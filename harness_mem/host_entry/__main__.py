"""Host-entry main module — ``python -m harness_mem.host_entry`` (v2.4.1 Req 1, 2, 6).

This module is the *adapter* that maps a tiny CLI surface to a single in-process
call to v2.4.0 ``reflection_once``. IDE hooks, cron jobs, and external
schedulers invoke it directly; it never shells out to the ``harness-mem``
console script (Req 1.6).

Structure: testable pure-ish functions (``build_parser``, ``validate_args``,
``apply_config_overrides``) plus an async ``run`` that holds the core logic and
never raises, plus a thin synchronous ``main`` that wires argparse -> ``run`` ->
stdout/exit-code.

Output channel discipline (Req 5.7, project rule P0 "MCP stdio protection"):
all logging/diagnostics go to stderr via ``logging.basicConfig(stream=sys.stderr)``;
stdout carries at most one JSON document terminated by exactly one newline.

Interruption handling (Req 6.6): this module registers NO signal handlers.
Interruption is observed entirely through persisted ``reflection_jobs`` state
(v2.4.0 expired-lease re-acquisition). We deliberately do not import ``signal``.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import logging
import os
import sys
from typing import Any, Sequence

from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult

logger = logging.getLogger("harness_mem.host_entry")

_VALID_SOURCES = ("user", "agent", "ide_hook", "scheduler")
_MAX_PROJECT_ROOT_CHARS = 4096
_MAX_TRIGGER_ID_CHARS = 256
_MAX_SESSION_IDS = 1024
_MAX_SESSION_ID_CHARS = 256

# Dotted config-override keys recognized by --config-override, mapped to the
# MergedConfig field they set. Per the design's "keep it strictly to setting
# recognized keys" note, only these four keys may be overridden; anything else
# raises ValueError and surfaces as an arg-validation error (exit 2).
_OVERRIDE_KEYS = {
    "triggers.after_agent": "triggers_after_agent",
    "triggers.scheduler": "triggers_scheduler",
    "distill.mode": "distill_mode",
    "worker.mode": "worker_mode",
}


def _dream_tick_host_result(payload: dict[str, Any]) -> HostEntryResult:
    """Adapt a v3.1 dream auto-tick payload to the stable host JSON shape."""
    if payload.get("success") is False:
        return HostEntryResult(
            phase="metabolism",
            status="failed",
            next_step="failed: dream auto tick failed",
            job_id=payload.get("job_id"),
            candidates_written=0,
            observations_written=0,
            error={
                "stage": "dream",
                "reason": str(payload.get("error") or payload.get("reason") or ""),
            },
        )

    summary_value = payload.get("summary")
    summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    processed = int(summary.get("processed") or 0)
    status = str(payload.get("status") or "")
    next_step = (
        "completed: dream auto tick skipped"
        if status == "skipped"
        else "completed: dream auto tick completed"
    )
    return HostEntryResult(
        phase="metabolism",
        status="completed",
        next_step=next_step,
        job_id=payload.get("job_id"),
        candidates_written=processed,
        observations_written=0,
        error=None,
    )


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the host entry (Req 2.2-2.6)."""
    parser = argparse.ArgumentParser(
        prog="python -m harness_mem.host_entry",
        allow_abbrev=False,
    )
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--source", required=True, choices=_VALID_SOURCES)
    parser.add_argument("--trigger-id", default=None)
    parser.add_argument("--session-ids", nargs="*", default=[])
    parser.add_argument(
        "--config-override",
        action="append",
        default=[],
        metavar="KEY=VALUE",
    )
    return parser


def validate_args(args: argparse.Namespace) -> str | None:
    """Enforce the length/count/path bounds argparse can't (Req 2.2, 2.4, 2.5).

    Returns a one-line error message naming the offending flag and the violated
    constraint, or ``None`` when every bound is satisfied. The ``--source`` enum
    is already enforced by argparse ``choices``, so it is not re-checked here.
    """
    project_root: str = args.project_root
    if len(project_root) > _MAX_PROJECT_ROOT_CHARS:
        return f"--project-root exceeds {_MAX_PROJECT_ROOT_CHARS} characters"
    if not os.path.isabs(project_root):
        return f"--project-root must be an absolute path: {project_root!r}"
    if not os.path.isdir(project_root):
        return f"--project-root must be an existing directory: {project_root!r}"

    if args.trigger_id is not None and len(args.trigger_id) > _MAX_TRIGGER_ID_CHARS:
        return f"--trigger-id exceeds {_MAX_TRIGGER_ID_CHARS} characters"

    session_ids: list[str] = args.session_ids
    if len(session_ids) > _MAX_SESSION_IDS:
        return f"--session-ids exceeds {_MAX_SESSION_IDS} entries"
    for sid in session_ids:
        if len(sid) > _MAX_SESSION_ID_CHARS:
            return (
                f"--session-ids entry exceeds {_MAX_SESSION_ID_CHARS} "
                f"characters: {sid!r}"
            )
    return None


def apply_config_overrides(
    merged: MergedConfig, overrides: list[str]
) -> MergedConfig:
    """Apply ``KEY=VALUE`` overrides onto a copy of ``merged`` (Req 2.6).

    Each token is split on the first ``=`` only. A token with no ``=`` or with
    an unrecognized dotted key raises ``ValueError`` so the caller can surface
    it as an argument-validation error (exit 2). MergedConfig is frozen, so each
    override produces a NEW instance via ``dataclasses.replace`` — the loaded
    config is never mutated and nothing is persisted.
    """
    result = merged
    for token in overrides:
        key, sep, value = token.partition("=")
        if not sep:
            raise ValueError(f"--config-override must be KEY=VALUE: {token!r}")
        field_name = _OVERRIDE_KEYS.get(key)
        if field_name is None:
            raise ValueError(f"--config-override unrecognized key: {key!r}")
        # The override value arrives as a plain str; recognized fields are typed
        # as Literals. We set verbatim (value validation is the loader's job),
        # so the kwargs dict is Any-typed to keep dataclasses.replace happy.
        replacement: dict[str, Any] = {field_name: value}
        result = dataclasses.replace(result, **replacement)
    return result


async def run(args: argparse.Namespace) -> tuple[int, str | None]:
    """Core host-entry logic. Returns ``(exit_code, stdout_json_or_None)``.

    This function never raises: every failure path is mapped to an exit code and
    (where appropriate) a JSON document. Codes 2 and 3 emit no stdout JSON;
    codes 0 and 4 carry a single JSON document.
    """
    # ---- 1. post-argparse validation (Req 2.7) -------------------------
    err = validate_args(args)
    if err is not None:
        logger.error(err)
        return (ExitCode.ARG_VALIDATION_ERROR, None)

    # ---- 2. load merged config (Req 3, Req 4.8) ------------------------
    try:
        merged = load_merged_config(args.project_root)
    except ConfigError as exc:
        logger.error("config error: %s", exc)
        return (ExitCode.CONFIG_LOAD_ERROR, None)

    # ---- 3. apply --config-override for this call only (Req 2.6) -------
    try:
        merged = apply_config_overrides(merged, args.config_override)
    except ValueError as exc:
        logger.error("%s", exc)
        return (ExitCode.ARG_VALIDATION_ERROR, None)

    reflection_enabled = (
        merged.triggers_after_agent == "on" or merged.triggers_scheduler == "on"
    )
    dream_enabled = merged.dream_auto_enabled

    # ---- 4. disabled-runtime short-circuit -----------------------------
    # Evaluated strictly before any business command is imported or called.
    if not reflection_enabled and not dream_enabled:
        return (ExitCode.SUCCESS, HostEntryResult.skipped_default_off().to_json())

    reflection_once_func: Any | None = None
    if reflection_enabled:
        # ---- 5. lazy import of reflection_once (Req 1.7) ---------------
        # Imported lazily so the disabled-runtime path never touches the business
        # command, and so an import failure surfaces as a config-load error
        # (design: exit 3) rather than crashing the process.
        try:
            from harness_mem.commands.reflection_jobs import reflection_once as reflection_once_func
        except ImportError as exc:
            logger.error("reflection_once import failed: %s", exc)
            return (ExitCode.CONFIG_LOAD_ERROR, None)

    # ---- 6. build backend + job store (Req 1.1) ------------------------
    from harness_mem.storage.local_memory_backend import (
        DEFAULT_DATA_DIR,
        LocalMemoryBackend,
    )
    from pathlib import Path

    # reflection_once resolves missing project_root via commands-layer lookup,
    # but host entry already has the absolute repo path in hand. We therefore
    # pass both a stable project_name (basename) and the explicit
    # --project-root, falling back to the full path only when basename is
    # empty (for example, a filesystem root).
    project_name = Path(args.project_root).name or args.project_root

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    result = None
    dream_payload: dict[str, Any] | None = None
    try:
        if reflection_enabled and reflection_once_func is not None:
            job_store = backend.reflection_job_store
            # ---- 7. single reflection_once call (Req 2.8, 1.1) ---------
            try:
                result = await reflection_once_func(
                    project_name=project_name,
                    config=merged.to_reflection_config(),
                    source=args.source,
                    session_ids=args.session_ids or None,
                    trigger_id=args.trigger_id,
                    project_root=args.project_root,
                    job_store=job_store,
                )
            except Exception as exc:
                # v2.4.0 Req 10.5 says reflection_once never raises; if it does,
                # we surface it rather than swallow it (Req 5.9).
                logger.exception("host_entry caught unhandled exception")
                failure = HostEntryResult(
                    phase=None,
                    status="failed",
                    next_step="failed: host_entry caught unhandled exception",
                    job_id=None,
                    candidates_written=0,
                    observations_written=0,
                    error={
                        "stage": "host_entry",
                        "reason": f"{type(exc).__name__}: {exc}"[:512],
                    },
                )
                return (ExitCode.REFLECTION_FAILED, failure.to_json())

        if dream_enabled:
            try:
                from harness_mem.commands.dream import dream_auto_tick

                dream_payload = await dream_auto_tick(
                    backend,
                    project_name=project_name,
                    project_root=args.project_root,
                    config=merged,
                    source=args.source,
                )
            except Exception as exc:  # noqa: BLE001 - host entry is total.
                logger.exception("host_entry caught unhandled dream exception")
                dream_payload = {
                    "success": False,
                    "status": "failed",
                    "project_name": project_name,
                    "error": f"{type(exc).__name__}: {exc}"[:512],
                }
    finally:
        # Req: async resources always closed (project rule "异步资源清理").
        await backend.close()

    if not reflection_enabled:
        host_result = _dream_tick_host_result(dream_payload or {})
        exit_code = (
            ExitCode.SUCCESS
            if host_result.status == "completed"
            else ExitCode.REFLECTION_FAILED
        )
        return (exit_code, host_result.to_json())

    if dream_payload and dream_payload.get("success") is False:
        logger.warning("dream auto tick failed: %s", dream_payload.get("error"))

    # ---- 8. map result -> HostEntryResult + exit code (Req 5.1-5.5) ----
    assert result is not None
    host_result = HostEntryResult.from_reflection_result(result)
    if result.status in ("needs_distill", "completed"):
        exit_code = ExitCode.SUCCESS
    else:  # "failed" or "retryable"
        exit_code = ExitCode.REFLECTION_FAILED
    return (exit_code, host_result.to_json())


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point: configure logging, parse args, run, emit stdout, return code.

    ``logging.basicConfig(stream=sys.stderr)`` is configured FIRST so no log
    record can leak to stdout (Req 5.7). argparse handles its own exit-2 path
    for malformed flags. The single stdout write is the only thing this process
    ever writes to stdout, terminated by exactly one newline.
    """
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    parser = build_parser()
    args = parser.parse_args(argv)
    exit_code, stdout_payload = asyncio.run(run(args))
    if stdout_payload is not None:
        sys.stdout.write(stdout_payload + "\n")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
