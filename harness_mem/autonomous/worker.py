"""Durable autonomous distill runner used by detached host workers."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Callable, Iterator, Literal, Mapping, Protocol, Sequence
from uuid import uuid4

from harness_mem.autonomous.models import (
    AssimilationDecision,
    CandidateVerificationDecision,
    DistillCandidate,
    verification_scope_status,
    validate_atomic_knowledge_statement,
)
from harness_mem.autonomous.provider import (
    ProviderError,
    ProviderResult,
)
from harness_mem.autonomous.hook_guard import count_hook_reentry_blocks
from harness_mem.autonomous.executors.registry import build_semantic_executor
from harness_mem.autonomous.hook_guard import challenge_hook_reentry_guard
from harness_mem.autonomous.authorization import background_on
from harness_mem.commands.distill_lifecycle import pending_distill_jobs
from harness_mem.commands.separated_assimilation import (
    SeparatedPreparedAssimilation,
    create_separated_candidates,
    final_scope_payload,
    final_scope_proof,
    normalize_identical_replacements,
    prepare_separated_assimilation,
    validate_separated_assimilation_decision,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.session_distill import (
    SessionDistillJob,
    ZeroCandidateChallenge as RuntimeZeroCandidateChallenge,
)
from harness_mem.diagnostic_events import DiagnosticRun, diagnostic_parent_id, emit_current_stage
from harness_mem.hook_receipts import hook_configuration_fingerprint
from harness_mem.session_notes import (
    existing_session_note_path,
    is_meaningful_session_summary,
    materialize_session_note,
)
from harness_mem.storage.local_memory_backend import DEFAULT_DATA_DIR, LocalMemoryBackend


logger = logging.getLogger("harness_mem.autonomous")
_REVIEW_LEASE_SECONDS = 300
_MAX_ASSIMILATION_CANDIDATES_PER_CALL = 16
_RUNTIME_SOURCE_FILES = (
    Path(__file__),
    Path(__file__).with_name("models.py"),
    Path(__file__).with_name("provider.py"),
    Path(__file__).with_name("hook_guard.py"),
    Path(__file__).with_name("executors") / "constants.py",
    Path(__file__).with_name("executors") / "registry.py",
    Path(__file__).with_name("executors") / "host_cli.py",
    Path(__file__).with_name("executors") / "host_structured_cli.py",
    Path(__file__).with_name("executors") / "codex_app_server.py",
    Path(__file__).parents[1] / "host_entry" / "__main__.py",
    Path(__file__).parents[1] / "hook_background.py",
    Path(__file__).parents[1] / "diagnostic_events.py",
    Path(__file__).parents[1] / "commands" / "maintenance.py",
    Path(__file__).parents[1] / "commands" / "ingest.py",
    Path(__file__).parents[1] / "mcp" / "tool_handlers.py",
    Path(__file__).parents[1] / "commands" / "distill_lifecycle.py",
    Path(__file__).parents[1] / "commands" / "separated_assimilation.py",
    Path(__file__).parents[1] / "commands" / "knowledge_assimilation.py",
    Path(__file__).parents[1] / "commands" / "evidence_admission.py",
    Path(__file__).parents[1] / "adapters" / "parser.py",
    Path(__file__).parents[1] / "adapters" / "snapshot.py",
    Path(__file__).parents[1] / "adapters" / "codex" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "codex" / "archive_adapter.py",
    Path(__file__).parents[1] / "adapters" / "source_metadata.py",
    Path(__file__).parents[1] / "adapters" / "source_inspection.py",
    Path(__file__).parents[1] / "adapters" / "protocol.py",
    Path(__file__).parents[1] / "capture_policy.py",
    Path(__file__).parents[1] / "config" / "merge.py",
    Path(__file__).parents[1] / "adapters" / "claude_code" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "cursor" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "cursor" / "sqlite_history.py",
    Path(__file__).parents[1] / "adapters" / "grok" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "hermes" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "opencode" / "adapter.py",
    Path(__file__).parents[1] / "adapters" / "antigravity" / "adapter.py",
    Path(__file__).parents[1] / "commands" / "session_inventory.py",
    Path(__file__).parents[1] / "commands" / "session_overview.py",
    Path(__file__).parents[1] / "mcp" / "session_handlers.py",
    Path(__file__).parents[1] / "rust_core.py",
    Path(__file__).parents[1] / "commands" / "distill_result.py",
    Path(__file__).parents[1] / "commands" / "manual_distill.py",
    Path(__file__).parents[1] / "mcp" / "governance_handlers.py",
    Path(__file__).parents[1] / "mcp" / "tool_specs.py",
    Path(__file__).parents[1] / "mcp" / "distill_handlers.py",
    Path(__file__).parents[1] / "mcp" / "distill_projection.py",
    Path(__file__).parents[1] / "mcp" / "read_search_handlers.py",
    Path(__file__).parents[1] / "mcp" / "read_projection.py",
    Path(__file__).parents[1] / "read_knowledge.py",
    Path(__file__).parents[1] / "storage" / "knowledge_store.py",
    Path(__file__).parents[1] / "storage" / "canonical_store.py",
    Path(__file__).parents[1] / "storage" / "sqlite_index.py",
    Path(__file__).parents[1] / "commands" / "dream.py",
    Path(__file__).parents[1] / "commands" / "dream_assimilation.py",
    Path(__file__).parents[1] / "storage" / "session_distill_store.py",
    Path(__file__).parents[1] / "storage" / "transcript_store.py",
    Path(__file__).parents[1] / "core" / "schemas" / "session_distill.py",
    Path(__file__).parents[1] / "core" / "schemas" / "dream_run.py",
    Path(__file__).parents[1] / "commands" / "archive_distill.py",
    Path(__file__).parents[1] / "storage" / "manual_batch_store.py",
    Path(__file__).parents[1] / "core" / "schemas" / "knowledge.py",
    Path(__file__).parents[1] / "core" / "schemas" / "source_report.py",
    Path(__file__).parents[1] / "core" / "schemas" / "evidence.py",
    Path(__file__).parents[1] / "session_notes.py",
    Path(__file__).parents[2] / "code" / "plugins" / "harness-mem" / "commands" / "hm" / "hm.md",
    Path(__file__).parents[2] / "code" / "tools" / "hm-distill" / "SKILL.md",
    Path(__file__).parents[2] / "code" / "tools" / "hm-distill" / "references" / "distillation-rules.md",
)


class DistillProvider(Protocol):
    name: str

    def decide(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Any = None,
    ) -> ProviderResult: ...

    def assimilate(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Any = None,
    ) -> ProviderResult: ...

    def verify(
        self,
        manifest: dict[str, Any],
        *,
        runtime_dir: Path,
        heartbeat: Any = None,
    ) -> ProviderResult: ...


def _invoke_provider(
    provider: DistillProvider,
    method_name: str,
    manifest: dict[str, Any],
    *,
    runtime_dir: Path,
    heartbeat: Any,
) -> ProviderResult:
    method = getattr(provider, method_name)
    emit_current_stage("provider_started", details={"method": method_name})
    result = method(
        manifest,
        runtime_dir=runtime_dir,
        heartbeat=heartbeat,
    )
    emit_current_stage("provider_finished", details={"method": method_name})
    return result


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def autonomous_runtime_fingerprint() -> str:
    """Fingerprint the runtime files whose behavior the receipt claims."""

    digest = hashlib.sha256()
    for path in _RUNTIME_SOURCE_FILES:
        digest.update(str(path.name).encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(path.read_bytes())
        except OSError:
            digest.update(b"<missing>")
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def autonomous_config_fingerprint(config: MergedConfig) -> str:
    """Fingerprint project settings that control authorized background execution."""

    payload = {
        "enabled": config.distill_autonomous_enabled,
        "recent_first": config.distill_auto_recent_first,
        "budget_tokens": config.cost_budget_distill_tokens,
        "execution_cli": config.distill_autonomous_cli,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def autonomous_receipt_path(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> Path:
    key = hashlib.sha256(
        f"{project_name}\0{project_root.expanduser().resolve()}".encode("utf-8")
    ).hexdigest()[:24]
    return Path(data_dir) / "autonomous" / "receipts" / f"{key}.json"


def read_autonomous_receipt(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> dict[str, Any] | None:
    path = autonomous_receipt_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def record_post_turn_maintenance_outcome(
    data_dir: Path, *, project_name: str, project_root: str | Path,
    trigger_id: str | None, dispatch_generation: str | None, dream: Mapping[str, Any],
) -> None:
    """Close the same natural request after Dream without losing source usage."""
    root = Path(project_root).resolve()
    previous = read_autonomous_receipt(data_dir, project_name=project_name, project_root=root)
    if (previous is None or previous.get("trigger_id") != trigger_id
            or previous.get("dispatch_generation") != dispatch_generation):
        return
    status = str(dream.get("status") or "failed")
    state = ("failed" if status == "failed" else "deferred" if status == "continuing"
             else str(previous.get("state") or "idle"))
    error = previous.get("error")
    if error is None and status in {"failed", "continuing"}:
        error = {"kind": "dream_failed" if status == "failed" else "dream_continuation_pending",
                 "message": str(dream.get("error") or dream.get("reason") or status)[:512]}
    _write_receipt(data_dir, project_name=project_name, project_root=root, update={
        "source_state": previous.get("source_state") or previous.get("state"),
        "source_finished_at": previous.get("source_finished_at") or previous.get("finished_at"),
        "state": state, "finished_at": _now(), "error": error,
        "maintenance_status": "paused" if status == "continuing" else status,
        "maintenance_dream": {key: dream.get(key) for key in
                              ("run_id", "status", "summary", "continuation", "reason")},
    })


def _record_post_turn_nonsemantic_terminal_receipt(
    data_dir: Path,
    *,
    project_name: str,
    project_root: str | Path,
    trigger_id: str | None,
    client: str,
    dispatch_generation: str | None,
    state: Literal["failed", "deferred"],
    job_id: str | None,
    error: dict[str, Any],
    execution_source: str = "hook_background",
    hook_launch_verified: bool | None = None,
    config_fingerprint: str | None = None,
    hook_guard_check: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist a non-semantic terminal receipt for a waited Hook.

    The Hook may fail while staging evidence or find a job that is deliberately
    waiting for its retry window. In both cases ``--wait`` must receive the
    actual terminal state rather than timing out. These receipts deliberately
    contain no provider result, so they cannot be mistaken for semantic
    completion.
    """

    root = Path(project_root).expanduser().resolve()
    finished_at = _now()
    return _write_receipt(
        data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": state,
            "maintenance_status": "failed" if state == "failed" else "paused",
            "started_at": finished_at,
            "finished_at": finished_at,
            "trigger_id": trigger_id,
            "dispatch_generation": dispatch_generation,
            "client": client,
            "execution_source": execution_source,
            "hook_launch_verified": (
                bool(trigger_id and client)
                if hook_launch_verified is None
                else hook_launch_verified
            ),
            "hook_config_fingerprint": hook_configuration_fingerprint(
                root,
                client=client,
            ),
            "runtime_fingerprint": autonomous_runtime_fingerprint(),
            "config_fingerprint": config_fingerprint,
            "hook_reentry_count": 0,
            "hook_guard_check": hook_guard_check,
            "batch": {
                "state": state,
                "offered": 0,
                "attempted": 0,
                "completed": 0,
                "deferred": int(state == "deferred"),
                "busy": 0,
                "job_ids": [job_id] if job_id else [],
                "jobs": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "provider_seconds": 0.0,
            },
            "job_id": job_id,
            "session_id": trigger_id,
            "provider": None,
            "note": None,
            "last_semantic_success_at": None,
            "last_job_completed_at": None,
            "last_note_materialized_at": None,
            "error": error,
            "last_batch_error": error,
            "last_background_error": error,
        },
    )


def record_post_turn_preflight_failure(
    data_dir: Path,
    *,
    project_name: str,
    project_root: str | Path,
    trigger_id: str | None,
    client: str,
    dispatch_generation: str | None,
    error: dict[str, Any],
) -> dict[str, Any]:
    """Persist the actual failure when Hook staging fails before model work."""

    return _record_post_turn_nonsemantic_terminal_receipt(
        data_dir,
        project_name=project_name,
        project_root=project_root,
        trigger_id=trigger_id,
        client=client,
        dispatch_generation=dispatch_generation,
        state="failed",
        job_id=None,
        error=error,
    )


def record_post_turn_retry_backoff(
    data_dir: Path,
    *,
    project_name: str,
    project_root: str | Path,
    trigger_id: str | None,
    client: str,
    dispatch_generation: str | None,
    job_id: str,
    retry_after: str,
) -> dict[str, Any]:
    """Publish a truthful terminal receipt for an already-owned retry window."""

    return _record_post_turn_nonsemantic_terminal_receipt(
        data_dir,
        project_name=project_name,
        project_root=project_root,
        trigger_id=trigger_id,
        client=client,
        dispatch_generation=dispatch_generation,
        state="deferred",
        job_id=job_id,
        error={
            "kind": "retry_backoff",
            "message": "distill job is waiting for its scheduled retry",
            "retry_after": retry_after,
        },
    )


def _legacy_verified_completion(receipt: dict[str, Any]) -> dict[str, Any] | None:
    """Recover one self-contained success snapshot from a complete v2/v3 receipt."""

    if int(receipt.get("schema_version") or 0) not in {2, 3}:
        return None
    trigger_id = str(receipt.get("trigger_id") or "")
    batch = receipt.get("batch")
    jobs = batch.get("jobs", []) if isinstance(batch, dict) else []
    record = next(
        (
            item
            for item in jobs
            if isinstance(item, dict)
            and item.get("status") == "completed"
            and str(item.get("session_id") or "") == trigger_id
            and isinstance(item.get("provider"), dict)
            and isinstance(item.get("note"), dict)
            and item.get("last_semantic_success_at")
            and item.get("last_job_completed_at")
            and item.get("last_note_materialized_at")
        ),
        None,
    )
    if record is None:
        return None
    return {
        "schema_version": 1,
        "trigger_id": trigger_id,
        "dispatch_generation": receipt.get("dispatch_generation"),
        "client": receipt.get("client"),
        "execution_source": receipt.get("execution_source"),
        "hook_launch_verified": receipt.get("hook_launch_verified") is True,
        "hook_config_fingerprint": receipt.get("hook_config_fingerprint"),
        "runtime_fingerprint": receipt.get("runtime_fingerprint"),
        "config_fingerprint": receipt.get("config_fingerprint"),
        "hook_reentry_count": int(receipt.get("hook_reentry_count") or 0),
        "hook_guard_check": receipt.get("hook_guard_check"),
        "job_id": record.get("job_id"),
        "session_id": record.get("session_id"),
        "last_semantic_success_at": record.get("last_semantic_success_at"),
        "last_job_completed_at": record.get("last_job_completed_at"),
        "last_note_materialized_at": record.get("last_note_materialized_at"),
        "provider": record.get("provider"),
        "note": record.get("note"),
    }


def _write_receipt(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    update: dict[str, Any],
) -> dict[str, Any]:
    path = autonomous_receipt_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    previous = (
        read_autonomous_receipt(
            data_dir,
            project_name=project_name,
            project_root=project_root,
        )
        or {}
    )
    preserved_completion = previous.get("last_verified_completion")
    if not isinstance(preserved_completion, dict):
        preserved_completion = _legacy_verified_completion(previous)
    payload = {
        **previous,
        "schema_version": 4,
        "project_name": project_name,
        "project_root": str(project_root.expanduser().resolve()),
        **(
            {"last_verified_completion": preserved_completion}
            if preserved_completion is not None
            else {}
        ),
        **update,
        "heartbeat_at": _now(),
        "worker_pid": os.getpid(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return payload


@contextmanager
def _tool_bindings(backend: LocalMemoryBackend) -> Iterator[Any]:
    from harness_mem.mcp import tool_handlers

    old_backend = getattr(tool_handlers, "_backend_provider", None)
    old_observer = getattr(tool_handlers, "_observer_data_dir_provider", None)
    old_budgets = getattr(tool_handlers, "_cost_surface_budgets_provider", None)
    old_logger = getattr(tool_handlers, "logger", logger)
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logger,
    )
    try:
        yield tool_handlers
    finally:
        if old_backend is None or old_observer is None or old_budgets is None:
            tool_handlers.reset_tool_handler_dependencies()
        else:
            tool_handlers.configure_tool_handler_dependencies(
                backend_provider=old_backend,
                observer_data_dir=old_observer,
                cost_surface_budgets=old_budgets,
                logger_instance=old_logger,
            )


def run_autonomous_distill_batch(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider | None = None,
    notes_dir: Path | None = None,
    max_jobs: int | None = None,
    preferred_job_id: str | None = None,
    launch_source: str | None = None,
    dispatch_generation: str | None = None,
) -> dict[str, Any]:
    """Own only executors created by this batch, including every early exit."""
    owned: list[Any] = []
    try:
        # Optional accounting must not invoke a provider's dynamic operation
        # fallback before manual-only jobs have been excluded.
        borrowed_journal = object.__getattribute__(provider, "_native_results")
    except AttributeError:
        borrowed_journal = None
    borrowed_start = len(borrowed_journal) if isinstance(borrowed_journal, list) else 0

    def create_executor(selected_config: MergedConfig, selected_client: str) -> Any:
        executor = build_semantic_executor(selected_config, selected_client)
        owned.append(executor)
        return executor

    result: dict[str, Any] | None = None
    active_error: BaseException | None = None
    try:
        result = _run_autonomous_distill_batch(
            backend, project_name=project_name, project_root=project_root,
            config=config, trigger_id=trigger_id, client=client, provider=provider,
            notes_dir=notes_dir, max_jobs=max_jobs, preferred_job_id=preferred_job_id,
            launch_source=launch_source, dispatch_generation=dispatch_generation,
            _create_executor=create_executor,
        )
        return result
    except BaseException as exc:
        active_error = exc
        if isinstance(exc, Exception):
            observed = []
            for executor in owned:
                journal = getattr(executor, "_native_results", None)
                if isinstance(journal, list):
                    observed.extend(journal)
            if isinstance(borrowed_journal, list):
                observed.extend(borrowed_journal[borrowed_start:])
            accounting = _native_provider_receipt(observed, exc if isinstance(exc, ProviderError) else None)
            if accounting is not None:
                if isinstance(exc, ProviderError):
                    exc.native_attempts = tuple(accounting["native_attempts"])
                else:
                    error = ProviderError(
                        f"Local worker failure: {type(exc).__name__}: {exc}", kind="transient",
                        attempt_results=tuple(observed), native_attempts=tuple(accounting["native_attempts"]),
                    )
                    active_error = error
                    raise error from exc
        raise
    finally:
        for executor in owned:
            close = getattr(executor, "close", None)
            if not callable(close):
                continue
            try:
                lifecycle = close()
                if lifecycle:
                    receipt = _write_receipt(
                        backend.data_dir, project_name=project_name,
                        project_root=Path(project_root).expanduser().resolve(),
                        update={"provider_lifecycle": lifecycle},
                    )
                    if result is not None:
                        result["provider_lifecycle"] = lifecycle
                        result["receipt"] = receipt
            except Exception as exc:
                error = exc if isinstance(exc, ProviderError) else ProviderError(str(exc), kind="transient")
                update: dict[str, Any] = {"state": "partial", "error": {
                    "kind": error.kind, "message": str(error), "phase": "provider_close"}}
                if error.native_attempts:
                    update["provider_lifecycle"] = {"closed": False, "native_attempts": list(error.native_attempts)}
                receipt = _write_receipt(
                    backend.data_dir, project_name=project_name,
                    project_root=Path(project_root).expanduser().resolve(), update=update,
                )
                if result is not None:
                    result.update(success=False, state="partial", error=update["error"], receipt=receipt)
                elif active_error is None:
                    raise error
                elif isinstance(active_error, ProviderError):
                    active_error.native_attempts += error.native_attempts


def _run_autonomous_distill_batch(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str | Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider | None = None,
    notes_dir: Path | None = None,
    max_jobs: int | None = None,
    preferred_job_id: str | None = None,
    launch_source: str | None = None,
    dispatch_generation: str | None = None,
    _create_executor: Any = None,
) -> dict[str, Any]:
    """Process a bounded offered batch and materialize user-visible notes."""

    from harness_mem.maintenance_lock import maintenance_is_locked

    if launch_source != "archive_batch" and maintenance_is_locked(
        backend.data_dir,
        trigger_id=trigger_id,
    ):
        return {
            "success": False,
            "state": "busy",
            "reason": "exclusive_maintenance_run_active",
            "outcomes": [],
        }

    root = Path(project_root).expanduser().resolve()
    selected_limit = (
        None if max_jobs is None else max(0, int(max_jobs))
    )
    # Distillation is bounded structured classification, not a coding turn.
    # Keep it independent from the user's heavier interactive model so a main
    # Agent model change cannot silently reintroduce provider latency.
    started_at = _now()
    try:
        # This worker is also the explicit, active-host distill path. Its
        # default remains Codex Responses even when a project selects a
        # separate unattended Dream profile. Dream passes that provider
        # explicitly when it invokes this bounded worker.
        chosen_provider = (
            provider
            if provider is not None
            else (_create_executor or build_semantic_executor)(config, client)
            if background_on(config)
            else None
        )
        if chosen_provider is None:
            raise ProviderError(
                "Background memory is disabled (distill.autonomous.enabled=false)",
                kind="setup_required",
            )
    except ProviderError as exc:
        _record_post_turn_nonsemantic_terminal_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=root,
            trigger_id=trigger_id,
            client=client,
            dispatch_generation=dispatch_generation,
            state="failed",
            job_id=None,
            error={"kind": exc.kind, "message": str(exc)},
            execution_source="autonomous_worker",
            hook_launch_verified=bool(
                launch_source == "ide_hook" and trigger_id and client
            ),
            config_fingerprint=autonomous_config_fingerprint(config),
        )
        return {
            "success": False,
            "state": exc.kind,
            "reason": str(exc),
            "outcomes": [],
        }
    hook_guard_check: dict[str, Any] | None = None
    if launch_source == "ide_hook" and trigger_id:
        hook_guard_check = challenge_hook_reentry_guard(
            backend.data_dir,
            project_name=project_name,
            project_root=root,
            client=client,
        )
        if not hook_guard_check["all_blocked"] or hook_guard_check[
            "downstream_jobs_created"
        ]:
            error = {
                "kind": "setup_required",
                "message": "Background Hook re-entry check failed.",
            }
            _record_post_turn_nonsemantic_terminal_receipt(
                backend.data_dir,
                project_name=project_name,
                project_root=root,
                trigger_id=trigger_id,
                client=client,
                dispatch_generation=dispatch_generation,
                state="failed",
                job_id=preferred_job_id,
                error=error,
                execution_source="autonomous_worker",
                hook_launch_verified=True,
                config_fingerprint=autonomous_config_fingerprint(config),
                hook_guard_check=hook_guard_check,
            )
            return {
                "success": False,
                "state": "setup_required",
                "reason": error["message"],
                "outcomes": [],
                "hook_guard_check": hook_guard_check,
            }
    notes_override = str(os.environ.get("HARNESS_MEM_SESSION_NOTES_DIR") or "").strip()
    if notes_dir is not None:
        resolved_notes = notes_dir
    elif notes_override:
        resolved_notes = Path(notes_override).expanduser().resolve()
    elif Path(backend.data_dir).resolve() != DEFAULT_DATA_DIR.resolve():
        resolved_notes = Path(backend.data_dir) / "session_notes"
    else:
        resolved_notes = Path.home() / ".codex" / "hm-distill" / "sessions"
    runtime_dir = Path(backend.data_dir) / "autonomous" / "provider-runtime"
    _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": "running",
            "maintenance_status": (
                "running" if launch_source == "ide_hook"
                and os.environ.get("HARNESS_MEM_HOOK_BACKGROUND_WORKER") == "1" else None
            ),
            "source_state": None,
            "source_finished_at": None,
            "maintenance_dream": None,
            "started_at": started_at,
            "trigger_id": trigger_id,
            "dispatch_generation": dispatch_generation,
            "client": client,
            "execution_source": "autonomous_worker",
            "hook_launch_verified": bool(
                launch_source == "ide_hook" and trigger_id and client
            ),
            "hook_config_fingerprint": hook_configuration_fingerprint(
                root,
                client=client,
            ),
            "provider_name": chosen_provider.name,
            "runtime_fingerprint": autonomous_runtime_fingerprint(),
            "config_fingerprint": autonomous_config_fingerprint(config),
            "hook_reentry_count": count_hook_reentry_blocks(
                backend.data_dir,
                project_name=project_name,
                project_root=root,
                trigger_id=trigger_id,
            ),
            "hook_guard_check": hook_guard_check,
            "batch": {
                "offered": 0,
                "attempted": 0,
                "completed": 0,
                "deferred": 0,
                "busy": 0,
                "job_ids": [],
                "jobs": [],
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "provider_seconds": 0.0,
            },
            "finished_at": None,
            "job_id": None,
            "session_id": None,
            "provider": None,
            "note": None,
            "last_semantic_success_at": None,
            "last_job_completed_at": None,
            "last_note_materialized_at": None,
            "error": None,
        },
    )
    outcomes: list[dict[str, Any]] = []
    _repair_missing_notes(
        backend,
        project_name=project_name,
        project_root=root,
        notes_dir=resolved_notes,
    )
    backlog_limit = (
        None
        if selected_limit is None
        else max(0, selected_limit - (1 if preferred_job_id else 0))
    )
    jobs = pending_distill_jobs(
        backend,
        project_name=project_name,
        recent_first=config.distill_auto_recent_first,
        max_jobs=backlog_limit,
        record_offer=True,
        background_only=True,
    )
    preferred = (
        backend.transcript_store.get_distill_job(preferred_job_id)
        if preferred_job_id
        else None
    )
    from harness_mem.commands.manual_distill import is_manual_distill_job

    if preferred is not None and is_manual_distill_job(backend, preferred):
        preferred = None
    # A repeated Stop hook may name a job that has already completed.  That is
    # not another batch result: materialize a missing Note and publish a fresh
    # terminal receipt for the hook, but keep ``outcomes`` empty so callers can
    # distinguish replay from new semantic work.
    completed_preferred_replay: dict[str, Any] | None = None
    if preferred is not None and _preferred_job_matches_trigger(
        preferred,
        project_name=project_name,
        trigger_id=trigger_id,
    ) and preferred.status == "completed":
        completed_preferred_replay = _replay_completed_preferred_job(
            backend,
            project_name=project_name,
            project_root=root,
            trigger_id=trigger_id,
            job=preferred,
            notes_dir=resolved_notes,
        )
    elif preferred is not None and _preferred_job_is_eligible(
        preferred, project_name=project_name, trigger_id=trigger_id
    ):
        jobs = [preferred, *(job for job in jobs if job.id != preferred.id)]
    if selected_limit is not None:
        jobs = jobs[:selected_limit]
    with _tool_bindings(backend) as tools:
        for offered in jobs:
            if not isinstance(offered, SessionDistillJob):
                continue
            outcome = _run_one(
                backend,
                tools=tools,
                job_id=offered.id,
                project_name=project_name,
                project_root=root,
                config=config,
                trigger_id=trigger_id,
                client=client,
                provider=chosen_provider,
                runtime_dir=runtime_dir,
                notes_dir=resolved_notes,
            )
            outcomes.append(outcome)
            if offered.id == preferred_job_id:
                outcome["selection_reason"] = "trigger_session"

    succeeded = [item for item in outcomes if item["status"] == "completed"]
    deferred = [item for item in outcomes if item["status"] == "deferred"]
    busy = [item for item in outcomes if item["status"] == "busy"]
    batch_state = (
        "partial"
        if succeeded and deferred
        else "succeeded"
        if succeeded
        else "deferred"
        if deferred
        else "busy"
        if busy
        else "idle"
    )
    latest_success = succeeded[-1] if succeeded else None
    latest_semantic_success = next(
        (
            item
            for item in reversed(succeeded)
            if item.get("last_semantic_success_at") and item.get("provider")
        ),
        None,
    )
    latest_evidence = latest_semantic_success or latest_success
    latest_error = deferred[-1].get("error") if deferred else None
    preferred_outcome = next(
        (item for item in outcomes if item.get("job_id") == preferred_job_id),
        None,
    )
    if completed_preferred_replay is not None:
        preferred_outcome = completed_preferred_replay
    if preferred_job_id is not None:
        preferred_status = (
            str(preferred_outcome.get("status") or "deferred")
            if preferred_outcome is not None
            else "deferred"
        )
        state = {
            "completed": "succeeded",
            "deferred": "deferred",
            "busy": "busy",
        }.get(preferred_status, "deferred")
        latest_evidence = (
            preferred_outcome if preferred_status == "completed" else None
        )
        receipt_error = (
            None
            if preferred_status == "completed"
            else (preferred_outcome or {}).get("error")
            or {
                "kind": "preferred_job_not_completed",
                "message": "the trigger-bound distill job did not complete",
            }
        )
    else:
        state = batch_state
        receipt_error = None if latest_success else latest_error
    receipt = _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=root,
        update={
            "state": state,
            "finished_at": _now(),
            "trigger_id": trigger_id,
            "batch": {
                "state": batch_state,
                "offered": len(jobs),
                "attempted": len(outcomes),
                "completed": len(succeeded),
                "deferred": len(deferred),
                "busy": len(busy),
                "job_ids": [item["job_id"] for item in outcomes],
                "jobs": outcomes,
                **_batch_provider_usage(outcomes),
                "provider_seconds": round(
                    sum(
                        float(
                            (item.get("provider") or {}).get("duration_seconds") or 0.0
                        )
                        for item in outcomes
                    ),
                    3,
                ),
            },
            # These compatibility fields deliberately come from one job record.
            # Consumers needing a specific job must read batch.jobs[].
            "job_id": latest_evidence.get("job_id") if latest_evidence else None,
            "session_id": (
                latest_evidence.get("session_id") if latest_evidence else None
            ),
            "provider": latest_evidence.get("provider") if latest_evidence else None,
            "note": latest_evidence.get("note") if latest_evidence else None,
            "last_semantic_success_at": (
                latest_evidence.get("last_semantic_success_at")
                if latest_evidence
                else None
            ),
            "last_job_completed_at": (
                latest_evidence.get("last_job_completed_at")
                if latest_evidence
                else None
            ),
            "last_note_materialized_at": (
                latest_evidence.get("last_note_materialized_at")
                if latest_evidence
                else None
            ),
            "error": receipt_error,
            "last_batch_error": (
                receipt_error if preferred_job_id is not None else latest_error
            ),
            "last_background_error": (
                latest_error if preferred_job_id is not None else None
            ),
        },
    )
    return {
        "success": bool(succeeded) or not outcomes,
        # A completed preferred job is a successful trigger-bound replay even
        # though this invocation performed no new batch work.
        "state": (
            state
            if completed_preferred_replay is not None
            else batch_state
        ),
        "outcomes": outcomes,
        "receipt": receipt,
        "hook_guard_check": hook_guard_check,
    }


def _preferred_job_is_eligible(
    job: SessionDistillJob | None,
    *,
    project_name: str,
    trigger_id: str | None,
) -> bool:
    """Keep the trigger job selected after queue reconciliation advances it."""

    return bool(
        _preferred_job_matches_trigger(
            job,
            project_name=project_name,
            trigger_id=trigger_id,
        )
        and job is not None
        and not job.manual_only
        and job.status in {"queued", "parked", "processing", "reviewing", "retryable"}
    )


def _preferred_job_matches_trigger(
    job: SessionDistillJob | None,
    *,
    project_name: str,
    trigger_id: str | None,
) -> bool:
    return bool(
        job is not None
        and job.project_name == project_name
        and job.session_id == trigger_id
    )


def _replay_completed_preferred_job(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None,
    job: SessionDistillJob,
    notes_dir: Path,
) -> dict[str, Any]:
    """Reuse one completed trigger job without another provider invocation.

    A host can deliver both its automatic Stop notification and a manual
    replay for the same session.  A completed, matching job is already the
    terminal result.  Re-running it would duplicate truth; dropping it used
    to manufacture a false ``preferred_job_not_completed`` failure.
    """

    receipt = read_autonomous_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=project_root,
    ) or {}
    verified = receipt.get("last_verified_completion")
    prior = (
        verified
        if isinstance(verified, dict)
        and verified.get("job_id") == job.id
        and verified.get("session_id") == job.session_id
        and verified.get("trigger_id") == trigger_id
        else {}
    )
    note: dict[str, Any] | None
    try:
        note = _materialize_note(job, notes_dir=notes_dir)
    except ProviderError:
        saved_note = prior.get("note")
        note = saved_note if isinstance(saved_note, dict) else None
    completed_at = job.completed_at.isoformat() if job.completed_at else _now()
    return {
        "job_id": job.id,
        "session_id": job.session_id,
        "status": "completed",
        "replayed": True,
        "note": note,
        "provider": prior.get("provider") if prior else None,
        "last_semantic_success_at": prior.get("last_semantic_success_at") if prior else None,
        "last_job_completed_at": prior.get("last_job_completed_at") or completed_at,
        "last_note_materialized_at": (
            str(note.get("materialized_at"))
            if isinstance(note, dict) and note.get("materialized_at")
            else prior.get("last_note_materialized_at")
            if prior
            else None
        ),
        "error": None,
    }


def _run_one(
    backend: LocalMemoryBackend,
    *,
    tools: Any,
    job_id: str,
    project_name: str,
    project_root: Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider,
    runtime_dir: Path,
    notes_dir: Path,
) -> dict[str, Any]:
    """Run one job while recording an independent content-free timeline."""

    diagnostic = DiagnosticRun(
        backend.data_dir,
        operation="autonomous",
        project_name=project_name,
        project_root=project_root,
parent_run_id=diagnostic_parent_id(),
        references={
            "job_id": job_id,
            "trigger_id": trigger_id,
            "client": client,
        },
    )
    diagnostic.emit("accepted", "running")
    diagnostic.emit("started", "running")
    try:
        with diagnostic.activate_children():
            result = _run_one_core(
                backend,
                tools=tools,
                job_id=job_id,
                project_name=project_name,
                project_root=project_root,
                config=config,
                trigger_id=trigger_id,
                client=client,
                provider=provider,
                runtime_dir=runtime_dir,
                notes_dir=notes_dir,
            )
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary.
        diagnostic.emit(
            "failed",
            "failed",
            references={"job_id": job_id},
            error={
                "kind": "autonomous_exception",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise
    references = {
        key: result.get(key)
        for key in ("job_id", "session_id")
        if result.get(key) is not None
    }
    status = str(result.get("status") or "deferred")
    if status == "completed":
        diagnostic.emit("completed", "completed", references=references)
    elif status == "busy":
        diagnostic.emit("skipped", "skipped", references=references)
    elif status in {"deferred", "blocked"}:
        diagnostic.emit(status, status, references=references, error=result.get("error"))
    else:
        diagnostic.emit(
            "failed",
            "failed",
            references=references,
            error=result.get("error"),
        )
    return result


def _run_one_core(
    backend: LocalMemoryBackend,
    *,
    tools: Any,
    job_id: str,
    project_name: str,
    project_root: Path,
    config: MergedConfig,
    trigger_id: str | None,
    client: str,
    provider: DistillProvider,
    runtime_dir: Path,
    notes_dir: Path,
) -> dict[str, Any]:
    lease_owner = f"autonomous:{os.getpid()}:{uuid4()}"
    native_journal = getattr(provider, "_native_results", None)
    native_start = len(native_journal) if isinstance(native_journal, list) else 0
    from harness_mem.commands.manual_distill import is_manual_distill_job

    current_job = backend.transcript_store.get_distill_job(job_id)
    if current_job is not None and is_manual_distill_job(backend, current_job):
        return {"job_id": job_id, "session_id": current_job.session_id,
                "status": "busy", "reason": "manual_session_owned"}
    try:
        packet = tools.tool_prepare_session_distill(
            project_name=project_name,
            client="auto",
            scope="project",
            project_root=str(project_root),
            distill_job_id=job_id,
            evidence_mode="semantic",
            detail_level="compact",
            budget_tokens=config.cost_budget_distill_tokens,
            run_ingest=False,
            _distill_source="autonomous_worker",
        )
        if not packet.get("success"):
            raise ProviderError(
                str(packet.get("error") or "semantic prepare failed"),
                kind="transient",
            )
        # Internal preparation used to leave only signal-selected compact
        # excerpts in this packet. Reuse the same complete-source projection
        # as manual MCP reading, without putting duplicate outlines in prompts.
        from harness_mem.mcp.distill_handlers import _compact_prepare_result

        internal = {key: packet[key] for key in (
            "zero_candidate_exchange_refs", "zero_candidate_challenge_template",
        ) if key in packet}
        packet = {**_compact_prepare_result(packet), **internal}
        if not packet.get("success"):
            raise ProviderError(
                str(packet.get("error") or "complete source projection failed"),
                kind="unrecoverable",
            )
        job = backend.transcript_store.get_distill_job(job_id)
        if job is None:
            raise ProviderError(
                "prepared distill job disappeared", kind="unrecoverable"
            )
        if job.status == "completed":
            note = _materialize_note(job, notes_dir=notes_dir)
            completion = _record_success_receipt(
                backend,
                project_name=project_name,
                project_root=project_root,
                trigger_id=trigger_id,
                client=client,
                job=job,
                note=note,
                provider_receipt=None,
            )
            return {
                "job_id": job.id,
                "session_id": job.session_id,
                "status": "completed",
                "repaired": True,
                "note": note,
                "provider": None,
                **completion,
            }
        claimed = backend.transcript_store.claim_distill_review(
            job_id,
            lease_owner=lease_owner,
            execution_source="autonomous_worker",
            lease_seconds=_REVIEW_LEASE_SECONDS,
        )
        if claimed is None:
            return {"job_id": job_id, "session_id": job.session_id, "status": "busy"}
        session_id = job.session_id

        def heartbeat() -> None:
            if not backend.transcript_store.renew_distill_review_lease(
                job_id,
                lease_owner=lease_owner,
                lease_seconds=_REVIEW_LEASE_SECONDS,
            ):
                raise ProviderError("semantic review lease was lost", kind="transient")
            try:
                from harness_mem.hook_background import heartbeat_background_worker

                heartbeat_background_worker(
                    backend.data_dir,
                    project_root=project_root,
                    client=client,
                )
            except Exception:
                logger.warning(
                    "could not renew detached worker heartbeat", exc_info=True
                )
            _write_receipt(
                backend.data_dir,
                project_name=project_name,
                project_root=project_root,
                update={
                    "state": "running",
                    "job_id": job_id,
                    "session_id": session_id,
                },
            )

        provider_result, decision, validated_candidates, candidate_warnings = (
            _decide_with_candidate_retry(
                provider,
                manifest=build_provider_manifest(packet),
                packet=packet,
                job=job,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        )
        verification_result: ProviderResult | None = None
        if validated_candidates:
            verify = getattr(provider, "verify", None)
            if not callable(verify):
                raise ProviderError(
                    "autonomous provider does not implement per-point semantic verification",
                    kind="setup_required",
                )
            verification_result, validated_candidates = _verify_candidates(
                provider,
                manifest=_build_candidate_verification_manifest(
                    packet=packet,
                    validated_candidates=validated_candidates,
                    project_root=project_root,
                    backend=backend,
                    distill_job_id=job.id,
                ),
                validated_candidates=validated_candidates,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        # Persist only the trusted per-point verification result.  The
        # extraction model's requested verification_outcome is an input claim,
        # not evidence that may reach assimilation.
        governed_candidate_ids = asyncio.run(
            create_separated_candidates(
                backend,
                project_name=project_name,
                distill_job_id=job.id,
                candidate_arguments=[
                    arguments for _candidate, arguments in validated_candidates
                ],
            )
        )
        governed_count = len(governed_candidate_ids)
        if decision.candidates and governed_count == 0:
            raise ProviderError(
                "All provider candidates failed kind-specific validation: "
                + "; ".join(candidate_warnings)[:1000],
                kind="unrecoverable",
            )
        handoff = _govern_unfinished_handoff(
            tools,
            job=job,
            decision=decision,
        )
        review_payload = decision.semantic_review.model_dump(
            mode="json", exclude_none=True
        )
        assimilation_result: ProviderResult | None = None
        final_verification_result: ProviderResult | None = None
        if governed_candidate_ids:
            prepared = asyncio.run(
                prepare_separated_assimilation(
                    backend,
                    project_name=project_name,
                    project_root=str(project_root),
                    candidate_ids=governed_candidate_ids,
                )
            )
            if prepared.eligible_candidate_ids:
                assimilate = getattr(provider, "assimilate", None)
                if not callable(assimilate):
                    raise ProviderError(
                        "autonomous provider does not implement post-verification assimilation",
                        kind="setup_required",
                    )
                assimilation_result = _assimilate_prepared_in_bounded_batches(
                    provider,
                    prepared=prepared,
                    runtime_dir=runtime_dir,
                    heartbeat=heartbeat,
                )
                if not isinstance(assimilation_result.decision, AssimilationDecision):
                    raise ProviderError(
                        "assimilation provider returned an unexpected decision type",
                        kind="unrecoverable",
                    )
                assimilation = validate_separated_assimilation_decision(
                    prepared,
                    assimilation_result.decision,
                )
            else:
                assimilation = validate_separated_assimilation_decision(
                    prepared,
                    AssimilationDecision(points=[]),
                )
            final_verification_result, assimilation = _verify_final_knowledge_scope(
                provider,
                backend=backend,
                prepared=prepared,
                plan=assimilation,
                original_manifest=_build_candidate_verification_manifest(
                    packet=packet, validated_candidates=validated_candidates,
                    project_root=project_root, backend=backend, distill_job_id=job.id,
                ),
                governed_candidate_ids=governed_candidate_ids,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
            review_payload["assimilation"] = assimilation
        finalized = tools.tool_finalize_session_distill(
            project_name=project_name,
            job_id=job_id,
            semantic_review=review_payload,
            _review_lease_owner=lease_owner,
        )
        if not finalized.get("success"):
            raise ProviderError(
                str(
                    finalized.get("error")
                    or finalized.get("reason_codes")
                    or "finalize failed"
                ),
                kind="unrecoverable",
            )
        stored = backend.transcript_store.get_distill_job(job_id)
        if stored is None or stored.status != "completed":
            raise ProviderError(
                "finalize did not persist a completed job", kind="unrecoverable"
            )
        # Combine the pre-cleanup identity with the completed, sanitized
        # result only in memory. This preserves a useful user-facing Note in
        # the caller's requested directory without restoring identifiers to
        # the durable raw-evidence ledger.
        note_job = stored.model_copy(
            update={
                "session_id": job.session_id,
                "project_root": job.project_root,
                "semantic_review": decision.semantic_review.model_dump(
                    mode="json", exclude_none=True
                ),
            }
        )
        note = _materialize_note(note_job, notes_dir=notes_dir)
        provider_receipt = {
            **provider_result.receipt(),
            "job_id": stored.id,
            "source_revision": job.source_revision,
            "session_id_sha256": _identity_digest(job.session_id),
            "trigger_id_sha256": _identity_digest(trigger_id),
            "project_root_sha256": _identity_digest(str(project_root)),
        }
        if verification_result is not None:
            provider_receipt["extraction"] = provider_result.receipt()
            provider_receipt["verification"] = verification_result.receipt()
        if assimilation_result is not None:
            provider_receipt["assimilation"] = assimilation_result.receipt()
            provider_receipt["combined"] = {
                "input_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.input_tokens,
                        verification_result.input_tokens if verification_result else None,
                    ),
                    assimilation_result.input_tokens,
                ),
                "output_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.output_tokens,
                        verification_result.output_tokens if verification_result else None,
                    ),
                    assimilation_result.output_tokens,
                ),
                "total_tokens": _sum_provider_metric(
                    _sum_provider_metric(
                        provider_result.total_tokens,
                        verification_result.total_tokens if verification_result else None,
                    ),
                    assimilation_result.total_tokens,
                ),
                "duration_seconds": round(
                    provider_result.duration_seconds
                    + (verification_result.duration_seconds if verification_result else 0.0)
                    + assimilation_result.duration_seconds,
                    3,
                ),
            }
        if final_verification_result is not None:
            provider_receipt["final_verification"] = final_verification_result.receipt()
            combined = provider_receipt.get("combined")
            if isinstance(combined, dict):
                for metric in ("input_tokens", "output_tokens", "total_tokens"):
                    combined[metric] = _sum_provider_metric(
                        combined[metric], getattr(final_verification_result, metric),
                    )
                combined["duration_seconds"] = round(
                    combined["duration_seconds"] + final_verification_result.duration_seconds, 3,
                )
        native_receipt = _native_provider_receipt(
            native_journal[native_start:] if isinstance(native_journal, list) else [],
        )
        if native_receipt is not None:
            provider_receipt.update(native_receipt)
        completion = _record_success_receipt(
            backend,
            project_name=project_name,
            project_root=project_root,
            trigger_id=trigger_id,
            client=client,
            job=note_job,
            note=note,
            provider_receipt=provider_receipt,
        )
        return {
            "job_id": note_job.id,
            "session_id": note_job.session_id,
            "status": "completed",
            "note_path": note["path"],
            "note": note,
            "provider": provider_receipt,
            "handoff": handoff,
            "candidate_warnings": candidate_warnings,
            **completion,
        }
    except ProviderError as exc:
        failure_provider = _native_provider_receipt(
            native_journal[native_start:] if isinstance(native_journal, list) else [], exc,
        )
        job = backend.transcript_store.get_distill_job(job_id)
        if job is not None and job.review_lease_owner == lease_owner:
            job = backend.transcript_store.defer_distill_job(
                job_id,
                error=f"{exc.kind}: {exc}"[:512],
            )
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={
                "state": "deferred",
                "job_id": job_id,
                "session_id": job.session_id if job else None,
                "error": {
                    "kind": exc.kind,
                    "message": str(exc)[:1000],
                    "exit_code": exc.exit_code,
                },
                **({"provider": failure_provider} if failure_provider is not None else {}),
            },
        )
        return {
            "job_id": job_id,
            "session_id": job.session_id if job else None,
            "status": "deferred",
            "error": {"kind": exc.kind, "message": str(exc)[:1000]},
            **({"provider": failure_provider} if failure_provider is not None else {}),
        }
    except Exception as exc:  # noqa: BLE001 - one broken job must not block the batch.
        failure_provider = _native_provider_receipt(
            native_journal[native_start:] if isinstance(native_journal, list) else [],
        )
        job = backend.transcript_store.get_distill_job(job_id)
        if job is not None and job.review_lease_owner == lease_owner:
            backend.transcript_store.defer_distill_job(
                job_id,
                error=f"unrecoverable: {type(exc).__name__}: {exc}"[:512],
            )
        logger.exception("autonomous distill job failed: %s", job_id)
        outcome = {
            "job_id": job_id,
            "session_id": job.session_id if job else None,
            "status": "deferred",
            "error": {
                "kind": "unrecoverable",
                "message": f"{type(exc).__name__}: {exc}"[:1000],
            },
            **({"provider": failure_provider} if failure_provider is not None else {}),
        }
        try:
            _write_receipt(
                backend.data_dir, project_name=project_name, project_root=project_root,
                update={"state": "deferred", **outcome},
            )
        except Exception as receipt_error:
            # The batch can retry its final receipt; paid history must remain
            # on the returned outcome even if this local write fails too.
            outcome["receipt_error"] = {"kind": "receipt_write_failed",
                                        "exception_type": type(receipt_error).__name__}
        return outcome


def _govern_unfinished_handoff(
    tools: Any,
    *,
    job: SessionDistillJob,
    decision: Any,
) -> dict[str, Any] | None:
    """Persist partial-session work under the same distill job boundary."""

    review = decision.semantic_review
    unfinished = [
        str(item).strip() for item in review.unfinished_work if str(item).strip()
    ]
    if review.promotion_decision != "partial" or not unfinished:
        return None
    result = tools.tool_govern_memory(
        action="handoff",
        arguments={
            "project_name": job.project_name,
            "task_id": f"distill-follow-up-{job.id}",
            "summary": str(review.final_outcome).strip()[:1000],
            "status": "in_progress",
            "next_steps": unfinished,
            "blockers": [],
            "distill_job_id": job.id,
        },
    )
    if not result.get("success"):
        raise ProviderError(
            str(result.get("error") or "unfinished handoff governance failed"),
            kind="unrecoverable",
        )
    return result


def build_provider_manifest(packet: dict[str, Any]) -> dict[str, Any]:
    """Project only decision-relevant evidence into the host CLI prompt."""

    semantic = packet.get("semantic_evidence")
    semantic_dict = semantic if isinstance(semantic, dict) else {}
    semantic_chunks = [
        str(item.get("content") or "")
        for item in semantic_dict.get("chunks") or []
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    decision_exchanges = [
        {
            "exchange_index": item.get("exchange_index"),
            "content_sha256": item.get("content_sha256"),
            "content": item.get("content"),
            **(
                {"preceding_assistant_messages": item["preceding_assistant_messages"]}
                if "preceding_assistant_messages" in item
                else {}
            ),
        }
        for item in packet.get("semantic_decision_exchanges") or []
        if isinstance(item, dict)
    ]
    exchange_count = int(
        semantic_dict.get("exchange_count")
        or semantic_dict.get("output_exchange_count")
        or 0
    )
    covered_indexes = {
        exchange_index
        for item in decision_exchanges
        if isinstance((exchange_index := item.get("exchange_index")), int)
    }
    if exchange_count > 0 and covered_indexes == set(range(1, exchange_count + 1)):
        # Complete decision windows already contain these exchanges verbatim.
        # Do not send the same user and assistant text twice.
        semantic_chunks = []
    return {
        "contract_version": "autonomous-distill-manifest-v1",
        "coverage": "complete_indexed_semantic_projection",
        "semantic_projection": {
            "exchange_count": exchange_count,
            "chunks": semantic_chunks,
        },
        "semantic_decision_exchanges": decision_exchanges,
        "zero_candidate_exchange_refs": packet.get("zero_candidate_exchange_refs", []),
        "zero_candidate_challenge_template": packet.get(
            "zero_candidate_challenge_template"
        ),
    }


def _normalize_zero_candidate_signal_labels(
    decision: Any,
    *,
    packet: dict[str, Any],
) -> Any:
    """Repair exact signal labels without inventing semantic justification.

    The provider can explain a downgrade in natural language yet omit the
    runtime's machine-readable signal key.  Finalization intentionally rejects
    that shape.  When the provider already supplied a substantive session-only
    rationale, append only the missing exact labels so the trusted gate can
    correlate the explanation with the detected signals.
    """

    if decision.candidates:
        return decision
    challenge = decision.semantic_review.zero_candidate_challenge
    template = packet.get("zero_candidate_challenge_template")
    if challenge is None or not isinstance(template, dict):
        return decision
    if challenge.future_utility != "session_only":
        return decision
    template_checks = template.get("checks")
    if not isinstance(template_checks, dict):
        return decision
    challenge_checks = challenge.checks.model_dump()
    downgraded = sorted(
        signal
        for signal, expected in template_checks.items()
        if expected == "candidate_required"
        and challenge_checks.get(signal) == "not_durable"
    )
    rationale = challenge.rationale
    missing = [
        signal for signal in downgraded if signal.lower() not in rationale.lower()
    ]
    rationale_without_labels = rationale.lower()
    for signal in downgraded:
        rationale_without_labels = rationale_without_labels.replace(signal.lower(), "")
    if not missing or sum(char.isalnum() for char in rationale_without_labels) < 12:
        return decision
    updated_challenge = challenge.model_copy(
        update={
            "rationale": (
                rationale.rstrip()
                + " Reviewed downgraded signals: "
                + ", ".join(missing)
                + "."
            )[:4000]
        }
    )
    updated_review = decision.semantic_review.model_copy(
        update={"zero_candidate_challenge": updated_challenge}
    )
    return decision.model_copy(update={"semantic_review": updated_review})


def _zero_candidate_validation_errors(
    decision: Any,
    *,
    packet: dict[str, Any],
    job: SessionDistillJob,
) -> list[str]:
    """Validate provider no-candidate state before governance/finalization."""

    if decision.candidates:
        return []
    challenge = decision.semantic_review.zero_candidate_challenge
    if challenge is None:
        return ["zero_candidate_challenge is required"]
    errors: list[str] = []
    try:
        RuntimeZeroCandidateChallenge.model_validate(challenge.model_dump(mode="json"))
    except ValueError as exc:
        errors.append(f"zero_candidate_challenge schema inconsistent: {exc}")
    if challenge.source_revision != job.source_revision:
        errors.append("zero-candidate challenge source revision does not match job")
    expected_exchange_refs = {
        int(item["exchange_index"]): str(item["content_sha256"])
        for item in packet.get("zero_candidate_exchange_refs", [])
        if isinstance(item, dict)
        and isinstance(item.get("exchange_index"), int)
        and isinstance(item.get("content_sha256"), str)
    }
    if expected_exchange_refs:
        supplied_exchange_refs = {
            item.exchange_index: item.content_sha256
            for item in challenge.inspected_exchange_refs
        }
        if supplied_exchange_refs != expected_exchange_refs:
            errors.append(
                "zero-candidate exchange proof incomplete or does not match the "
                "required semantic exchanges"
            )
    template = packet.get("zero_candidate_challenge_template")
    template_checks = template.get("checks") if isinstance(template, dict) else None
    if isinstance(template_checks, dict):
        challenge_checks = challenge.checks.model_dump()
        still_required = sorted(
            signal
            for signal, finding in challenge_checks.items()
            if finding == "candidate_required"
        )
        if still_required:
            errors.append(
                "detected durable signals still require a candidate: "
                + ", ".join(still_required)
            )
        incorrectly_absent = sorted(
            signal
            for signal, expected in template_checks.items()
            if expected == "candidate_required"
            and challenge_checks.get(signal) == "absent"
        )
        if incorrectly_absent:
            errors.append(
                "detected durable signals cannot be marked absent: "
                + ", ".join(incorrectly_absent)
            )
        downgraded = sorted(
            signal
            for signal, expected in template_checks.items()
            if expected == "candidate_required"
            and challenge_checks.get(signal) == "not_durable"
        )
        if downgraded:
            rationale = challenge.rationale.lower()
            rationale_without_signal_keys = rationale
            for signal in downgraded:
                rationale_without_signal_keys = rationale_without_signal_keys.replace(
                    signal.lower(), ""
                )
            has_session_only_explanation = (
                challenge.future_utility == "session_only"
                and sum(character.isalnum() for character in rationale_without_signal_keys)
                >= 12
            )
            missing_signal_names = [
                signal for signal in downgraded if signal.lower() not in rationale
            ]
            if missing_signal_names or not has_session_only_explanation:
                errors.append(
                    "downgraded durable signals require a substantive session-only "
                    "rationale naming each signal: "
                    + ", ".join(downgraded)
                )
    return errors


def _decide_with_candidate_retry(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    packet: dict[str, Any],
    job: SessionDistillJob,
    runtime_dir: Path,
    heartbeat: Any,
) -> tuple[ProviderResult, Any, list[tuple[Any, dict[str, Any]]], list[str]]:
    """Retry once when every returned candidate violates its kind contract."""

    results: list[ProviderResult] = []
    current_manifest = manifest
    for attempt in range(2):
        result = _invoke_provider(
            provider,
            "decide",
            current_manifest,
            runtime_dir=runtime_dir,
            heartbeat=heartbeat,
        )
        results.append(result)
        decision = _normalize_zero_candidate_signal_labels(
            result.decision,
            packet=packet,
        )
        decision = normalize_provider_review_state(decision)
        validated: list[tuple[Any, dict[str, Any]]] = []
        warnings = _zero_candidate_validation_errors(
            decision,
            packet=packet,
            job=job,
        )
        for index, candidate in enumerate(decision.candidates):
            control_reason = provider_candidate_control_reason(
                candidate,
                decision=decision,
            )
            if control_reason is not None:
                warnings.append(f"candidate[{index}]: {control_reason}")
                continue
            try:
                arguments = _candidate_arguments(candidate, job=job, packet=packet)
            except ValueError as exc:
                warnings.append(f"candidate[{index}]: {exc}")
                continue
            validated.append((candidate, arguments))
        decision_valid = bool(decision.candidates or not warnings)
        if decision_valid and (not decision.candidates or validated):
            return _combine_provider_results(results), decision, validated, warnings
        if attempt == 1:
            raise ProviderError(
                "provider correction failed candidate/zero-candidate validation: "
                + "; ".join(warnings)[:2000],
                kind="unrecoverable",
            )
        current_manifest = {
            **manifest,
            "candidate_validation_feedback": {
                "errors": warnings,
                "instruction": (
                    "Return corrected review and points. Every point must satisfy its kind "
                    "fields and cite an available exchange index. If no points are returned, "
                    "each detected candidate_required signal must either have a point or be "
                    "listed in review.not_durable_signals. Explain every not-durable signal "
                    "substantively in review.no_candidate_reason. Do not copy runtime hashes, "
                    "status fields, confidence, or the zero-candidate template."
                ),
            },
        }
    raise AssertionError("candidate retry loop did not return")


def _assimilate_with_schema_retry(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    runtime_dir: Path,
    heartbeat: Any,
    validate_decision: Callable[[AssimilationDecision], Any] | None = None,
) -> ProviderResult:
    """Give a malformed post-verification response two bounded correction passes.

    Candidate extraction already has a field-contract retry.  Atomic
    ``knowledge_items`` introduced another strict structured shape, so the
    second semantic call needs the same bounded recovery: an omitted item title,
    unavailable target, or invalid target cardinality must not strand a complete
    session in ``reviewing``. Each retry passes the validator's exact feedback and
    still fails closed after two corrections.
    """

    current_manifest = manifest
    attempt_results: list[ProviderResult] = []
    unknown_attempt_count = 0

    def completed_result(*, decision: Any = None) -> ProviderResult:
        combined = _combine_provider_results(attempt_results, decision=decision)
        if unknown_attempt_count:
            combined = replace(
                combined,
                attempt_count=combined.attempt_count + unknown_attempt_count,
                input_tokens=None, output_tokens=None, total_tokens=None,
            )
        return combined

    for attempt in range(3):
        try:
            result = _invoke_provider(
                provider,
                "assimilate",
                current_manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
            )
        except ProviderError as exc:
            attempt_results.extend(exc.attempt_results)
            unknown_attempt_count += exc.unknown_attempt_count
            if not exc.attempt_results and not exc.unknown_attempt_count:
                unknown_attempt_count += 1
            invalid_shape = exc.failure_reason == "decision_schema"
            if attempt < 2 and exc.kind == "unrecoverable" and invalid_shape:
                current_manifest = {
                    **manifest,
                    "assimilation_validation_feedback": {
                        "errors": [str(exc)[:2000]],
                        "instruction": (
                            "Return a corrected assimilation decision. A knowledge_items "
                            "row must contain title, statement, topic_path, and claim_kind; "
                            "use canonical_title/canonical_statement instead when writing "
                            "one item. When knowledge_items is non-empty, leave point-level "
                            "canonical_title and canonical_statement null and topic_path empty. "
                            "Never keep an umbrella item together with narrower items that split "
                            "the same requirement. If a requirement offers alternative enforcement "
                            "mechanisms, preserve the either/or in one atomic sentence with one "
                            "modal instead of expanding it into separate must clauses. Return every "
                            "supplied candidate_id at least once. A broad candidate can "
                            "return multiple points with distinct dispositions and targets. "
                            "Preserve every technical identifier "
                            "named in the candidate; when feedback lists dropped terms, copy those "
                            "identifiers exactly into the corrected knowledge statement. Set "
                            "matched_truth_handles=[] for add, no_write, handoff, defer, and "
                            "reject; use exactly one available handle for confirm, and one or "
                            "more available handles for refine or replace. If an error says independent obligations or separate "
                            "steps, split the offending statement into as many distinct "
                            "atomic knowledge_items as the source requires. Do not repeat or "
                            "lightly rephrase the invalid combined statement. Keep a paired growth and lossless-"
                            "reconstruction qualification test contract in one testing item "
                            "rather than one item per test name."
                        ),
                    },
                }
                continue
            raise ProviderError(
                str(exc), kind=exc.kind, exit_code=exc.exit_code,
                attempt_results=tuple(attempt_results),
                unknown_attempt_count=unknown_attempt_count,
                native_attempts=exc.native_attempts,
                failure_reason=exc.failure_reason,
            ) from exc
        attempt_results.append(result)
        if isinstance(result.decision, AssimilationDecision):
            if validate_decision is not None:
                try:
                    validate_decision(result.decision)
                    _validate_verified_source_clause_grouping(
                        result.decision, manifest=manifest
                    )
                except ValueError as exc:
                    if attempt < 2:
                        current_manifest = {
                            **manifest,
                            "assimilation_validation_feedback": {
                                "errors": [str(exc)[:2000]],
                                "instruction": (
                                    "Return every supplied candidate_id at least once in a "
                                    "corrected assimilation decision; a broad candidate may "
                                    "emit multiple points with distinct dispositions and targets. "
                                "Set matched_truth_handles=[] "
                                "for add, no_write, handoff, defer, and reject. A "
                                    "confirm needs exactly one supplied truth handle; refine and "
                                    "replace may use one or more supplied handles; do not reference unavailable handles. For confirm, "
                                    "no_write, handoff, defer, conflict, and reject, return no "
                                    "knowledge_items and leave canonical_title, "
                                    "canonical_statement, and topic_path empty. Correct every named "
                                    "error before returning. Never keep an umbrella item together "
                                    "with narrower items that split the same requirement. Preserve "
                                    "alternative enforcement mechanisms as one either/or sentence "
                                    "with one modal. Preserve every candidate technical identifier "
                                    "exactly, including any terms named as dropped in the error. "
                                    "Keep a paired growth and lossless-reconstruction qualification "
                                    "test contract in one testing item rather than one item per test."
                                ),
                            },
                        }
                        continue
                    repaired = _repair_invalid_writing_with_source_clauses(
                        result.decision,
                        manifest=manifest,
                        error=exc,
                    )
                    if repaired is not None:
                        try:
                            validate_decision(repaired)
                            _validate_verified_source_clause_grouping(
                                repaired, manifest=manifest
                            )
                        except ValueError:
                            pass
                        else:
                            return replace(
                                completed_result(decision=repaired),
                                decision=repaired,
                                provider=f"{result.provider}->runtime_source_clause",
                            )
                    raise ProviderError(
                        f"invalid assimilation decision: {exc}",
                        kind="unrecoverable",
                        attempt_results=tuple(attempt_results),
                        unknown_attempt_count=unknown_attempt_count,
                        failure_reason="decision_validation",
                    ) from exc
            return completed_result()
        raise ProviderError(
            "assimilation provider returned an unexpected decision type",
            kind="unrecoverable",
            attempt_results=tuple(attempt_results),
            unknown_attempt_count=unknown_attempt_count,
            failure_reason="decision_validation",
        )
    raise AssertionError("assimilation retry loop did not return")


def _validate_verified_source_clause_grouping(
    decision: AssimilationDecision, *, manifest: dict[str, Any]
) -> None:
    """Catch literal recombination of separate verified obligations.

    Structural prose validation deliberately does not judge atomicity. This
    bounded check only recognizes copied source clauses with their own modals;
    it does not infer facts from punctuation or split provider paraphrases.
    Related alternatives and overlapping clauses stay with the Agent.
    """

    sources = {
        str(item.get("candidate_id") or ""): str(item.get("statement") or "")
        for item in manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    }
    for point in decision.points:
        if point.disposition not in {"add", "refine", "replace"}:
            continue
        clauses = _split_verified_source_clauses(sources.get(point.candidate_id, ""))
        if len(clauses) < 2 or _source_clauses_have_overlapping_identifiers(clauses):
            continue
        subjects = [re.match(r"^(.+?)(?:必须|应当|应该|应|须)", clause) for clause in clauses]
        if all(subjects) and len({match.group(1).strip() for match in subjects if match}) == 1:
            # Repeated Chinese subjects may describe one shared contract, just
            # like overlapping English identifiers. Independence is ambiguous.
            continue
        if any(
            not re.search(r"必须|应当|应该|应|须|\b(?:must|should|required to)\b", clause, re.I)
            or re.search(
                r"^(?:如果|否则|若|当)|或者|否则|\b(?:if|when|unless|otherwise|else|either|or)\b",
                clause,
                re.I,
            )
            for clause in clauses
        ):
            continue
        statements = (
            [item.statement for item in point.knowledge_items]
            if point.knowledge_items
            else [str(point.canonical_statement or "")]
        )
        for statement in statements:
            copied = set(_split_verified_source_clauses(statement)) & set(clauses)
            if len(copied) > 1:
                raise ValueError(
                    "canonical knowledge combines independent obligations copied "
                    "from the verified candidate; split them into knowledge_items"
                )


def _repair_invalid_writing_with_source_clauses(
    decision: AssimilationDecision,
    *,
    manifest: dict[str, Any],
    error: ValueError,
) -> AssimilationDecision | None:
    """Recover verified atomic source clauses after repeated lossy wording.

    This does not synthesize missing facts. It copies only clauses from the
    already verified candidate, and only when every clause is independently
    atomic. Conditional alternatives and broad/ambiguous candidates still fail
    closed and are deferred by the caller.
    """

    message = str(error)
    wording_error_markers = (
        "canonical knowledge",
        "knowledge item",
        "knowledge_items",
    )
    if not any(marker in message for marker in wording_error_markers):
        return None
    if len(decision.points) != 1:
        return None
    projections = [
        item
        for item in manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    ]
    if len(projections) != 1:
        return None
    projection = projections[0]
    point = decision.points[0]
    if point.candidate_id != str(projection.get("candidate_id") or ""):
        return None
    # The candidate is not the complete successor contract of matched truth.
    # Copying it must never discard existing settings or scope during repair.
    # Mutating actions stay on the ordinary model retry/defer path instead.
    if point.disposition != "add" or point.matched_truth_handles:
        return None
    source = str(projection.get("statement") or "").strip()
    if not source or re.search(r"(?:；|;)\s*(?:如果|否则|if\b|otherwise\b)", source, re.I):
        return None
    source_clauses = _split_verified_source_clauses(source)
    if not source_clauses:
        return None
    if _source_clauses_have_overlapping_identifiers(source_clauses):
        return None
    atomic_clauses: list[str] = []
    for clause in source_clauses:
        try:
            atomic_clauses.append(validate_atomic_knowledge_statement(clause))
        except ValueError:
            return None
    payload = decision.model_dump(mode="json")
    raw_point = payload["points"][0]
    if raw_point.get("knowledge_items"):
        existing_items = raw_point["knowledge_items"]
        template = existing_items[0]
        raw_point["knowledge_items"] = [
            {
                "title": (
                    str(template.get("title") or "")
                    if len(atomic_clauses) == 1
                    else _source_clause_title(clause)
                ),
                "statement": clause,
                "topic_path": list(template.get("topic_path") or []),
                "claim_kind": template.get("claim_kind"),
            }
            for clause in atomic_clauses
        ]
        if any(not item["title"] for item in raw_point["knowledge_items"]):
            return None
    elif raw_point.get("canonical_statement"):
        return None
    else:
        return None
    return AssimilationDecision.model_validate(payload)


def _source_clauses_have_overlapping_identifiers(clauses: list[str]) -> bool:
    """Keep deterministic fallback from duplicating the same technical checklist."""

    ignored = {
        "adapter",
        "candidate",
        "chunk",
        "current",
        "knowledge",
        "must",
        "revision",
        "session",
        "should",
        "support",
        "test",
    }
    identifiers = [
        {
            token.casefold()
            for token in re.findall(r"[A-Za-z][A-Za-z0-9_-]{2,}", clause)
            if token.casefold() not in ignored
        }
        for clause in clauses
    ]
    return any(
        len(left & right) >= 2
        for index, left in enumerate(identifiers)
        for right in identifiers[index + 1 :]
    )


def _split_verified_source_clauses(source: str) -> list[str]:
    """Split only explicit source conjunctions while retaining their shared subject."""

    if re.search(r"之一|任选|任一|(?:二|两|三|多)选一|\bone of\b|\bat least one\b", source, re.I):
        # Alternatives govern the entire checklist. Expanding its conjunctions
        # could turn an optional branch into an unsupported mandatory fact.
        return [source.strip(" \t\r\n,，。")] if source.strip() else []
    clauses = [
        clause.strip(" \t\r\n,，。")
        for clause in source.replace("；", ";").split(";")
        if clause.strip(" \t\r\n,，。")
    ]
    expanded: list[str] = []
    for clause in clauses:
        modal = re.match(r"^(?P<prefix>.+?(?:必须|应当|应该|应|须))(?P<body>.+)$", clause)
        if modal is None:
            expanded.append(clause)
            continue
        prefix = modal.group("prefix")
        body = modal.group("body")
        split = re.split(
            r"，并(?=(?:通过|具备|声明|完成|提供|执行|保存|记录))",
            body,
            maxsplit=1,
        )
        if len(split) == 2:
            expanded.extend([prefix + split[0], prefix + split[1]])
        else:
            expanded.append(clause)

    atomic_candidates: list[str] = []
    for clause in expanded:
        if not (
            re.search(r"(?:路径|样本|匹配规则)", clause)
            and re.search(r"hook\s*/\s*transcript|hook.+transcript", clause, re.I)
        ):
            atomic_candidates.append(clause)
            continue
        modal = re.match(
            r"^(?P<prefix>.+?(?:必须|应当|应该|应|须)(?:声明|具备)?)(?P<body>.+)$",
            clause,
        )
        if modal is None:
            atomic_candidates.append(clause)
            continue
        body = modal.group("body")
        capability = re.search(
            r"(?:、|，|和|及)\s*(?P<capability>hook\s*/\s*transcript\s*能力.*)$",
            body,
            re.I,
        )
        if capability is None:
            atomic_candidates.append(clause)
            continue
        left = body[: capability.start()].strip(" 、,，")
        if not left:
            atomic_candidates.append(clause)
            continue
        atomic_candidates.extend(
            [modal.group("prefix") + left, modal.group("prefix") + capability.group("capability")]
        )
    return [clause.strip(" \t\r\n,，。") for clause in atomic_candidates if clause.strip()]


def _source_clause_title(source_clause: str) -> str:
    """Derive a bounded title from one copied source clause, without new facts."""

    normalized = " ".join(source_clause.split()).strip(" ,，。")
    match = re.search(r"(?:必须|应当|应该|应|须)", normalized)
    if match is None:
        head = re.split(r"[、,，。]", normalized, maxsplit=1)[0]
        return head[:80] or "Verified source constraint"
    subject = normalized[: match.start()].strip()
    subject = re.sub(r"^(?:每个|每一|所有)\s*", "", subject).strip()
    predicate = normalized[match.end() :].strip()
    predicate = re.split(r"[、,，。]", predicate, maxsplit=1)[0].strip()
    title = " ".join(part for part in (subject, predicate) if part).strip()
    return title[:80] or "Verified source constraint"


def _provider_error_after_attempts(
    error: ProviderError,
    prior_results: Sequence[ProviderResult],
    *,
    prior_unknown_count: int = 0,
) -> ProviderError:
    """Carry non-overlapping completed prefixes through a failed recovery."""

    return ProviderError(
        str(error), kind=error.kind, exit_code=error.exit_code,
        attempt_results=(*prior_results, *error.attempt_results),
        unknown_attempt_count=prior_unknown_count + error.unknown_attempt_count,
        native_attempts=error.native_attempts,
        failure_reason=error.failure_reason,
    )


def _assimilate_prepared_in_bounded_batches(
    provider: DistillProvider,
    *,
    prepared: SeparatedPreparedAssimilation,
    runtime_dir: Path,
    heartbeat: Any,
    _batch_size: int | None = None,
) -> ProviderResult:
    """Batch verified points without weakening per-point checks or isolation.

    Complete decisions share current truth once per batch. Invalid batches
    fall back to individual points; no candidate or knowledge item is dropped.
    """

    eligible = list(prepared.eligible_candidate_ids)
    if not eligible:
        raise ProviderError(
            "bounded assimilation requires at least one eligible candidate",
            kind="unrecoverable",
        )
    projected = {
        str(item.get("candidate_id") or ""): dict(item)
        for item in prepared.manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    }
    if any(candidate_id not in projected for candidate_id in eligible):
        raise ProviderError(
            "assimilation manifest is missing an eligible candidate projection",
            kind="unrecoverable",
        )

    results: list[ProviderResult] = []
    combined_points = []
    prior_batch_knowledge: list[dict[str, Any]] = [
        dict(item) for item in prepared.manifest.get("prior_batch_knowledge") or []
        if isinstance(item, dict)
    ]
    retired_truth_handles: set[str] = set()
    batch_size = _batch_size or _MAX_ASSIMILATION_CANDIDATES_PER_CALL
    for offset in range(0, len(eligible), batch_size):
        batch_ids = tuple(
            eligible[offset : offset + batch_size]
        )
        available_truth_by_handle = {
            handle: truth_id
            for handle, truth_id in prepared.truth_by_handle.items()
            if handle not in retired_truth_handles
        }
        batch_prepared = SeparatedPreparedAssimilation(
            project_name=prepared.project_name,
            project_root=prepared.project_root,
            candidate_ids=batch_ids,
            eligible_candidate_ids=batch_ids,
            automatic_points=(),
            answer_status_by_candidate={
                candidate_id: prepared.answer_status_by_candidate[candidate_id]
                for candidate_id in batch_ids
            },
            truth_by_handle=available_truth_by_handle,
            manifest={
                **prepared.manifest,
                "verified_candidates": [projected[candidate_id] for candidate_id in batch_ids],
                "prior_batch_knowledge": list(prior_batch_knowledge),
                "current_truth": [
                    item
                    for item in prepared.manifest.get("current_truth") or []
                    if isinstance(item, dict)
                    and str(item.get("handle") or "") in available_truth_by_handle
                ],
            },
        )

        def validate_batch(candidate: AssimilationDecision) -> dict[str, Any]:
            return validate_separated_assimilation_decision(batch_prepared, candidate)

        try:
            result = _assimilate_with_schema_retry(
                provider,
                manifest=batch_prepared.manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
                validate_decision=validate_batch,
            )
        except ProviderError as exc:
            if exc.kind != "unrecoverable" or exc.failure_reason not in {
                "decision_schema", "decision_validation",
            }:
                raise _provider_error_after_attempts(exc, results) from exc
            if len(batch_ids) > 1:
                try:
                    result = _assimilate_prepared_in_bounded_batches(
                        provider,
                        prepared=batch_prepared,
                        runtime_dir=runtime_dir,
                        heartbeat=heartbeat,
                        _batch_size=1,
                    )
                except ProviderError as recovery_error:
                    raise _provider_error_after_attempts(
                        recovery_error, [*results, *exc.attempt_results],
                        prior_unknown_count=exc.unknown_attempt_count,
                    ) from recovery_error
                if exc.attempt_results:
                    result = _combine_provider_results(
                        [*exc.attempt_results, result], decision=result.decision,
                    )
                if exc.unknown_attempt_count:
                    result = replace(
                        result,
                        attempt_count=result.attempt_count + exc.unknown_attempt_count,
                        input_tokens=None, output_tokens=None, total_tokens=None,
                    )
            else:
                result = _deferred_assimilation_result(
                    provider,
                    candidate_ids=batch_ids,
                    error=exc,
                    manifest=batch_prepared.manifest,
                )
        if not isinstance(result.decision, AssimilationDecision):
            raise ProviderError(
                "assimilation provider returned an unexpected decision type",
                kind="unrecoverable",
            )
        normalized_decision = normalize_identical_replacements(
            batch_prepared,
            result.decision,
        )
        if normalized_decision is not result.decision:
            result = replace(result, decision=normalized_decision)
        normalized_batch = validate_separated_assimilation_decision(
            batch_prepared,
            result.decision,
        )
        results.append(result)
        combined_points.extend(result.decision.points)
        retired_truth_handles.update(
            str(handle)
            for point in result.decision.points
            if point.disposition in {"refine", "replace"}
            for handle in point.matched_truth_handles
        )
        for point in normalized_batch["points"]:
            knowledge_items = list(point.get("knowledge_items") or [])
            if knowledge_items:
                prior_batch_knowledge.extend(
                    {
                        "candidate_id": str(point["candidate_id"]),
                        "title": str(item["title"]),
                        "statement": str(item["statement"]),
                        "topic_path": list(item["topic_path"]),
                    }
                    for item in knowledge_items
                )
            elif point.get("canonical_title") and point.get("canonical_statement"):
                prior_batch_knowledge.append(
                    {
                        "candidate_id": str(point["candidate_id"]),
                        "title": str(point["canonical_title"]),
                        "statement": str(point["canonical_statement"]),
                        "topic_path": list(point.get("topic_path") or []),
                    }
                )

    combined_decision = AssimilationDecision(points=combined_points)
    try:
        validate_separated_assimilation_decision(prepared, combined_decision)
    except ValueError:
        # Per-point batches intentionally keep prompt size bounded. A later
        # point can still select a truth handle that an earlier point merely
        # confirmed and another point mutates. Re-submit only that small
        # collision set with the revalidated source-backed candidate claims
        # and the current truth. This makes the semantic executor choose one
        # complete outcome instead of silently writing a partial mutation or
        # leaving a pseudo-final ``defer`` record behind.
        conflict = _conflicting_truth_target_candidates(combined_decision)
        if conflict is None:
            raise
        resolution_prepared = _prepare_truth_target_resolution(
            prepared,
            decision=combined_decision,
            candidate_ids=conflict.candidate_ids,
            truth_handles=conflict.truth_handles,
        )

        def validate_resolution(candidate: AssimilationDecision) -> dict[str, Any]:
            normalized = validate_separated_assimilation_decision(
                resolution_prepared,
                candidate,
            )
            _validate_truth_target_resolution(
                candidate,
                truth_handles=conflict.truth_handles,
            )
            return normalized

        try:
            resolution = _assimilate_with_schema_retry(
                provider,
                manifest=resolution_prepared.manifest,
                runtime_dir=runtime_dir,
                heartbeat=heartbeat,
                validate_decision=validate_resolution,
            )
        except ProviderError as exc:
            raise _provider_error_after_attempts(exc, results) from exc
        if not isinstance(resolution.decision, AssimilationDecision):
            raise ProviderError(
                "truth-target resolution returned an unexpected decision type",
                kind="unrecoverable",
            )
        normalized_resolution = normalize_identical_replacements(
            resolution_prepared,
            resolution.decision,
        )
        if normalized_resolution is not resolution.decision:
            resolution = replace(resolution, decision=normalized_resolution)
        validate_resolution(resolution.decision)
        results.append(resolution)
        conflict_ids = set(conflict.candidate_ids)
        combined_decision = AssimilationDecision(
            points=[
                point
                for point in combined_decision.points
                if point.candidate_id not in conflict_ids
            ]
            + list(resolution.decision.points)
        )
        validate_separated_assimilation_decision(prepared, combined_decision)
    return _combine_provider_results(results, decision=combined_decision)


@dataclass(frozen=True)
class _TruthTargetConflict:
    """The bounded candidate set that must resolve one mutable truth target."""

    candidate_ids: tuple[str, ...]
    truth_handles: tuple[str, ...]


def _conflicting_truth_target_candidates(
    decision: AssimilationDecision,
) -> _TruthTargetConflict | None:
    """Locate the specific points that require a second, joint decision."""

    target_points: dict[str, list[Any]] = {}
    for point in decision.points:
        for handle in point.matched_truth_handles:
            target_points.setdefault(str(handle), []).append(point)
    conflicting_handles = {
        handle
        for handle, points in target_points.items()
        if len(points) > 1
        and any(point.disposition in {"refine", "replace"} for point in points)
    }
    if not conflicting_handles:
        return None
    candidate_ids = tuple(
        dict.fromkeys(
            str(point.candidate_id)
            for handle in sorted(conflicting_handles)
            for point in target_points[handle]
        )
    )
    return _TruthTargetConflict(
        candidate_ids=candidate_ids,
        truth_handles=tuple(sorted(conflicting_handles)),
    )


def _prepare_truth_target_resolution(
    prepared: SeparatedPreparedAssimilation,
    *,
    decision: AssimilationDecision,
    candidate_ids: tuple[str, ...],
    truth_handles: tuple[str, ...],
) -> SeparatedPreparedAssimilation:
    """Build a small, source-verified adjudication manifest for one collision."""

    projections = {
        str(item.get("candidate_id") or ""): dict(item)
        for item in prepared.manifest.get("verified_candidates") or []
        if isinstance(item, dict)
    }
    if any(candidate_id not in projections for candidate_id in candidate_ids):
        raise ProviderError(
            "truth-target resolution is missing a verified candidate projection",
            kind="unrecoverable",
        )
    truth_by_handle = {
        handle: prepared.truth_by_handle[handle]
        for handle in truth_handles
        if handle in prepared.truth_by_handle
    }
    if set(truth_by_handle) != set(truth_handles):
        raise ProviderError(
            "truth-target resolution references unavailable current truth",
            kind="unrecoverable",
        )
    resolution_points = [
        point.model_dump(mode="json")
        for point in decision.points
        if point.candidate_id in set(candidate_ids)
    ]
    return SeparatedPreparedAssimilation(
        project_name=prepared.project_name,
        project_root=prepared.project_root,
        candidate_ids=candidate_ids,
        eligible_candidate_ids=candidate_ids,
        automatic_points=(),
        answer_status_by_candidate={
            candidate_id: prepared.answer_status_by_candidate[candidate_id]
            for candidate_id in candidate_ids
        },
        truth_by_handle=truth_by_handle,
        manifest={
            **prepared.manifest,
            "verified_candidates": [projections[candidate_id] for candidate_id in candidate_ids],
            "current_truth": [
                item
                for item in prepared.manifest.get("current_truth") or []
                if isinstance(item, dict)
                and str(item.get("handle") or "") in truth_by_handle
            ],
            "prior_batch_knowledge": [],
            "truth_target_resolution": {
                "candidate_ids": list(candidate_ids),
                "truth_handles": list(truth_handles),
                "preliminary_points": resolution_points,
            },
        },
    )


def _validate_truth_target_resolution(
    decision: AssimilationDecision,
    *,
    truth_handles: tuple[str, ...],
) -> None:
    """Require the shared executor to finish, rather than defer, a collision."""

    target_uses: dict[str, int] = {}
    for point in decision.points:
        if point.disposition in {"defer", "conflict", "handoff"}:
            raise ValueError(
                "truth-target resolution must choose a terminal no_write, reject, "
                "confirm, refine, or replace outcome"
            )
        for handle in point.matched_truth_handles:
            target_uses[str(handle)] = target_uses.get(str(handle), 0) + 1
    reused = sorted(handle for handle, count in target_uses.items() if count > 1)
    if reused:
        raise ValueError(
            "truth-target resolution must select at most one outcome per current truth: "
            + ", ".join(reused)
        )
    unavailable = sorted(set(target_uses) - set(truth_handles))
    if unavailable:
        raise ValueError(
            "truth-target resolution referenced a truth outside the collision: "
            + ", ".join(unavailable)
        )


def _deferred_assimilation_result(
    provider: DistillProvider,
    *,
    candidate_ids: Sequence[str],
    error: ProviderError,
    manifest: dict[str, Any],
) -> ProviderResult:
    """Defer every affected point without weakening the truth gate."""

    decision = AssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": candidate_id,
                    "disposition": "defer",
                    "matched_truth_handles": [],
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "knowledge_items": [],
                    "reason": (
                        "The assimilation output remained invalid after correction, "
                        "so this point was deferred without a truth write. "
                        f"Validation error: {str(error)[:600]}"
                    ),
                }
                for candidate_id in candidate_ids
            ]
        }
    )
    model = str(
        getattr(provider, "assimilation_model", None)
        or getattr(provider, "model", None)
        or ""
    ).strip() or None
    payload = json.dumps(manifest, ensure_ascii=False, sort_keys=True)
    result = ProviderResult(
        decision=decision,
        provider=f"{getattr(provider, 'name', 'provider')}->runtime_defer",
        model=model,
        duration_seconds=0.0,
        input_sha256=hashlib.sha256(payload.encode("utf-8")).hexdigest(),
        response_sha256=hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
        event_count=0,
        attempt_count=0,
        schema_valid=False,
    )
    if error.attempt_results:
        result = _combine_provider_results(
            [*error.attempt_results, result], decision=decision,
        )
    if error.unknown_attempt_count:
        result = replace(
            result,
            attempt_count=result.attempt_count + error.unknown_attempt_count,
            input_tokens=None, output_tokens=None, total_tokens=None,
        )
    return result


def _build_candidate_verification_manifest(
    *,
    packet: dict[str, Any],
    validated_candidates: list[tuple[Any, dict[str, Any]]],
    project_root: Path,
    backend: LocalMemoryBackend | None = None,
    distill_job_id: str | None = None,
) -> dict[str, Any]:
    """Bind each extracted claim to the exact current text it cites."""

    from harness_mem.autonomous.provider import _complete_exchange_content

    windows = {
        int(item["exchange_index"]): item
        for item in packet.get("semantic_decision_exchanges") or []
        if isinstance(item, dict) and item.get("exchange_index") is not None
    }
    rows: list[dict[str, Any]] = []
    for index, (candidate, arguments) in enumerate(validated_candidates):
        sources: list[dict[str, Any]] = []
        for ref in candidate.verification_refs:
            if ref.kind == "user_statement" and ref.exchange_index in windows:
                window = windows[int(ref.exchange_index)]
                sources.append(
                    {
                        "kind": "user_statement",
                        "exchange_index": ref.exchange_index,
                        "content_sha256": ref.content_sha256,
                        "content": _complete_exchange_content(window),
                    }
                )
            elif ref.kind == "repository" and ref.locator:
                locator = Path(ref.locator)
                path = (project_root / locator).resolve()
                if (
                    locator.is_absolute()
                    or not _path_is_within(path, project_root.resolve())
                    or not path.is_file()
                ):
                    sources.append(
                        {
                            "kind": "repository",
                            "locator": ref.locator,
                            "content_sha256": ref.content_sha256,
                            "content": None,
                        }
                    )
                else:
                    current_content = path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                    sources.append(
                        {
                            "kind": "repository",
                            "locator": ref.locator,
                            "content_sha256": ref.content_sha256,
                            "current_content_sha256": hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                            "content": current_content[:16000],
                        }
                    )
            elif ref.kind == "source_report" and ref.exchange_index in windows:
                from harness_mem.commands.evidence_admission import source_report_speaker_excerpt

                if backend is None or distill_job_id is None:
                    raise ProviderError("source-report verification requires its native source owner", kind="unrecoverable")
                sources.append({
                    "kind": "source_report", "role": ref.role,
                    "exchange_index": ref.exchange_index, "content_sha256": ref.content_sha256,
                    "content": source_report_speaker_excerpt(
                        backend, project_name=str(packet.get("project_name") or ""),
                        job_id=distill_job_id, ref=ref,
                    ),
                    "content_scope": "native_speaker_only; full exchange digest binds the source, not this excerpt",
                })
            elif ref.kind == "transcript" and ref.exchange_index in windows:
                window = windows[int(ref.exchange_index)]
                sources.append(
                    {
                        "kind": ref.kind,
                        "role": ref.role,
                        "exchange_index": ref.exchange_index,
                        "content_sha256": ref.content_sha256,
                        "content": _complete_exchange_content(window),
                    }
                )
            elif ref.kind == "transcript" and ref.chunk_index is not None:
                chunks = packet.get("semantic_evidence", {}).get("chunks", [])
                chunk = next(
                    (
                        item
                        for item in chunks
                        if int(item.get("chunk_index", -1)) == ref.chunk_index
                    ),
                    None,
                )
                sources.append(
                    {
                        "kind": "transcript",
                        "chunk_index": ref.chunk_index,
                        "content_sha256": ref.content_sha256,
                        "content": chunk.get("content") if isinstance(chunk, dict) else None,
                    }
                )
        rows.append(
            {
                "candidate_index": index,
                "kind": candidate.kind,
                "statement": _candidate_statement_from_arguments(arguments),
                "sources": sources,
            }
        )
    return {
        "contract_version": "candidate-semantic-verification-v2",
        "scope_partition_required": True,
        "project_name": packet.get("project_name"),
        # A decision excerpt may omit the subject established earlier. Keep
        # complete session context available independently of model-picked refs.
        # The provider wire projection shares identical text instead of
        # retransmitting each excerpt once per candidate.
        "session_context": [
            {
                "exchange_index": index,
                "content_sha256": window.get("content_sha256"),
                "content": _complete_exchange_content(window),
            }
            for index, window in windows.items()
        ],
        "candidates": rows,
    }


def _candidate_statement_from_arguments(arguments: dict[str, Any]) -> str:
    kind = arguments.get("kind")
    if kind == "memory":
        return str(arguments.get("content") or "")
    if kind == "rule":
        trigger = str(arguments.get("trigger") or "").strip().rstrip(".,:;。；：")
        pattern = str(arguments.get("pattern") or "").strip()
        return f"{trigger}: {pattern}" if trigger else pattern
    return " ".join(
        str(arguments.get(name) or "")
        for name in ("source_entity", "relation_type", "target_entity")
    ).strip()


def _path_is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _verify_final_knowledge_scope(
    provider: DistillProvider,
    *,
    backend: LocalMemoryBackend,
    prepared: SeparatedPreparedAssimilation,
    plan: dict[str, Any],
    original_manifest: dict[str, Any],
    governed_candidate_ids: list[str],
    runtime_dir: Path,
    heartbeat: Any,
) -> tuple[ProviderResult | None, dict[str, Any]]:
    """Recheck actual write/confirmation payloads, never old truth as evidence."""
    from harness_mem.commands.evidence_admission import reopen_knowledge_sources

    store = backend.structured_store.knowledge_store
    original_rows = list(original_manifest.get("candidates") or [])
    if len(original_rows) != len(governed_candidate_ids):
        raise ProviderError("final verification lost candidate/source coverage", kind="unrecoverable")
    sources_by_candidate = {
        candidate_id: list(row.get("sources") or [])
        for candidate_id, row in zip(governed_candidate_ids, original_rows)
    }
    points = [dict(point) for point in plan["points"]]
    payloads: dict[str, dict[str, Any]] = {}
    blocked: dict[str, str] = {}
    rows: list[dict[str, Any]] = []
    owner_by_index: dict[int, str] = {}
    reopened_by_target: dict[str, list[dict[str, Any]] | None] = {}

    async def target_sources(target_id: str) -> list[dict[str, Any]] | None:
        if target_id in reopened_by_target:
            return reopened_by_target[target_id]
        sources = await store.list_sources(target_id)
        validation, reopened = await reopen_knowledge_sources(
            backend, project_name=prepared.project_name, sources=sources,
            project_root=prepared.project_root,
        )
        value = None
        if (validation.verification_outcome == "verified" and sources
                and len(reopened) == len(sources)
                and all(item.content and not item.truncated for item in reopened)):
            value = [{
                "kind": source.source_kind, "content_sha256": source.content_sha256,
                "content": item.content,
                "content_scope": "reopened native/repository source, not current knowledge prose",
            } for source, item in zip(sources, reopened)]
        reopened_by_target[target_id] = value
        return value

    for point in points:
        if point["disposition"] not in {"add", "refine", "replace", "confirm"}:
            continue
        candidate_id = str(point["candidate_id"])
        payload = final_scope_payload(prepared, point)
        payloads[candidate_id] = payload
        sources = list(sources_by_candidate[candidate_id])
        for target in payload["targets"]:
            complete = asyncio.run(target_sources(target["id"]))
            if complete is None:
                blocked[candidate_id] = "final_scope_target_source_incomplete"
                break
            sources.extend(complete)
        if candidate_id in blocked:
            continue
        final_items = payload["targets"] if point["disposition"] == "confirm" else payload["knowledge_items"]
        if not final_items or not sources or any(not source.get("content") for source in sources):
            blocked[candidate_id] = "final_scope_source_incomplete"
            continue
        for item in final_items:
            index = len(rows)
            owner_by_index[index] = candidate_id
            rows.append({"candidate_index": index, "kind": "memory", "statement": str(item["statement"]),
                         "title": str(item["title"]),
                         "scope_text": str(item["title"]) + "\n" + str(item["statement"]),
                         "sources": sources})

    result = None
    if rows:
        result = _invoke_provider(
            provider, "verify", {
                "contract_version": "final-knowledge-scope-v1",
                "scope_partition_required": True,
                "project_name": prepared.project_name,
                "session_context": original_manifest.get("session_context") or [],
                "candidates": rows,
            }, runtime_dir=runtime_dir, heartbeat=heartbeat,
        )
        if not isinstance(result.decision, CandidateVerificationDecision):
            raise ProviderError("final scope verification returned an invalid decision", kind="unrecoverable")
        checked = list(result.decision.points)
        if (len(checked) != len(rows)
                or {point.candidate_index for point in checked} != set(range(len(rows)))):
            raise ProviderError("final scope verification must cover every item once", kind="unrecoverable")
        for verdict in checked:
            candidate_id = owner_by_index[verdict.candidate_index]
            scope = verification_scope_status(verdict, rows[verdict.candidate_index]["scope_text"])
            if (verdict.semantic_support != "supported" or scope != "source_scope_durable"
                    or verdict.future_scope != "durable"
                    or verdict.source_use not in {"standing_decision", "reusable_knowledge"}):
                blocked[candidate_id] = "final_" + (
                    scope if scope != "source_scope_durable" else "semantic_support_incomplete")

    async def retain_scope_verdicts() -> None:
        for candidate_id, payload in payloads.items():
            evidence_items = await store.list_evidence(candidate_id)
            if len(evidence_items) != 1:
                raise ProviderError("final scope evidence binding is incomplete", kind="unrecoverable")
            evidence = evidence_items[0]
            reason = blocked.get(candidate_id)
            code = reason or final_scope_proof(payload)
            evidence.verification_reason_codes = list(dict.fromkeys([
                *evidence.verification_reason_codes, code,
            ]))
            await store.save_evidence(evidence)

    asyncio.run(retain_scope_verdicts())
    for point in points:
        reason = blocked.get(str(point["candidate_id"]))
        if reason is not None:
            # Keep all predecessor rows if any item of a replacement failed.
            point.update(disposition="defer", matched_truth_ids=[], matched_truth_kinds=[],
                         canonical_title=None, canonical_statement=None, topic_path=[], knowledge_items=[],
                         reason=f"Final knowledge scope verification deferred this complete point: {reason}.")
    return result, {**plan, "points": points}


def _verify_candidates(
    provider: DistillProvider,
    *,
    manifest: dict[str, Any],
    validated_candidates: list[tuple[Any, dict[str, Any]]],
    runtime_dir: Path,
    heartbeat: Any,
) -> tuple[ProviderResult, list[tuple[Any, dict[str, Any]]]]:
    result = _invoke_provider(
        provider,
        "verify",
        manifest,
        runtime_dir=runtime_dir,
        heartbeat=heartbeat,
    )
    if not isinstance(result.decision, CandidateVerificationDecision):
        raise ProviderError(
            "verification provider returned an unexpected decision type",
            kind="unrecoverable",
        )
    points = list(result.decision.points)
    indexes = [point.candidate_index for point in points]
    expected = list(range(len(validated_candidates)))
    if sorted(indexes) != expected or len(indexes) != len(set(indexes)):
        raise ProviderError(
            "verification decision must cover every extracted candidate once",
            kind="unrecoverable",
        )
    by_index = {point.candidate_index: point for point in points}
    verified: list[tuple[Any, dict[str, Any]]] = []
    for index, (candidate, arguments) in enumerate(validated_candidates):
        point = by_index[index]
        updated = dict(arguments)
        codes = list(updated.get("verification_reason_codes") or [])
        codes.extend([f"source_use_{point.source_use}", f"future_scope_{point.future_scope}"])
        scope_status = verification_scope_status(point, _candidate_statement_from_arguments(arguments))
        codes.extend(["autonomous_final_scope_required", scope_status])
        if scope_status not in {"source_scope_durable", "source_scope_session_only"}:
            updated["verification_outcome"] = "unverified"
        elif point.semantic_support == "contradicted":
            updated["verification_outcome"] = "contradicted"
            codes.append("semantic_support_contradicted")
        elif scope_status == "source_scope_session_only" and point.semantic_support == "supported":
            updated["verification_outcome"] = "not_applicable"
            codes.extend(["session_only_not_durable", "source_use_task_context"])
        elif scope_status == "source_scope_session_only":
            updated["verification_outcome"] = "unverified"
            codes.append("semantic_support_incomplete")
        elif _is_historical_current_version_without_repository(
            manifest,
            candidate_index=index,
            arguments=updated,
        ):
            # A historical conversation can prove which version was current at
            # that time, but not which version is current now. Only repository
            # evidence reopened by this run can support that mutable claim.
            updated["verification_outcome"] = "not_applicable"
            codes.extend(
                [
                    "session_only_not_durable",
                    "current_version_requires_repository_evidence",
                ]
            )
        elif _is_unfinished_task_envelope_only(manifest, candidate_index=index):
            # A request template is evidence of what to do in that one session,
            # not evidence of a project rule.  This is intentionally a trusted
            # deterministic boundary: models previously promoted Read/Write/
            # Acceptance instructions from sessions with no assistant result.
            updated["verification_outcome"] = "not_applicable"
            codes.extend(
                ["session_only_not_durable", "unfinished_task_envelope"]
            )
        elif point.semantic_support == "supported" and point.future_scope == "durable":
            updated["verification_outcome"] = "verified"
            codes.extend(["semantic_support_verified", "future_utility_verified"])
            rebound_refs = _rebind_current_repository_refs(
                updated.get("verification_refs") or [],
                manifest=manifest,
                candidate_index=index,
            )
            if rebound_refs is not None:
                updated["verification_refs"] = rebound_refs
                codes.append("repository_ref_rebound_to_current")
        elif point.semantic_support == "contradicted":
            updated["verification_outcome"] = "contradicted"
            codes.append("semantic_support_contradicted")
        elif point.semantic_support == "supported" and point.future_scope == "session_only":
            updated["verification_outcome"] = "not_applicable"
            codes.append("session_only_not_durable")
        else:
            updated["verification_outcome"] = "unverified"
            codes.append("semantic_support_incomplete")
        updated["verification_reason_codes"] = list(dict.fromkeys(codes))
        verified.append((candidate, updated))
    return result, verified


_SEMANTIC_VERSION_RE = re.compile(
    r"(?<![\w.])v?\d+\.\d+\.\d+"
    r"(?:-[0-9a-z-]+(?:\.[0-9a-z-]+)*)?"
    r"(?:\+[0-9a-z-]+(?:\.[0-9a-z-]+)*)?(?!\w|\.\d)",
    re.IGNORECASE,
)
_CURRENT_VERSION_CLAIM_RE = re.compile(
    r"(?:\bcurrent\s+(?:source\s+|package\s+|project\s+)?version\b|"
    r"\bversion\s+is\b|当前(?:源码|软件|包|项目)?版本|版本\s*(?:为|是))",
    re.IGNORECASE,
)


def _is_historical_current_version_without_repository(
    manifest: dict[str, Any],
    *,
    candidate_index: int,
    arguments: dict[str, Any],
) -> bool:
    """Reject a mutable version claim supported only by historical dialogue.

    The rule is intentionally lexical and narrow. It does not classify every
    transient fact; it only closes the observed false-positive class without
    teaching the runtime a project name or a particular release number.
    """

    if arguments.get("kind") != "memory" or arguments.get("evidence_basis") == "source_report":
        return False
    statement = _candidate_statement_from_arguments(arguments)
    if not (
        _SEMANTIC_VERSION_RE.search(statement)
        and _CURRENT_VERSION_CLAIM_RE.search(statement)
    ):
        return False
    claimed_versions = {
        match.group(0).casefold().removeprefix("v")
        for match in _SEMANTIC_VERSION_RE.finditer(statement)
    }
    row = next(
        (
            value
            for value in manifest.get("candidates") or []
            if isinstance(value, dict)
            and int(value.get("candidate_index", -1)) == candidate_index
        ),
        None,
    )
    if not isinstance(row, dict):
        return True
    for source in row.get("sources") or []:
        if not (
            isinstance(source, dict)
            and source.get("kind") == "repository"
            and bool(source.get("locator"))
            and source.get("content") is not None
            and bool(source.get("current_content_sha256"))
        ):
            continue
        current_versions = {
            match.group(0).casefold().removeprefix("v")
            for match in _SEMANTIC_VERSION_RE.finditer(str(source["content"]))
        }
        if claimed_versions & current_versions:
            return False
    return True


_TASK_ENVELOPE_MARKERS = (
    "goal:",
    "working directory:",
    "read:",
    "write:",
    "acceptance:",
    "preflight:",
    "hard boundary:",
    "verification:",
    "目标：",
    "工作目录：",
    "读取：",
    "写入：",
    "验收：",
    "预检：",
    "硬边界：",
    "验证：",
)


def _is_unfinished_task_envelope_only(
    manifest: dict[str, Any], *, candidate_index: int
) -> bool:
    """Recognize a one-message task template with no recorded result.

    This is deliberately narrower than a general natural-language classifier.
    It only catches the concrete false-positive class where all evidence is a
    user task envelope and the semantic exchange has no assistant outcome.
    Explicit project decisions outside that template continue through normal
    semantic verification.
    """

    row = next(
        (
            value
            for value in manifest.get("candidates") or []
            if isinstance(value, dict)
            and int(value.get("candidate_index", -1)) == candidate_index
        ),
        None,
    )
    if not isinstance(row, dict):
        return False
    sources = row.get("sources") or []
    if not sources or any(
        not isinstance(source, dict) or source.get("kind") != "user_statement"
        for source in sources
    ):
        return False
    source_text = "\n".join(
        str(source.get("content") or "") for source in sources
    ).casefold()
    if "assistant outcome:" in source_text:
        return False
    return sum(marker in source_text for marker in _TASK_ENVELOPE_MARKERS) >= 2


def _rebind_current_repository_refs(
    refs: list[Any],
    *,
    manifest: dict[str, Any],
    candidate_index: int,
) -> list[dict[str, Any]] | None:
    """Bind semantically reverified repository refs to current file bytes.

    Historical sessions carry the digest that was current when the conversation
    happened. A changed digest alone does not prove that the claim is stale. Once
    the bounded verifier confirms that today's file still supports the claim, the
    trusted runtime replaces only the digest with the one it computed itself.
    """

    candidate_rows = manifest.get("candidates") or []
    row = next(
        (
            item
            for item in candidate_rows
            if isinstance(item, dict)
            and int(item.get("candidate_index", -1)) == candidate_index
        ),
        None,
    )
    if row is None:
        return None
    current_by_locator = {
        str(source.get("locator") or ""): str(
            source.get("current_content_sha256") or ""
        )
        for source in row.get("sources") or []
        if isinstance(source, dict)
        and source.get("kind") == "repository"
        and source.get("locator")
        and source.get("current_content_sha256")
    }
    if not current_by_locator:
        return None
    rebound: list[dict[str, Any]] = []
    changed = False
    for value in refs:
        ref = dict(value) if isinstance(value, dict) else value.model_dump(
            mode="json", exclude_none=True
        )
        locator = str(ref.get("locator") or "")
        current_digest = current_by_locator.get(locator)
        if ref.get("kind") == "repository" and current_digest:
            ref["content_sha256"] = current_digest
            changed = True
        rebound.append(ref)
    return rebound if changed else None


def _native_provider_receipt(
    results: Sequence[ProviderResult], error: ProviderError | None = None,
) -> dict[str, Any] | None:
    """Keep every native call, including validated prefixes of a deferred job."""
    attempts: dict[str, dict[str, Any]] = {}
    selected: list[ProviderResult] = []
    for result in [*results, *(error.attempt_results if error else ())]:
        ids = {str(item.get("call_id")) for item in result.native_attempts}
        if not ids or ids <= attempts.keys():
            continue
        if ids & attempts.keys():
            # The per-call journal is authoritative over an overlapping
            # semantic-stage aggregate; its counters must not be paid twice.
            continue
        selected.append(result)
        for item in result.native_attempts:
            attempts[str(item.get("call_id"))] = item
    if error:
        for item in error.native_attempts:
            attempts[str(item.get("call_id"))] = item
    if not attempts:
        return None
    receipt = _combine_provider_results(selected).receipt() if selected else {}
    receipt["native_attempts"] = list(attempts.values())
    # Canonical leaf call identities also include errors that occurred before
    # a ProviderResult could be returned. Never let a known prefix hide that
    # unknown suffix, or count overlapping stage aggregates twice.
    metrics = ("input_tokens", "output_tokens", "total_tokens")
    leaves = list(attempts.values())
    for metric in metrics:
        values = [(item.get("usage") or {}).get(metric) for item in leaves]
        receipt[metric] = (
            sum(values) if all(type(value) is int and value >= 0 for value in values) else None
        )
    receipt["known_usage_subtotal"] = {
        metric: sum(
            value for item in leaves
            if type(value := (item.get("known_usage_subtotal") or item.get("usage") or {}).get(metric)) is int
            and value >= 0
        ) for metric in metrics
    }
    receipt["attempt_count"] = len(leaves)
    receipt["unknown_native_call_usage_count"] = sum(
        any((item.get("usage") or {}).get(metric) is None for metric in metrics) for item in leaves
    )
    if error is not None:
        receipt["schema_valid"] = False
        receipt["unknown_attempt_count"] = error.unknown_attempt_count
        if error.unknown_attempt_count:
            receipt.update(input_tokens=None, output_tokens=None, total_tokens=None)
            receipt["attempt_count"] = int(receipt.get("attempt_count", 0)) + error.unknown_attempt_count
    return receipt


def _batch_provider_usage(outcomes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Complete totals and observed subtotals are different accounting claims."""
    metrics = ("input_tokens", "output_tokens", "total_tokens")
    reports = [item.get("provider") for item in outcomes if item.get("status") != "busy"]
    result: dict[str, Any] = {}
    for metric in metrics:
        values = [report.get(metric) if isinstance(report, dict) else None for report in reports]
        result[metric] = (
            sum(values) if all(type(value) is int and value >= 0 for value in values) else None
        )
    result["known_usage_subtotal"] = {
        metric: sum(
            value for report in reports if isinstance(report, dict)
            if type(value := (report.get("known_usage_subtotal") or report).get(metric)) is int
            and value >= 0
        ) for metric in metrics
    }
    result["unknown_usage_job_count"] = sum(
        not isinstance(report, dict)
        or any(type(report.get(metric)) is not int or report[metric] < 0 for metric in metrics)
        for report in reports
    )
    result["unknown_native_call_usage_count"] = sum(
        value for report in reports if isinstance(report, dict)
        if type(value := report.get("unknown_native_call_usage_count")) is int and value >= 0
    )
    return result


def _combine_provider_results(
    results: list[ProviderResult],
    *,
    decision: Any | None = None,
) -> ProviderResult:
    """Preserve the final decision while accounting for every provider attempt."""

    last = results[-1]
    if len(results) == 1 and decision is None:
        return last

    def summed(name: str) -> int | None:
        values = [getattr(item, name) for item in results]
        return (
            None
            if any(value is None for value in values)
            else sum(value or 0 for value in values)
        )

    return ProviderResult(
        decision=last.decision if decision is None else decision,
        provider=last.provider,
        model=last.model,
        duration_seconds=sum(item.duration_seconds for item in results),
        input_sha256=hashlib.sha256(
            "|".join(item.input_sha256 for item in results).encode("utf-8")
        ).hexdigest(),
        response_sha256=hashlib.sha256(
            "|".join(item.response_sha256 for item in results).encode("utf-8")
        ).hexdigest(),
        input_tokens=summed("input_tokens"),
        output_tokens=summed("output_tokens"),
        total_tokens=summed("total_tokens"),
        event_count=sum(item.event_count for item in results),
        attempt_count=sum(item.attempt_count for item in results),
        schema_valid=all(item.schema_valid for item in results),
        host_client=last.host_client,
        native_attempts=tuple(attempt for result in results for attempt in result.native_attempts),
    )


def normalize_provider_review_state(decision: Any) -> Any:
    """Enforce review-state invariants at the trusted runtime boundary."""

    review = decision.semantic_review
    unfinished = [
        str(item).strip() for item in review.unfinished_work if str(item).strip()
    ]
    if (
        not unfinished
        or review.evidence_status == "contradicted"
        or review.promotion_decision == "blocked"
    ):
        return decision
    updates: dict[str, Any] = {}
    if review.last_turn_status != "unfinished":
        updates["last_turn_status"] = "unfinished"
    if review.evidence_status != "partial":
        updates["evidence_status"] = "partial"
    if review.promotion_decision != "partial":
        updates["promotion_decision"] = "partial"
    if not updates:
        return decision
    return decision.model_copy(
        update={"semantic_review": review.model_copy(update=updates)}
    )


def _candidate_arguments(
    candidate: Any,
    *,
    job: SessionDistillJob,
    packet: dict[str, Any],
) -> dict[str, Any]:
    evidence = _safe_evidence(candidate, packet=packet)
    common = {
        "kind": candidate.kind,
        "project_name": job.project_name,
        "distill_job_id": job.id,
        **evidence,
    }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "memory":
        _require_candidate_fields(candidate, "category", "content", "confidence")
        return {
            **common,
            "category": str(candidate.category),
            "content": str(candidate.content),
            "source": f"distill-job:{job.id}",
            "confidence": _required_confidence(candidate),
            "tags": candidate.tags or [],
        }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "rule":
        pattern = candidate.pattern or candidate.content
        if not pattern or not candidate.trigger:
            raise ValueError("rule candidate missing fields: ['pattern', 'trigger']")
        pattern, trigger = _normalize_rule_candidate_fields(
            str(pattern),
            str(candidate.trigger),
        )
        return {
            **common,
            "session_id": job.session_id,
            "pattern": pattern,
            "trigger": trigger,
            "examples": candidate.examples or [],
        }
    if isinstance(candidate, DistillCandidate) and candidate.kind == "relation":
        _require_candidate_fields(
            candidate,
            "source_entity",
            "target_entity",
            "relation_type",
            "evidence",
            "confidence",
        )
        return {
            **common,
            "source_entity": str(candidate.source_entity),
            "target_entity": str(candidate.target_entity),
            "relation_type": str(candidate.relation_type),
            "evidence": str(candidate.evidence),
            "source": f"distill-job:{job.id}",
            "confidence": _required_confidence(candidate),
        }
    raise TypeError(f"unsupported candidate type: {type(candidate).__name__}")


def _normalize_rule_candidate_fields(pattern: str, trigger: str) -> tuple[str, str]:
    """Repair only an obvious provider reversal of rule condition and behavior."""

    normalized_pattern = " ".join(pattern.split())
    normalized_trigger = " ".join(trigger.split())
    condition_prefixes = (
        "when ",
        "whenever ",
        "if ",
        "after ",
        "before ",
        "during ",
        "当",
        "如果",
        "在",
    )
    condition_suffixes = (
        "时",
        "时。",
        "后",
        "后。",
        "前",
        "前。",
        "情况下",
        "情况下。",
    )
    action_markers = (
        "must ",
        "should ",
        "create ",
        "preserve ",
        "record ",
        "requeue ",
        "创建",
        "保存",
        "记录",
        "重新处理",
        "重新入队",
        "必须",
        "应当",
        "应该",
    )

    def looks_like_condition(value: str) -> bool:
        lowered = value.casefold()
        return lowered.startswith(condition_prefixes) or value.endswith(
            condition_suffixes
        )

    def looks_like_action(value: str) -> bool:
        lowered = value.casefold()
        return any(marker in lowered for marker in action_markers)

    if (
        looks_like_condition(normalized_pattern)
        and not looks_like_condition(normalized_trigger)
        and looks_like_action(normalized_trigger)
    ):
        return normalized_trigger, normalized_pattern
    return normalized_pattern, normalized_trigger


def _governed_candidate_id(result: dict[str, Any]) -> str | None:
    """Read the stable id returned by one kind-specific suggest handler."""

    for key in ("entry_id", "candidate_id", "fact_id"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    return None


def _sum_provider_metric(left: int | None, right: int | None) -> int | None:
    if left is None or right is None:
        return None
    return int(left or 0) + int(right or 0)


def provider_candidate_control_reason(
    candidate: Any,
    *,
    decision: Any,
) -> str | None:
    """Route explicit task handoffs without deciding a point's semantic value."""
    review = decision.semantic_review
    category = str(getattr(candidate, "category", None) or "").lower()
    candidate_statement = str(
        getattr(candidate, "content", None)
        or getattr(candidate, "pattern", None)
        or getattr(candidate, "evidence", None)
        or ""
    ).strip()
    normalized_statement = " ".join(candidate_statement.casefold().split())
    normalized_unfinished = {
        " ".join(str(item).casefold().split())
        for item in review.unfinished_work
        if str(item).strip()
    }
    # A handoff category, or an exact copy of a listed next step, is task
    # narration.  Do not reject a real durable rule merely because it contains
    # words such as "unfinished" while specifying how to handle that state.
    if review.unfinished_work and (
        any(
            marker in category
            for marker in ("handoff", "unfinished", "task", "后续", "待办", "未完成")
        )
        or normalized_statement in normalized_unfinished
    ):
        return "unfinished work belongs to the job-bound handoff"
    # Replacement wording may contain both an obsolete value and its valid
    # successor. Only evidence verification and assimilation can decide which
    # parts are useful; a lexical veto here silently discards the entire point.
    return None


def _require_candidate_fields(candidate: DistillCandidate, *names: str) -> None:
    missing = [name for name in names if getattr(candidate, name) in {None, ""}]
    if missing:
        raise ValueError(f"{candidate.kind} candidate missing fields: {missing}")


def _required_confidence(candidate: DistillCandidate) -> float:
    """Keep a legacy ranking hint from vetoing a valid separated candidate.

    Confidence is not current knowledge and cannot establish truth.  The
    compatibility candidate tables still require a value, so an omitted model
    hint receives the neutral existing-default value instead of converting an
    otherwise valid evidence-backed point into a failed session.
    """

    return 0.5 if candidate.confidence is None else float(candidate.confidence)


def _safe_evidence(candidate: Any, *, packet: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        (int(item.get("exchange_index") or 0), str(item.get("content_sha256") or ""))
        for item in packet.get("zero_candidate_exchange_refs", [])
        if isinstance(item, dict)
    }
    refs = [
        item.model_dump(mode="json", exclude_none=True)
        for item in candidate.verification_refs
    ]
    reasons = list(candidate.verification_reason_codes)
    verified_user_statement = (
        candidate.evidence_basis == "user_statement"
        and candidate.verification_outcome == "verified"
        and bool(refs)
        and all(
            ref.get("kind") == "user_statement"
            and ref.get("role") == "user"
            and (
                int(ref.get("exchange_index") or 0),
                str(ref.get("content_sha256") or ""),
            )
            in allowed
            for ref in refs
        )
    )
    if verified_user_statement:
        return {
            "evidence_basis": "user_statement",
            "verification_outcome": "verified",
            "verification_refs": refs,
            "verification_reason_codes": reasons,
        }
    reasons.append(f"autonomous_provider_cannot_verify_{candidate.evidence_basis}")
    return {
        "evidence_basis": candidate.evidence_basis,
        "verification_outcome": "unverified",
        "verification_refs": refs,
        "verification_reason_codes": list(dict.fromkeys(reasons)),
    }


def _materialize_note(job: SessionDistillJob, *, notes_dir: Path) -> dict[str, Any]:
    if not str(job.session_id).strip():
        raise ProviderError(
            "completed job has no pre-cleanup session identity for Note materialization",
            kind="unrecoverable",
        )
    return materialize_session_note(job, notes_dir=notes_dir)


def _identity_digest(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _repair_missing_notes(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path,
    notes_dir: Path,
) -> None:
    completed = backend.transcript_store.list_distill_jobs(
        project_name=project_name,
        status="completed",
        limit=200,
    )
    for job in completed:
        path, _recovered_session_id = existing_session_note_path(notes_dir, job)
        summary = str(job.semantic_review.get("session_summary") or "").strip()
        if (
            not is_meaningful_session_summary(summary)
            and path is not None
            and path.is_file()
        ):
            recovered = _summary_from_note(path)
            if recovered:
                job = backend.transcript_store.backfill_distill_session_summary(
                    job.id,
                    session_summary=recovered,
                )
        if (
            not is_meaningful_session_summary(
                job.semantic_review.get("session_summary")
            )
            and path is None
            and job.semantic_review.get("evidence_state") == "source_pruned"
        ):
            job = backend.transcript_store.mark_distill_historical_summary_unavailable(
                job.id,
                reason="immutable_note_missing_after_source_pruned",
            )
        if (path is not None and path.is_file()) or not job.semantic_review:
            continue
        if not str(job.session_id).strip():
            # The cleanup ledger no longer has enough identity to create a new
            # immutable path; report the gap instead of inventing one.
            continue
        note = _materialize_note(job, notes_dir=notes_dir)
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={
                "last_note_materialized_at": note["materialized_at"],
                "note": note,
                "job_id": job.id,
                "session_id": job.session_id,
            },
        )


def _summary_from_note(path: Path) -> str | None:
    try:
        content = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for heading in ("## 会话主题", "## Scope"):
        marker = content.find(heading)
        if marker < 0:
            continue
        body = content[marker + len(heading) :]
        next_heading = body.find("\n## ")
        if next_heading >= 0:
            body = body[:next_heading]
        compact = " ".join(line.strip() for line in body.splitlines() if line.strip())
        if len(compact) >= 12:
            return compact[:2000]
    return None


def _record_success_receipt(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None,
    client: str,
    job: SessionDistillJob,
    note: dict[str, Any],
    provider_receipt: dict[str, Any] | None,
) -> dict[str, str | None]:
    completed_at = job.completed_at.isoformat() if job.completed_at else _now()
    semantic_success_at = _now() if provider_receipt is not None else None
    completion = {
        "last_semantic_success_at": semantic_success_at,
        "last_job_completed_at": completed_at,
        "last_note_materialized_at": str(note["materialized_at"]),
    }
    current = (
        read_autonomous_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
        )
        or {}
    )
    hook_reentry_count = count_hook_reentry_blocks(
        backend.data_dir,
        project_name=project_name,
        project_root=project_root,
        trigger_id=trigger_id,
    )
    verified_completion = {
        "schema_version": 1,
        "trigger_id": trigger_id,
        "dispatch_generation": current.get("dispatch_generation"),
        "client": client,
        "execution_source": "autonomous_worker",
        "hook_launch_verified": current.get("hook_launch_verified") is True,
        "hook_config_fingerprint": current.get("hook_config_fingerprint"),
        "runtime_fingerprint": current.get("runtime_fingerprint"),
        "config_fingerprint": current.get("config_fingerprint"),
        "hook_reentry_count": hook_reentry_count,
        "hook_guard_check": current.get("hook_guard_check"),
        "job_id": job.id,
        "session_id": job.session_id,
        **completion,
        "provider": provider_receipt,
        "note": note,
    }
    if trigger_id is not None and job.session_id != trigger_id:
        # This job belongs to backlog work offered in the same batch. Keep its
        # evidence in the batch outcome without rebinding the active Hook's
        # generation-scoped receipt to another session.
        _write_receipt(
            backend.data_dir,
            project_name=project_name,
            project_root=project_root,
            update={"last_background_completion": verified_completion},
        )
        return completion
    _write_receipt(
        backend.data_dir,
        project_name=project_name,
        project_root=project_root,
        update={
            "state": "succeeded",
            "trigger_id": trigger_id,
            "client": client,
            "execution_source": "autonomous_worker",
            "job_id": job.id,
            "session_id": job.session_id,
            **completion,
            "provider": provider_receipt,
            "note": note,
            "last_verified_completion": verified_completion,
            "error": None,
        },
    )
    return completion


__all__ = [
    "build_provider_manifest",
    "autonomous_config_fingerprint",
    "autonomous_receipt_path",
    "autonomous_runtime_fingerprint",
    "record_post_turn_preflight_failure",
    "record_post_turn_retry_backoff",
    "read_autonomous_receipt",
    "provider_candidate_control_reason",
    "normalize_provider_review_state",
    "run_autonomous_distill_batch",
]
