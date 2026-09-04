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
import math
import os
from pathlib import Path
import sys
import time
from typing import Any, Literal, Sequence

from harness_mem import __version__
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import load_merged_config
from harness_mem.commands.support import (
    detect_runtime_client,
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
    "codex-start",
    "codex-stop",
    "hermes-pre",
    "hermes-post",
)
_MAX_PROJECT_ROOT_CHARS = 4096
_MAX_TRIGGER_ID_CHARS = 256
_DEFAULT_WAIT_TIMEOUT_SECONDS = 60.0
_MAX_WAIT_TIMEOUT_SECONDS = 3600.0
_WAIT_POLL_SECONDS = 0.1
_TERMINAL_AUTONOMOUS_STATES = frozenset(
    {"succeeded", "partial", "deferred", "busy", "idle", "failed"}
)
_REPEATED_WAKE_CLIENTS = frozenset({"hermes", "antigravity"})
_WAKE_FALLBACK_TRIGGERS = frozenset({"hermes-pre-llm", "antigravity-pre-invocation"})


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
        next_step = (
            "queued: evidence synced; an Agent must consume the pending distill task"
        )
    elif status == "in_progress":
        next_step = "in progress: an Agent is already consuming this evidence"
    elif status == "completed":
        next_step = "completed: transcript evidence is up to date"
    elif status == "deferred":
        next_step = "deferred: an existing distill job is waiting for its retry window"
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
        "autonomous": payload.get("autonomous"),
        "summary": summary,
    }


def build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser for the host entry (Req 2.2-2.6)."""
    parser = argparse.ArgumentParser(
        prog="harness-mem-hook",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--version", action="version", version=f"harness-mem-hook {__version__}"
    )
    parser.add_argument("--adapter", choices=_VALID_ADAPTERS)
    parser.add_argument("--action", choices=_VALID_ACTIONS)
    parser.add_argument("--project-root")
    parser.add_argument("--source", choices=_VALID_SOURCES)
    parser.add_argument("--trigger-id", default=None)
    parser.add_argument("--client", choices=_VALID_CLIENTS, default=None)
    parser.add_argument(
        "--wait",
        action="store_true",
        help=(
            "wait for the detached post-turn autonomous receipt and emit its "
            "terminal state; IDE adapters remain non-blocking unless enabled"
        ),
    )
    parser.add_argument(
        "--wait-timeout",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "maximum --wait duration (default: 60, maximum: 3600); a timeout "
            "returns a failed terminal receipt"
        ),
    )
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

    wait_timeout = getattr(args, "wait_timeout", None)
    if wait_timeout is not None and not getattr(args, "wait", False):
        return "--wait-timeout requires --wait"
    if wait_timeout is not None and (
        not math.isfinite(wait_timeout)
        or wait_timeout <= 0
        or wait_timeout > _MAX_WAIT_TIMEOUT_SECONDS
    ):
        return (
            "--wait-timeout must be greater than 0 and no more than "
            f"{_MAX_WAIT_TIMEOUT_SECONDS:g} seconds"
        )

    return None


def _wait_coordinates(
    args: argparse.Namespace,
) -> tuple[Path, Path, str, Path, dict[str, Any] | None]:
    """Resolve and snapshot the receipt that predates one detached dispatch."""

    from harness_mem.autonomous.worker import (
        autonomous_receipt_path,
        read_autonomous_receipt,
    )
    from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR

    project_context = resolve_project_context(
        None,
        project_root=args.project_root,
        required=True,
        action_label="host-entry receipt wait",
    )
    if project_context is None or project_context.project_root is None:
        raise ValueError("could not resolve project context for receipt wait")
    project_root = project_context.project_root
    project_name = project_context.project_name
    receipt_path = autonomous_receipt_path(
        DEFAULT_DATA_DIR,
        project_name=project_name,
        project_root=project_root,
    )
    initial = read_autonomous_receipt(
        DEFAULT_DATA_DIR,
        project_name=project_name,
        project_root=project_root,
    )
    return DEFAULT_DATA_DIR, project_root, project_name, receipt_path, initial


def _wait_for_autonomous_receipt(
    *,
    data_dir: Path,
    project_root: Path,
    project_name: str,
    trigger_id: str | None,
    dispatch_generation: str | None = None,
    receipt_path: Path,
    initial_receipt: dict[str, Any] | None,
    timeout_seconds: float,
    read_receipt: Any = None,
    monotonic: Any = None,
    sleep: Any = None,
) -> tuple[int, str]:
    """Poll one receipt to a known terminal state within a hard deadline."""

    if read_receipt is None:
        from harness_mem.autonomous.worker import (
            read_autonomous_receipt as read_receipt,
        )

    clock = monotonic or time.monotonic
    pause = sleep or time.sleep
    deadline = clock() + timeout_seconds
    while True:
        receipt = read_receipt(
            data_dir,
            project_name=project_name,
            project_root=project_root,
        )
        state = str((receipt or {}).get("state") or "")
        is_new = receipt is not None and receipt != initial_receipt
        trigger_matches = (receipt or {}).get("trigger_id") == trigger_id
        generation_matches = dispatch_generation is None or (
            (receipt or {}).get("dispatch_generation") == dispatch_generation
        )
        if (
            is_new
            and trigger_matches
            and generation_matches
            and state in _TERMINAL_AUTONOMOUS_STATES
        ):
            error = receipt.get("error") or receipt.get("last_batch_error")
            success = state in {"succeeded", "idle"} and not error
            payload = {
                "action": "post-turn-maintenance",
                "success": success,
                "trigger": trigger_id,
                "trigger_id": trigger_id,
                "dispatch_generation": dispatch_generation,
                "state": state,
                "job": receipt.get("job_id"),
                "job_id": receipt.get("job_id"),
                "error": error,
                "receipt": str(receipt_path),
            }
            code = ExitCode.SUCCESS if success else ExitCode.HOOK_FAILED
            return int(code), json.dumps(payload, sort_keys=True)

        remaining = deadline - clock()
        if remaining <= 0:
            payload = {
                "action": "post-turn-maintenance",
                "success": False,
                "trigger": trigger_id,
                "trigger_id": trigger_id,
                "state": "timeout",
                "job": None,
                "job_id": None,
                "error": {
                    "kind": "wait_timeout",
                    "message": (
                        "no matching terminal autonomous receipt was observed "
                        f"within {timeout_seconds:g} seconds"
                    ),
                },
                "receipt": str(receipt_path),
            }
            return int(ExitCode.HOOK_FAILED), json.dumps(payload, sort_keys=True)
        pause(min(_WAIT_POLL_SECONDS, remaining))


def _adapter_payload() -> dict[str, Any]:
    try:
        value = json.load(sys.stdin)
    except Exception:  # noqa: BLE001 - passive hooks must fail open.
        return {}
    return value if isinstance(value, dict) else {}


def _adapter_request(
    args: argparse.Namespace, payload: dict[str, Any]
) -> argparse.Namespace:
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
        action, client, default_trigger = (
            "wake-start",
            "antigravity",
            "antigravity-pre-invocation",
        )
        trigger_id = payload.get("conversationId") or default_trigger
    elif adapter == "antigravity-stop":
        action, client, default_trigger = (
            "post-turn-maintenance",
            "antigravity",
            "antigravity-stop",
        )
        trigger_id = payload.get("conversationId") or default_trigger
    elif adapter == "codex-start":
        action, client, default_trigger = "wake-start", "codex", "codex-session-start"
        trigger_id = payload.get("session_id") or default_trigger
    elif adapter == "codex-stop":
        action, client, default_trigger = "post-turn-maintenance", "codex", "codex-stop"
        # Use Codex's session id for both SessionStart and Stop receipts.  This
        # lets health prove that both lifecycle actions came from one actual
        # session instead of combining unrelated CLI/Desktop executions.
        trigger_id = (
            payload.get("session_id") or payload.get("turn_id") or default_trigger
        )
    else:
        action = "wake-start" if adapter == "hermes-pre" else "post-turn-maintenance"
        client, default_trigger = "hermes", f"{adapter}-llm"
        trigger_id = (
            payload.get("session_id") or extra_dict.get("task_id") or default_trigger
        )

    return argparse.Namespace(
        action=action,
        project_root=project_root,
        source="ide_hook",
        trigger_id=str(trigger_id),
        client=client,
        wait=getattr(args, "wait", False),
        wait_timeout=getattr(args, "wait_timeout", None),
    )


def _run_request(args: argparse.Namespace) -> tuple[int, str | None]:
    """Run one request and optionally resolve its detached autonomous receipt."""

    wait = bool(getattr(args, "wait", False))
    coordinates = _wait_coordinates(args) if wait else None
    exit_code, stdout_payload = asyncio.run(run(args))
    if not wait or exit_code != ExitCode.SUCCESS or coordinates is None:
        return int(exit_code), stdout_payload

    data_dir, project_root, project_name, receipt_path, initial = coordinates
    dispatch_generation: str | None = None
    try:
        dispatch_payload = json.loads(stdout_payload or "{}")
        summary = dispatch_payload.get("summary")
        if isinstance(summary, dict) and summary.get("dispatch_generation"):
            dispatch_generation = str(summary["dispatch_generation"])
    except (TypeError, ValueError, json.JSONDecodeError):
        dispatch_generation = None
    return _wait_for_autonomous_receipt(
        data_dir=data_dir,
        project_root=project_root,
        project_name=project_name,
        trigger_id=args.trigger_id,
        dispatch_generation=dispatch_generation,
        receipt_path=receipt_path,
        initial_receipt=initial,
        timeout_seconds=float(
            getattr(args, "wait_timeout", None) or _DEFAULT_WAIT_TIMEOUT_SECONDS
        ),
    )


def _run_adapter(args: argparse.Namespace) -> int:
    """Run a passive Hook adapter and emit only its host-specific response."""

    payload = _adapter_payload()
    if getattr(args, "wait", False) and args.adapter == "codex-stop" and not (
        payload.get("session_id") or payload.get("turn_id")
    ):
        error = {
            "action": "post-turn-maintenance",
            "success": False,
            "trigger": "codex-stop",
            "trigger_id": "codex-stop",
            "state": "failed",
            "job": None,
            "job_id": None,
            "error": {
                "kind": "missing_hook_identity",
                "message": (
                    "--wait with codex-stop requires a JSON session_id or turn_id "
                    "payload on stdin"
                ),
            },
            "receipt": None,
        }
        sys.stdout.write(json.dumps(error, sort_keys=True) + "\n")
        return int(ExitCode.ARG_VALIDATION_ERROR)
    request = _adapter_request(args, payload)
    try:
        exit_code, stdout_payload = _run_request(request)
    except Exception:  # noqa: BLE001 - adapters are passive by contract.
        logger.exception("hook adapter failed: %s", args.adapter)
        exit_code, stdout_payload = ExitCode.HOOK_FAILED, None

    adapter = args.adapter
    assert adapter is not None
    if getattr(args, "wait", False):
        sys.stdout.write((stdout_payload or "{}") + "\n")
    elif adapter == "codex-start":
        context = (
            stdout_payload.rstrip("\n")
            if exit_code == ExitCode.SUCCESS and stdout_payload
            else ""
        )
        sys.stdout.write(context + "\n")
    elif adapter == "antigravity-pre":
        message = (
            stdout_payload.strip()
            if exit_code == ExitCode.SUCCESS and stdout_payload
            else ""
        )
        response: dict[str, Any] = (
            {"injectSteps": [{"ephemeralMessage": message}]}
            if message
            else {"injectSteps": []}
        )
        sys.stdout.write(json.dumps(response) + "\n")
    elif adapter == "antigravity-stop":
        sys.stdout.write(
            json.dumps(
                {"decision": "stop", "reason": "memory evidence staging finished"}
            )
            + "\n"
        )
    elif adapter == "hermes-pre":
        context = (
            stdout_payload.rstrip("\n")
            if exit_code == ExitCode.SUCCESS and stdout_payload
            else ""
        )
        sys.stdout.write(json.dumps({"context": context}) + "\n" if context else "{}\n")
    else:
        sys.stdout.write("{}\n")
    if getattr(args, "wait", False) or (
        request.action == "post-turn-maintenance" and exit_code != ExitCode.SUCCESS
    ):
        return int(exit_code)
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

    requested_client = normalize_client_name(getattr(args, "client", None))
    client_override = (
        detect_runtime_client()
        if requested_client in {"auto", "agent"}
        else requested_client
    )
    previous_client_env = os.environ.get("HARNESS_MEM_CLIENT")
    if client_override:
        os.environ["HARNESS_MEM_CLIENT"] = client_override

    try:
        from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR

        project_context = resolve_project_context(
            None,
            project_root=args.project_root,
            required=True,
            action_label=f"host-entry {args.action}",
        )
        if project_context is None or project_context.project_root is None:
            return (ExitCode.ARG_VALIDATION_ERROR, None)
        project_root = project_context.project_root
        project_name = project_context.project_name

        from harness_mem.autonomous.hook_guard import (
            autonomous_provider_hook_reentry_blocked,
            record_hook_reentry_block,
        )

        if autonomous_provider_hook_reentry_blocked(
            args.action,
            data_dir=DEFAULT_DATA_DIR,
        ):
            record_hook_reentry_block(
                DEFAULT_DATA_DIR,
                project_name=project_name,
                project_root=project_root,
                action=args.action,
                trigger_id=args.trigger_id,
            )
            payload = {
                "action": args.action,
                "success": True,
                "status": "skipped",
                "reason": "autonomous_provider_hook_reentry_blocked",
                "project_root": str(project_root),
                "trigger_id": args.trigger_id,
                "summary": {
                    "hook_reentry_blocked": True,
                    "autonomous_provider": True,
                },
            }
            return (ExitCode.SUCCESS, json.dumps(payload, sort_keys=True))

        if (
            args.action == "post-turn-maintenance"
            and args.source == "ide_hook"
            and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") != "1"
        ):
            if client_override is None:
                payload = {
                    "action": "post-turn-maintenance",
                    "success": False,
                    "status": "failed",
                    "project_root": str(project_root),
                    "trigger_id": args.trigger_id,
                    "summary": {
                        "background": True,
                        "spawned": False,
                    },
                    "error": {
                        "kind": "host_not_detected",
                        "message": (
                            "The Hook could not identify its Agent host, so no "
                            "background work was started."
                        ),
                    },
                }
                return (ExitCode.HOOK_FAILED, json.dumps(payload, sort_keys=True))
            try:
                from harness_mem.hook_background import dispatch_post_turn

                dispatch = dispatch_post_turn(
                    DEFAULT_DATA_DIR,
                    project_root=project_root,
                    client=client_override,
                    source=args.source,
                    trigger_id=args.trigger_id,
                )
                payload = {
                    "action": "post-turn-maintenance",
                    "success": True,
                    "status": "queued",
                    "project_root": str(project_root),
                    "trigger_id": args.trigger_id,
                    "summary": {
                        "background": True,
                        "spawned": dispatch.spawned,
                        "coalesced": dispatch.coalesced,
                        "dispatch_generation": dispatch.generation,
                    },
                }
                return (ExitCode.SUCCESS, json.dumps(payload, sort_keys=True))
            except Exception as exc:  # noqa: BLE001 - Hook must remain passive.
                logger.error(
                    "could not dispatch background hook maintenance; no inline work ran",
                    exc_info=True,
                )
                payload = {
                    "action": "post-turn-maintenance",
                    "success": False,
                    "status": "failed",
                    "project_root": str(project_root),
                    "trigger_id": args.trigger_id,
                    "summary": {
                        "background": True,
                        "spawned": False,
                    },
                    "error": {
                        "kind": "background_dispatch_failed",
                        "message": (
                            "The detached background worker could not be started; "
                            "the Hook did not run maintenance inline."
                        ),
                        "exception": type(exc).__name__,
                    },
                }
                return (ExitCode.HOOK_FAILED, json.dumps(payload, sort_keys=True))

        # ---- 2. load merged config (Req 3, Req 4.8) ------------------------
        try:
            merged = load_merged_config(project_root)
        except ConfigError as exc:
            logger.error("config error: %s", exc)
            return (ExitCode.CONFIG_LOAD_ERROR, None)

        # ---- 3. build backend ---------------------------------------------
        from harness_mem.storage.local_memory_backend import LocalMemoryBackend

        if (
            args.action == "wake-start"
            and client_override in _REPEATED_WAKE_CLIENTS
            and args.trigger_id
            and args.trigger_id not in _WAKE_FALLBACK_TRIGGERS
            and project_context.project_root is not None
        ):
            from harness_mem.hook_receipts import read_hook_execution_receipt

            receipt = read_hook_execution_receipt(
                DEFAULT_DATA_DIR,
                project_root=project_context.project_root,
                client=client_override,
                action="wake-start",
            )
            if receipt is not None and receipt.get("trigger_id") == args.trigger_id:
                return (ExitCode.SUCCESS, "")

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
                    from harness_mem.commands.maintenance import (
                        run_post_turn_maintenance,
                    )

                    maintenance_payload = await run_post_turn_maintenance(
                        backend,
                        project_name=project_name,
                        project_root=args.project_root,
                        config=merged,
                        source=args.source,
                        trigger_id=args.trigger_id,
                    )
                    if (
                        not maintenance_payload.get("success")
                        and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER")
                        == "1"
                    ):
                        # The foreground Hook has already returned ``queued``.
                        # Persist the staging failure so ``--wait`` receives the
                        # real terminal result rather than an arbitrary timeout.
                        from harness_mem.autonomous.worker import (
                            record_post_turn_preflight_failure,
                            record_post_turn_retry_backoff,
                        )
                        from harness_mem.hook_background import (
                            background_generation_from_env,
                        )

                        evidence_packet = maintenance_payload.get("evidence_packet")
                        evidence_error = (
                            evidence_packet.get("error")
                            if isinstance(evidence_packet, dict)
                            else None
                        )
                        summary = maintenance_payload.get("summary")
                        retry_after = (
                            summary.get("distill_retry_after")
                            if isinstance(summary, dict)
                            else None
                        )
                        job_id = (
                            summary.get("distill_job_id")
                            if isinstance(summary, dict)
                            else None
                        )
                        if (
                            maintenance_payload.get("status") == "deferred"
                            and isinstance(job_id, str)
                            and isinstance(retry_after, str)
                        ):
                            record_post_turn_retry_backoff(
                                backend.data_dir,
                                project_name=project_name,
                                project_root=project_root,
                                trigger_id=args.trigger_id,
                                client=client_override or "auto",
                                dispatch_generation=background_generation_from_env(),
                                job_id=job_id,
                                retry_after=retry_after,
                            )
                        else:
                            record_post_turn_preflight_failure(
                                backend.data_dir,
                                project_name=project_name,
                                project_root=project_root,
                                trigger_id=args.trigger_id,
                                client=client_override or "auto",
                                dispatch_generation=background_generation_from_env(),
                                error={
                                    "kind": "evidence_staging_failed",
                                    "message": str(
                                        evidence_error
                                        or "post-turn transcript staging did not complete"
                                    )[:512],
                                },
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
                    in ("completed", "queued", "in_progress", "deferred", "skipped")
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
    if args.wait:
        if args.adapter and args.adapter not in {
            "antigravity-stop",
            "codex-stop",
            "hermes-post",
        }:
            parser.error("--wait is only supported by post-turn adapters")
        if not args.adapter and args.action != "post-turn-maintenance":
            parser.error("--wait is only supported with --action post-turn-maintenance")
    if args.wait_timeout is not None and not args.wait:
        parser.error("--wait-timeout requires --wait")
    if args.wait_timeout is not None and (
        not math.isfinite(args.wait_timeout)
        or args.wait_timeout <= 0
        or args.wait_timeout > _MAX_WAIT_TIMEOUT_SECONDS
    ):
        parser.error(
            "--wait-timeout must be greater than 0 and no more than "
            f"{_MAX_WAIT_TIMEOUT_SECONDS:g} seconds"
        )
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
    if args.wait and args.source != "ide_hook":
        parser.error("--wait requires --source ide_hook")
    worker_generation: str | None = None
    worker_client = normalize_client_name(args.client)
    if (
        os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1"
        and args.action == "post-turn-maintenance"
        and worker_client
        and worker_client != "auto"
    ):
        from harness_mem.hook_background import (
            background_generation_from_env,
            load_background_request,
        )
        from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR

        request = load_background_request(
            DEFAULT_DATA_DIR,
            project_root=Path(args.project_root),
            client=worker_client,
        )
        if request is not None:
            args.trigger_id = request.trigger_id
            worker_generation = request.generation
        else:
            worker_generation = background_generation_from_env()
    try:
        exit_code, stdout_payload = _run_request(args)
    finally:
        if worker_generation is not None and worker_client:
            from harness_mem.hook_background import finish_background_worker
            from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR

            try:
                finish_background_worker(
                    DEFAULT_DATA_DIR,
                    project_root=Path(args.project_root),
                    client=worker_client,
                    processed_generation=worker_generation,
                )
            except Exception:  # noqa: BLE001 - background handoff is best-effort.
                logger.warning(
                    "could not hand off coalesced hook maintenance", exc_info=True
                )
    if stdout_payload is not None:
        sys.stdout.write(stdout_payload + "\n")
    return int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
