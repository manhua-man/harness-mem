"""Host-entry main module for the ``harness-mem-hook`` console script.

This module is the adapter that maps explicit IDE hook actions to in-process
runtime calls. It never shells out to the ``harness-mem`` console script.

``dream-end`` runs a gated dream maintenance tick and emits one JSON document.
``post-turn-maintenance`` syncs evidence, queues Agent-led distillation, and
emits one JSON document. It does not claim semantic summarization completed.
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
from pathlib import Path
import sys
from typing import Any, Literal, Sequence

from harness_mem import __version__
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import load_merged_config
from harness_mem.commands.support import (
    ensure_project_profile,
    normalize_client_name,
    resolve_project_context,
)
from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult

HostEntryStatus = Literal["skipped", "completed", "failed"]

logger = logging.getLogger("harness_mem.host_entry")

_VALID_SOURCES = ("user", "agent", "ide_hook")
_VALID_ACTIONS = ("dream-end", "post-turn-maintenance", "wake-start")
_VALID_CLIENTS = (
    "claude-code",
    "cursor",
    "grok",
    "codex",
    "codex-archive",
    "hermes",
    "opencode",
    "antigravity",
)
_VALID_ADAPTERS = (
    "antigravity-pre",
    "antigravity-stop",
    "codex-stop",
    "hermes-pre",
    "hermes-post",
)
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
    host_status: HostEntryStatus = "skipped" if status == "skipped" else "completed"
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
    if status == "queued":
        next_step = "queued: evidence synced; an Agent must consume the pending distill task"
    elif status == "in_progress":
        next_step = "in progress: an Agent is already consuming this evidence"
    elif status == "completed":
        next_step = "completed: transcript evidence is up to date"
    else:
        next_step = "failed: transcript evidence staging did not complete"
    return {
        "action": action,
        "status": status or "failed",
        "next_step": next_step,
        "project_name": payload.get("project_name"),
        "project_root": payload.get("project_root"),
        "trigger_id": payload.get("trigger_id"),
        "success": bool(payload.get("success")),
        "evidence_packet": payload.get("evidence_packet"),
        "distill_job": payload.get("distill_job"),
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the host entry (Req 2.2-2.6)."""
    parser = argparse.ArgumentParser(
        prog="harness-mem-hook",
        allow_abbrev=False,
    )
    parser.add_argument("--version", action="version", version=f"harness-mem-hook {__version__}")
    parser.add_argument("--adapter", choices=_VALID_ADAPTERS)
    parser.add_argument("--action", choices=_VALID_ACTIONS)
    parser.add_argument("--project-root")
    parser.add_argument("--source", choices=_VALID_SOURCES)
    parser.add_argument("--trigger-id", default=None)
    parser.add_argument("--client", choices=_VALID_CLIENTS, default=None)
    return parser


def validate_args(args: argparse.Namespace) -> str | None:
    """Enforce the length/count/path bounds argparse can't (Req 2.2, 2.4, 2.5).

    Returns a one-line error message naming the offending flag and the violated
    constraint, or ``None`` when every bound is satisfied. The ``--source`` enum
    is already enforced by argparse ``choices``, so it is not re-checked here.
    """
    project_root = args.project_root
    if project_root is None:
        return "--project-root is required"
    if len(project_root) > _MAX_PROJECT_ROOT_CHARS:
        return f"--project-root exceeds {_MAX_PROJECT_ROOT_CHARS} characters"
    if not os.path.isabs(project_root):
        return f"--project-root must be an absolute path: {project_root!r}"
    if not os.path.isdir(project_root):
        return f"--project-root must be an existing directory: {project_root!r}"

    if args.trigger_id is not None and len(args.trigger_id) > _MAX_TRIGGER_ID_CHARS:
        return f"--trigger-id exceeds {_MAX_TRIGGER_ID_CHARS} characters"

    return None


def _adapter_payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - passive hooks must fail open.
        return {}
    return value if isinstance(value, dict) else {}


def _adapter_request(args: argparse.Namespace, payload: dict[str, Any]) -> argparse.Namespace:
    """Translate one host protocol payload into a normal host-entry request."""

    adapter = args.adapter
    assert adapter is not None
    workspace_paths = payload.get("workspacePaths")
    roots = workspace_paths if isinstance(workspace_paths, list) else []
    extra = payload.get("extra")
    extra_dict = extra if isinstance(extra, dict) else {}
    root_candidates = [
        *(str(value) for value in roots),
        payload.get("project_root"),
        payload.get("projectRoot"),
        payload.get("workspace"),
        payload.get("cwd"),
        extra_dict.get("project_root"),
        extra_dict.get("projectRoot"),
        extra_dict.get("workspace"),
        extra_dict.get("cwd"),
        args.project_root,
        os.getcwd(),
    ]
    project_root = next(
        (
            str(Path(str(value)).expanduser().resolve())
            for value in root_candidates
            if value and Path(str(value)).expanduser().is_dir()
        ),
        args.project_root,
    )

    if adapter == "antigravity-pre":
        action, client, default_trigger = "wake-start", "antigravity", "antigravity-pre-invocation"
        trigger_id = payload.get("conversationId") or default_trigger
    elif adapter == "antigravity-stop":
        action, client, default_trigger = "post-turn-maintenance", "antigravity", "antigravity-stop"
        trigger_id = payload.get("conversationId") or default_trigger
    elif adapter == "codex-stop":
        action, client, default_trigger = "post-turn-maintenance", "codex", "codex-stop"
        trigger_id = payload.get("turn_id") or payload.get("session_id") or default_trigger
    else:
        action = "wake-start" if adapter == "hermes-pre" else "post-turn-maintenance"
        client, default_trigger = "hermes", f"{adapter}-llm"
        trigger_id = payload.get("session_id") or extra_dict.get("task_id") or default_trigger

    return argparse.Namespace(
        action=action,
        project_root=project_root,
        source="ide_hook",
        trigger_id=str(trigger_id),
        client=client,
    )


def _run_adapter(args: argparse.Namespace) -> int:
    """Run a passive Hook adapter and emit only its host-specific response."""

    payload = _adapter_payload()
    request = _adapter_request(args, payload)
    try:
        exit_code, stdout_payload = asyncio.run(run(request))
    except Exception:  # noqa: BLE001 - adapters are passive by contract.
        logger.exception("hook adapter failed: %s", args.adapter)
        exit_code, stdout_payload = ExitCode.HOOK_FAILED, None

    adapter = args.adapter
    assert adapter is not None
    if adapter == "antigravity-pre":
        message = stdout_payload.strip() if exit_code == ExitCode.SUCCESS and stdout_payload else ""
        response: dict[str, Any] = (
            {"injectSteps": [{"ephemeralMessage": message}]} if message else {"injectSteps": []}
        )
        sys.stdout.write(json.dumps(response) + "\n")
    elif adapter == "antigravity-stop":
        sys.stdout.write(json.dumps({"decision": "stop", "reason": "memory evidence staging finished"}) + "\n")
    elif adapter == "hermes-pre":
        context = stdout_payload.rstrip("\n") if exit_code == ExitCode.SUCCESS and stdout_payload else ""
        sys.stdout.write(json.dumps({"context": context}) + "\n" if context else "{}\n")
    else:
        sys.stdout.write("{}\n")
    return int(ExitCode.SUCCESS)


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

    client_override = normalize_client_name(getattr(args, "client", None))
    previous_client_env = os.environ.get("HARNESS_MEM_CLIENT")
    if client_override and client_override != "auto":
        os.environ["HARNESS_MEM_CLIENT"] = client_override

    try:
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
        project_context = resolve_project_context(
            None,
            project_root=args.project_root,
            required=True,
            action_label=f"host-entry {args.action}",
        )
        if project_context is None:
            return (ExitCode.ARG_VALIDATION_ERROR, None)
        project_name = project_context.project_name

        backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        await backend.init()
        try:
            if project_context.project_root is not None:
                await ensure_project_profile(project_name, project_context.project_root)

            def record_success(action: str) -> None:
                if project_context.project_root is None:
                    return
                try:
                    from harness_mem.hook_receipts import record_hook_execution

                    record_hook_execution(
                        backend.data_dir,
                        project_root=project_context.project_root,
                        project_name=project_name,
                        client=client_override or "unknown",
                        action=action,
                        source=args.source,
                        trigger_id=args.trigger_id,
                    )
                except Exception:  # noqa: BLE001 - receipt failure must not fail the hook.
                    logger.warning(
                        "could not persist hook execution receipt",
                        exc_info=True,
                    )

            if args.action == "wake-start":
                from harness_mem.commands.wake import build_wake_injection

                try:
                    text = await build_wake_injection(backend, project_name)
                except Exception:  # noqa: BLE001 - host entry is total.
                    logger.exception("host_entry caught unhandled wake exception")
                    return (ExitCode.HOOK_FAILED, None)
                record_success("wake-start")
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
                post_turn_result = _post_turn_host_result(maintenance_payload)
                exit_code = (
                    ExitCode.SUCCESS
                    if post_turn_result["status"]
                    in ("completed", "queued", "in_progress", "skipped")
                    else ExitCode.HOOK_FAILED
                )
                if exit_code == ExitCode.SUCCESS:
                    record_success("post-turn-maintenance")
                return (exit_code, json.dumps(post_turn_result, sort_keys=True))

            logger.error("unsupported action: %s", args.action)
            return (ExitCode.ARG_VALIDATION_ERROR, None)
        finally:
            await backend.close()
    finally:
        if previous_client_env is None:
            os.environ.pop("HARNESS_MEM_CLIENT", None)
        else:
            os.environ["HARNESS_MEM_CLIENT"] = previous_client_env


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
    if args.adapter:
        if args.project_root is None and not args.adapter.startswith("hermes-"):
            parser.error("--project-root is required with --adapter")
        return _run_adapter(args)
    if args.action is None:
        parser.error("--action is required")
    if args.project_root is None:
        parser.error("--project-root is required")
    if args.source is None:
        parser.error("--source is required")
    exit_code, stdout_payload = asyncio.run(run(args))
    if stdout_payload is not None:
        sys.stdout.write(stdout_payload + "\n")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
