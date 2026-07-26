"""MCP tool handler facade for harness-mem.

``server.py`` owns stdio protection, backend initialization, and JSON-RPC
routing. This module owns dependency binding, compatibility re-exports, the
small remaining ingest/candidate helpers, and the registry bound to
``tool_specs``. Capability bodies live in bounded ``*_handlers.py`` modules.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Callable
from uuid import NAMESPACE_URL, uuid5

from harness_mem.commands import support as _support  # noqa: F401
from harness_mem.commands.auto_review import auto_review_candidates
from harness_mem.commands.dream import (
    dream_auto_tick,
)
from harness_mem.commands.ingest import cmd_ingest
from harness_mem.commands.integration_cmds import (  # noqa: F401
    SUPPORTED_HOOK_CLIENTS,
    cmd_install_hook_suite,
)
from harness_mem.commands.support import (
    SUPPORTED_INGEST_CLIENTS,
    get_active_project,
    normalize_client_name,
    resolve_project_context,
    resolve_host_source,
    resolve_ingest_client,
    set_active_project,
)
from harness_mem.config.merge import load_merged_config
from harness_mem.event_log import StateEventType, append_state_event
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.mcp.governance_handlers import (
    tool_confirm_memory_entry,
    tool_confirm_relation_fact,
    tool_confirm_rule,
    tool_confirm_supersede,
    tool_create_rule_candidate,
    tool_create_task_handoff,
    tool_govern_memory,
    tool_reject_memory_entry,
    tool_reject_relation_fact,
    tool_reject_rule,
    tool_reject_supersede,
    tool_suggest_correction,
    tool_suggest_memory_entry,
    tool_suggest_relation_fact,
    tool_suggest_rule,
    tool_suggest_supersede,
)

BackendProvider = Callable[[], LocalMemoryBackend]
ObserverDataDirProvider = Callable[[], Path]
CostSurfaceBudgetsProvider = Callable[[str | None], dict[str, int] | None]

_backend_provider: BackendProvider | None = None
_observer_data_dir_provider: ObserverDataDirProvider | None = None
_cost_surface_budgets_provider: CostSurfaceBudgetsProvider | None = None
logger = logging.getLogger("harness_mem_mcp")
_default_logger = logger


def configure_tool_handler_dependencies(
    *,
    backend_provider: BackendProvider,
    observer_data_dir: ObserverDataDirProvider,
    cost_surface_budgets: CostSurfaceBudgetsProvider,
    logger_instance: logging.Logger,
) -> None:
    """Bind server-owned dependencies needed by MCP tool handlers."""
    global _backend_provider, _observer_data_dir_provider
    global _cost_surface_budgets_provider, logger
    _backend_provider = backend_provider
    _observer_data_dir_provider = observer_data_dir
    _cost_surface_budgets_provider = cost_surface_budgets
    logger = logger_instance


def reset_tool_handler_dependencies() -> None:
    """Reset MCP tool handler dependencies to their unconfigured defaults."""
    global _backend_provider, _observer_data_dir_provider
    global _cost_surface_budgets_provider, logger
    _backend_provider = None
    _observer_data_dir_provider = None
    _cost_surface_budgets_provider = None
    logger = _default_logger


def _get_backend() -> LocalMemoryBackend:
    if _backend_provider is None:
        raise RuntimeError("MCP tool handlers are not configured")
    return _backend_provider()


def _observer_data_dir() -> Path:
    if _observer_data_dir_provider is None:
        raise RuntimeError("MCP tool handlers are not configured")
    return _observer_data_dir_provider()


def _cost_surface_budgets(project_name: str | None) -> dict[str, int] | None:
    if _cost_surface_budgets_provider is None:
        raise RuntimeError("MCP tool handlers are not configured")
    return _cost_surface_budgets_provider(project_name)


def _record_state_event(
    backend: LocalMemoryBackend,
    *,
    event_type: StateEventType,
    project_name: str | None,
    target_kind: str,
    target_id: str,
    status: str | None = None,
    source_surface: str,
    payload: dict[str, Any] | None = None,
) -> str | None:
    """Best-effort governance audit event for MCP-visible writes."""

    try:
        return append_state_event(
            backend.data_dir,
            event_type=event_type,
            project_name=project_name,
            target_kind=target_kind,
            target_id=target_id,
            status=status,
            source_surface=source_surface,
            actor="mcp",
            payload=payload,
        )
    except Exception:
        logger.exception(
            "Failed to append state audit event for %s/%s", target_kind, target_id
        )
        return None


# =============================================================================
# READ TOOLS
# =============================================================================


def tool_set_active_project(project_name: str) -> dict:
    """Set the active project so wake/search/suggest defaults pick it up.

    The active project is the implicit default for tools that take
    ``project_name`` and is the only thing that keeps memory written in
    different working directories from cross-contaminating.
    """
    name = (project_name or "").strip()
    if not name:
        return {"success": False, "error": "project_name must not be empty"}
    previous = get_active_project()
    set_active_project(name)
    return {
        "success": True,
        "project_name": name,
        "previous_active_project": previous,
    }


def tool_ingest_sessions(
    project_name: str | None = None,
    client: str = "auto",
    limit: int = 10,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
) -> dict:
    """Low-level transcript sync used by /hm:distill and diagnostics."""
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, grok, antigravity, opencode, hermes",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    host_source = resolve_host_source(normalized_client)
    project_context = resolve_project_context(
        project_name,
        project_root=project_root,
        required=True,
        action_label="MCP transcript sync",
    )
    if project_context is None:
        return {
            "success": False,
            "error": (
                "project_name could not be resolved. Pass project_name, pass "
                "project_root, run from a workspace directory, or set an active project."
            ),
        }
    resolved_project_name = project_context.project_name
    resolved_project_root = (
        str(project_context.project_root)
        if project_context.project_root is not None
        else project_root
    )

    payload = _run_command_to_payload(
        cmd_ingest(
            normalized_client,
            resolved_project_name,
            limit,
            full_rescan,
            scope=scope,
            project_root=resolved_project_root,
        )
    )
    return {
        "project_name": resolved_project_name,
        "project_root": resolved_project_root,
        "project_resolution_source": project_context.source,
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
        "host_client": host_source.host_client,
        "source_kind": host_source.source_kind,
        "adapter_available": host_source.adapter_available,
        "scope": scope,
        "limit": limit,
        **payload,
    }


# Pure serializers extracted to mcp/serializers.py — see the future-split
# note in the module docstring. We re-export the names here so internal
# callers (and any external import that already uses them) keep working.
from harness_mem.mcp.serializers import (  # noqa: E402, F401
    _isoformat,
    _serialize_merge_suggestion_candidate,
    _serialize_memory_entry_candidate,
    _serialize_relation_fact_candidate,
    _serialize_rule_candidate,
    _serialize_stale_truth_suggestion_candidate,
    _serialize_supersede_candidate,
)


async def _gather_candidate_payload(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    status: str,
    limit: int,
) -> tuple[
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
    list[dict],
]:
    rules = await backend.structured_store.list_rule_candidates(
        project_name, status=status
    )
    entries = await backend.structured_store.list_memory_entries(
        project_name, status=status, limit=limit
    )
    facts = await backend.structured_store.list_relation_facts(
        project_name, status=status, limit=limit
    )
    supersedes = await backend.structured_store.list_supersede_candidates(
        project_name, status=status
    )
    merge_suggestions = await backend.structured_store.list_merge_suggestion_candidates(
        project_name, status=status
    )
    stale_suggestions = (
        await backend.structured_store.list_stale_truth_suggestion_candidates(
            project_name, status=status
        )
    )
    return (
        [_serialize_rule_candidate(candidate) for candidate in rules[:limit]],
        [_serialize_memory_entry_candidate(entry) for entry in entries],
        [_serialize_relation_fact_candidate(fact) for fact in facts],
        [_serialize_supersede_candidate(candidate) for candidate in supersedes[:limit]],
        [
            _serialize_merge_suggestion_candidate(candidate)
            for candidate in merge_suggestions[:limit]
        ],
        [
            _serialize_stale_truth_suggestion_candidate(candidate)
            for candidate in stale_suggestions[:limit]
        ],
    )


def tool_list_candidates(
    project_name: str, status: str = "pending", limit: int = 100
) -> dict:
    """Return structured memory candidates for human review."""
    from harness_mem.governance_status import GOVERNANCE_STATUSES

    if status not in GOVERNANCE_STATUSES:
        return {
            "success": False,
            "error": (
                "status must be one of: pending, deferred, rejected, auto_confirmed, "
                "provisional, user_confirmed, superseded"
            ),
        }

    effective_limit = max(1, min(int(limit), 500))
    backend = _get_backend()
    (
        rule_candidates,
        memory_entries,
        relation_facts,
        supersede_candidates,
        merge_suggestion_candidates,
        stale_truth_suggestion_candidates,
    ) = asyncio.run(
        _gather_candidate_payload(
            backend,
            project_name=project_name,
            status=status,
            limit=effective_limit,
        )
    )
    all_candidates = [
        *rule_candidates,
        *memory_entries,
        *relation_facts,
        *supersede_candidates,
        *merge_suggestion_candidates,
        *stale_truth_suggestion_candidates,
    ]
    all_candidates.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    candidates = all_candidates[:effective_limit]

    return {
        "success": True,
        "project_name": project_name,
        "status": status,
        "limit": effective_limit,
        "candidates": candidates,
        "rule_candidates": rule_candidates,
        "memory_entries": memory_entries,
        "relation_facts": relation_facts,
        "supersede_candidates": supersede_candidates,
        "merge_suggestion_candidates": merge_suggestion_candidates,
        "stale_truth_suggestion_candidates": stale_truth_suggestion_candidates,
        "count": len(candidates),
        "total_count": len(all_candidates),
        "rule_count": len(rule_candidates),
        "memory_entry_count": len(memory_entries),
        "relation_fact_count": len(relation_facts),
        "supersede_count": len(supersede_candidates),
        "merge_suggestion_count": len(merge_suggestion_candidates),
        "stale_truth_suggestion_count": len(stale_truth_suggestion_candidates),
    }


def tool_get_candidate_detail(
    candidate_id: str, candidate_kind: str | None = None
) -> dict:
    """Return one reviewable candidate/detail payload without mutating state."""

    backend = _get_backend()

    async def _lookup() -> tuple[str, dict] | None:
        lookups = {
            "memory_entry": (
                backend.structured_store.get_memory_entry,
                _serialize_memory_entry_candidate,
            ),
            "relation_fact": (
                backend.structured_store.get_relation_fact,
                _serialize_relation_fact_candidate,
            ),
            "rule_candidate": (
                backend.structured_store.get_rule_candidate,
                _serialize_rule_candidate,
            ),
            "supersede": (
                backend.structured_store.get_supersede_candidate,
                _serialize_supersede_candidate,
            ),
            "merge_suggestion_candidate": (
                backend.structured_store.get_merge_suggestion_candidate,
                _serialize_merge_suggestion_candidate,
            ),
            "stale_truth_suggestion_candidate": (
                backend.structured_store.get_stale_truth_suggestion_candidate,
                _serialize_stale_truth_suggestion_candidate,
            ),
        }
        if candidate_kind:
            selected = (
                {candidate_kind: lookups[candidate_kind]}
                if candidate_kind in lookups
                else {}
            )
        else:
            selected = lookups
        for kind, (getter, serializer) in selected.items():
            candidate = await getter(candidate_id)
            if candidate is not None:
                return kind, serializer(candidate)
        return None

    found = asyncio.run(_lookup())
    if found is None:
        return {
            "success": False,
            "candidate_id": candidate_id,
            "candidate_kind": candidate_kind,
            "error": "candidate not found",
        }

    kind, candidate = found
    return {
        "success": True,
        "candidate_id": candidate_id,
        "candidate_kind": kind,
        "candidate": candidate,
    }


def tool_auto_review_candidates(
    project_name: str,
    apply: bool = False,
) -> dict:
    """Run conservative heuristic auto-review over pending candidates.

    Returns the standard summary shape
    (auto_confirmed / auto_rejected / kept_pending / needs_user_confirmation).
    With ``apply=False`` the structured store is not modified — the response
    is what auto-review *would* do. With ``apply=True`` decisions are applied
    via the same status mutators users would invoke manually.
    """
    backend = _get_backend()
    summary = asyncio.run(
        auto_review_candidates(
            backend,
            project_name=project_name,
            apply=apply,
        )
    )
    payload = summary.to_dict()
    payload["success"] = True
    payload["project_name"] = project_name
    payload["applied"] = bool(apply)
    if apply:
        from harness_mem.commands.distill_lifecycle import complete_pending_distill_jobs

        candidate_ids = [
            decision.candidate_id for decision in summary.applied_decisions
        ]
        completed_jobs = complete_pending_distill_jobs(
            backend,
            project_name=project_name,
            candidate_ids=candidate_ids,
            job_id=None,
        )
        payload["distill_jobs_completed"] = [job.id for job in completed_jobs]
        if completed_jobs:
            project_root = completed_jobs[0].project_root
            try:
                config = load_merged_config(project_root)
                payload["dream"] = asyncio.run(
                    dream_auto_tick(
                        backend,
                        project_name=project_name,
                        project_root=project_root,
                        config=config,
                        source="agent",
                    )
                )
            except Exception as exc:  # noqa: BLE001 - review remains auditable.
                payload["dream"] = {
                    "success": False,
                    "status": "failed",
                    "project_name": project_name,
                    "error": f"{type(exc).__name__}: {exc}"[:512],
                }
    return payload


# =============================================================================
# WRITE TOOLS
# =============================================================================


def _distill_candidate_id(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str | None,
    candidate_kind: str,
    payload: dict[str, Any],
) -> str | None:
    """Return a deterministic candidate id for review-ready distill work."""

    if not distill_job_id:
        return None
    job = backend.transcript_store.get_distill_job(distill_job_id)
    if job is None:
        raise ValueError("distill job not found")
    if job.project_name != project_name:
        raise ValueError("distill job belongs to another project")
    if job.status != "reviewing":
        raise ValueError(
            "distill candidates can only be created after all chunks are reviewed"
        )
    fingerprint = json.dumps(
        _normalize_semantic_claim(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return str(
        uuid5(
            NAMESPACE_URL,
            (
                "harness-mem://distill-candidate/"
                f"{project_name}/{job.source_revision}/{job.pipeline_version}/"
                f"{candidate_kind}/{fingerprint}"
            ),
        )
    )


def _normalize_semantic_claim(value: Any) -> Any:
    """Canonicalize whitespace and unordered containers for claim idempotency."""

    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, dict):
        return {
            str(key): _normalize_semantic_claim(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        normalized = [_normalize_semantic_claim(item) for item in value]
        return sorted(
            normalized,
            key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
    return value


# Runtime modules keep the registry facade stable while owning separate handler domains.
from harness_mem.mcp.read_handlers import (  # noqa: E402, F401
    CONTEXT_OUTCOME_VALUES,
    VALID_CONTEXT_OUTCOMES,
    VALID_MEMORY_TYPES,
    VALID_RETRIEVAL_PROFILES,
    RetrievalProfile,
    _action,
    _autopilot_dx_metadata,
    _extract_as_of_hint,
    _is_historical_truth,
    _is_superseded_truth,
    _normalize_retrieval_profile,
    _resolve_retrieval_profile,
    _retrieval_profile_status,
    _search_dx_metadata,
    _temporal_intent_drilldown_hint,
    _temporal_intent_mode,
    _temporal_query_action,
    _wake_dx_metadata,
    _with_temporal_intent_hint,
    tool_autopilot_search_tick,
    tool_file_context,
    tool_get_confirmed_rules,
    tool_get_observations,
    tool_get_project_profile,
    tool_get_skill,
    tool_get_task_handoffs,
    tool_record_context_outcome,
    tool_search_memory,
    tool_search_raw,
    tool_search_skills,
    tool_temporal_query,
    tool_timeline,
    tool_trace_relations,
    tool_wake,
)
from harness_mem.mcp.status_handlers import (  # noqa: E402, F401
    _bootstrap_status_workspace,
    _gather_project_status,
    tool_get_project_status,
)
from harness_mem.mcp.dream_handlers import (  # noqa: E402, F401
    _dream_budget_from_payload,
    _dream_run_summary,
    _highest_risk,
    _maintenance_summary,
    _resolve_project_for_dream,
    _resolve_project_root_for_dream,
    _run_command_to_payload,
    tool_dream_auto_tick,
    tool_dream_ledger,
    tool_dream_run,
    tool_undo_dream_item,
)
from harness_mem.mcp.distill_handlers import (  # noqa: E402, F401
    _checkpoint_distill_structural_projection,
    _distill_job_candidate_ids,
    _load_distill_exchange_windows,
    _load_distill_semantic_evidence,
    _recent_project_observations,
    _semantic_review_allows_promotion,
    tool_finalize_session_distill,
    tool_prepare_session_distill,
    tool_submit_distill_chunk,
)


def build_tool_handlers() -> dict[str, Callable[..., dict[str, Any]]]:
    """Return the MCP tool handler map keyed by public tool name."""
    return {
        "autopilot_search_tick": tool_autopilot_search_tick,
        "search_memory": tool_search_memory,
        "timeline": tool_timeline,
        "trace_relations": tool_trace_relations,
        "temporal_query": tool_temporal_query,
        "search_raw": tool_search_raw,
        "search_skills": tool_search_skills,
        "get_skill": tool_get_skill,
        "get_observations": tool_get_observations,
        "get_task_handoffs": tool_get_task_handoffs,
        "get_confirmed_rules": tool_get_confirmed_rules,
        "get_project_profile": tool_get_project_profile,
        "file_context": tool_file_context,
        "get_project_status": tool_get_project_status,
        "set_active_project": tool_set_active_project,
        "wake": tool_wake,
        "ingest_sessions": tool_ingest_sessions,
        "prepare_session_distill": tool_prepare_session_distill,
        "submit_distill_chunk": tool_submit_distill_chunk,
        "finalize_session_distill": tool_finalize_session_distill,
        "dream_ledger": tool_dream_ledger,
        "dream_run": tool_dream_run,
        "dream_auto_tick": tool_dream_auto_tick,
        "undo_dream_item": tool_undo_dream_item,
        "list_candidates": tool_list_candidates,
        "get_candidate_detail": tool_get_candidate_detail,
        "auto_review_candidates": tool_auto_review_candidates,
        "govern_memory": tool_govern_memory,
        "suggest_supersede": tool_suggest_supersede,
        "confirm_supersede": tool_confirm_supersede,
        "reject_supersede": tool_reject_supersede,
        "suggest_correction": tool_suggest_correction,
        "record_context_outcome": tool_record_context_outcome,
        "create_rule_candidate": tool_create_rule_candidate,
        "confirm_rule": tool_confirm_rule,
        "reject_rule": tool_reject_rule,
        "suggest_rule": tool_suggest_rule,
        "suggest_memory_entry": tool_suggest_memory_entry,
        "confirm_memory_entry": tool_confirm_memory_entry,
        "reject_memory_entry": tool_reject_memory_entry,
        "suggest_relation_fact": tool_suggest_relation_fact,
        "confirm_relation_fact": tool_confirm_relation_fact,
        "reject_relation_fact": tool_reject_relation_fact,
        "create_task_handoff": tool_create_task_handoff,
    }
