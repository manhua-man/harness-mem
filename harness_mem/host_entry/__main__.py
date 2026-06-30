"""Host-entry main module — ``python -m harness_mem.host_entry``.

This module is the adapter that maps explicit IDE hook actions to in-process
runtime calls. It never shells out to the ``harness-mem`` console script.

``dream-end`` runs a gated dream maintenance tick and emits one JSON document.
``post-turn-maintenance`` runs session-distill packetization, low-risk
auto-review, and dream maintenance, then emits one JSON document.
``wake-start`` renders wake context for session-start injection and emits
plaintext.

Output channel discipline (Req 5.7, project rule P0 "MCP stdio protection"):
all logging/diagnostics go to stderr via ``logging.basicConfig(stream=sys.stderr)``;
stdout carries at most one JSON document terminated by exactly one newline.

Interruption handling: this module registers NO signal handlers. Dream
concurrency is handled by the internal dream job ledger.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
from typing import Any, Sequence

from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import load_merged_config
from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult

logger = logging.getLogger("harness_mem.host_entry")

_VALID_SOURCES = ("user", "agent", "ide_hook")
_VALID_ACTIONS = ("dream-end", "post-turn-maintenance", "wake-start")
_MAX_PROJECT_ROOT_CHARS = 4096
_MAX_TRIGGER_ID_CHARS = 256


def _dream_tick_host_result(payload: dict[str, Any]) -> HostEntryResult:
    """Adapt a dream auto-tick payload to the host JSON shape."""
    if payload.get("success") is False:
        return HostEntryResult(
            action="dream-end",
            status="failed",
            next_step="failed: dream auto tick failed",
            job_id=payload.get("job_id"),
            items_processed=0,
            error={
                "stage": "dream",
                "reason": str(payload.get("error") or payload.get("reason") or ""),
            },
        )

    summary_value = payload.get("summary")
    summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    processed = int(summary.get("processed") or 0)
    status = str(payload.get("status") or "")
    host_status = "skipped" if status == "skipped" else "completed"
    next_step = (
        "skipped: dream auto gate did not run"
        if host_status == "skipped"
        else "completed: dream maintenance tick completed"
    )
    return HostEntryResult(
        action="dream-end",
        status=host_status,
        next_step=next_step,
        job_id=payload.get("job_id"),
        items_processed=processed,
        error=None,
    )


def _post_turn_host_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Adapt the post-turn maintenance payload to the host JSON shape."""

    summary_value = payload.get("summary")
    summary: dict[str, Any] = summary_value if isinstance(summary_value, dict) else {}
    status = str(payload.get("status") or "")
    action = str(payload.get("action") or "post-turn-maintenance")
    next_step = (
        "partial: distill or dream maintenance needs follow-up"
        if status == "partial"
        else "completed: distill, auto-review, and dream maintenance completed"
    )
    return {
        "action": action,
        "status": status or "failed",
        "next_step": next_step,
        "project_name": payload.get("project_name"),
        "project_root": payload.get("project_root"),
        "trigger_id": payload.get("trigger_id"),
        "success": bool(payload.get("success")),
        "session_distill": payload.get("session_distill"),
        "auto_review": payload.get("auto_review"),
        "dream": payload.get("dream"),
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the host entry (Req 2.2-2.6)."""
    parser = argparse.ArgumentParser(
        prog="python -m harness_mem.host_entry",
        allow_abbrev=False,
    )
    parser.add_argument("--action", required=True, choices=_VALID_ACTIONS)
    parser.add_argument("--project-root", required=True)
    parser.add_argument("--source", required=True, choices=_VALID_SOURCES)
    parser.add_argument("--trigger-id", default=None)
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

    return None


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

    # ---- 3. build backend ---------------------------------------------
    from harness_mem.storage.local_memory_backend import (
        DEFAULT_DATA_DIR,
        LocalMemoryBackend,
    )
    from pathlib import Path

    # Host entry already has the absolute repo path in hand. Use its basename
    # as the stable project name, falling back to the full path only for edge
    # cases such as filesystem roots.
    project_name = Path(args.project_root).name or args.project_root

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        if args.action == "wake-start":
            from harness_mem.commands.wake import build_wake_injection

            try:
                text = await build_wake_injection(backend, project_name)
            except Exception:  # noqa: BLE001 - host entry is total.
                logger.exception("host_entry caught unhandled wake exception")
                return (ExitCode.HOOK_FAILED, None)
            return (ExitCode.SUCCESS, text)

        if args.action == "dream-end":
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
            host_result = _dream_tick_host_result(dream_payload)
            exit_code = (
                ExitCode.SUCCESS
                if host_result.status in ("completed", "skipped")
                else ExitCode.HOOK_FAILED
            )
            return (exit_code, host_result.to_json())

        if args.action == "post-turn-maintenance":
            try:
                from harness_mem.commands.maintenance import run_post_turn_maintenance

                maintenance_payload = await run_post_turn_maintenance(
                    backend,
                    project_name=project_name,
                    project_root=args.project_root,
                    config=merged,
                    source=args.source,
                    trigger_id=args.trigger_id,
                )
            except Exception as exc:  # noqa: BLE001 - host entry is total.
                logger.exception("host_entry caught unhandled post-turn exception")
                maintenance_payload = {
                    "success": False,
                    "status": "failed",
                    "action": "post-turn-maintenance",
                    "project_name": project_name,
                    "error": f"{type(exc).__name__}: {exc}"[:512],
                }
            host_result = _post_turn_host_result(maintenance_payload)
            exit_code = (
                ExitCode.SUCCESS
                if host_result["status"] in ("completed", "skipped")
                else ExitCode.HOOK_FAILED
            )
            return (exit_code, json.dumps(host_result, sort_keys=True))

        logger.error("unsupported action: %s", args.action)
        return (ExitCode.ARG_VALIDATION_ERROR, None)
    finally:
        await backend.close()


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
