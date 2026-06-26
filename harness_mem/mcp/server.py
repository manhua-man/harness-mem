#!/usr/bin/env python3
"""
harness-mem MCP Server — structured memory access for AI agents
=================================================================
Install: claude mcp add harness-mem -- python -m harness_mem.mcp.server

Tools:
  search_memory          — search structured + verbatim memory
  timeline               — observation timeline
  get_observations      — list observations for a session
  get_task_handoffs     — recent task handoffs
  get_confirmed_rules   — confirmed rules for a project
  get_project_profile   — project profile
  get_project_status    — current project memory status and active project
  ingest_sessions       — project-scoped environment-aware session ingest
  prepare_session_distill — one-shot ingest + evidence packet for AI distill
  list_candidates       — pending/accepted/rejected review candidates
  auto_review_candidates — heuristic auto-confirm / auto-reject pass (preview or apply)
  suggest_correction    — one-shot rule replacement (new rule + supersede chain)
  create_rule_candidate — create a rule candidate
  confirm_rule          — promote candidate to confirmed rule

Future split note (do not split ad-hoc):
  This file currently sits at ~1550 lines / 33 tools after pulling out
  serializers (commit 0ec616d) and tool schemas (this commit). The
  remaining content is now mostly tool function bodies, the JSON-RPC
  handler, and stdio plumbing — readable as one file. The natural split
  axes for the next round are:

      mcp/
        server.py        — JSON-RPC handler, stdio plumbing, TOOLS factory
                           call, main loop. Stays small.
        backend.py       — _get_backend / set_backend_override singleton.
                           Public contract: re-export set_backend_override
                           from server.py if moved.
        serializers.py   — already extracted (0ec616d). Owns
                           _serialize_rule_candidate / _serialize_memory_
                           entry_candidate / _isoformat etc.
        tool_specs.py    — already extracted (this commit). Owns ToolSpec
                           typed dict + the schema registry. Handlers stay
                           in server.py and are passed in via build_tools.
        tools/
          read.py        — search_memory / timeline / trace_relations /
                           search_raw / search_skills / get_*
          ingest.py      — ingest_sessions / prepare_session_distill /
                           list_candidates / auto_review_candidates
          review.py      — confirm_* / reject_*
          suggest.py     — suggest_* / create_rule_candidate /
                           suggest_correction / create_task_handoff

  Reasons NOT to do the tools/ split today:
   1. set_backend_override is a public override hook; moving its module
      requires a re-export shim and adds complexity without runtime benefit.
   2. _REAL_STDOUT_FD redirection lives at module-import time in this
      file. Splitting risks ordering bugs in stdio protection.
   3. No user-facing pain point drives the split — it's pure long-term
      maintainability and should be handled as a coordinated refactor.

  When the file crosses ~2000 lines again, or when adding a new tool
  category forces a 5th cluster, split the MCP server into
  read/ingest/review/suggest modules as a coordinated PR.
"""

import os
import sys

# --- MCP stdio protection -----------------------------------------------
# Redirect stdout → stderr before heavy imports so that any stray print()
# statements from dependencies never corrupt the JSON-RPC stream on stdout.
_REAL_STDOUT_FD = None
_REAL_STDOUT_ENCODING = sys.stdout.encoding or "utf-8"
_REAL_STDOUT_ERRORS = sys.stdout.errors or "replace"
try:
    _REAL_STDOUT_FD = os.dup(1)
    os.dup2(2, 1)
except (OSError, AttributeError):
    pass
sys.stdout = sys.stderr

import contextlib  # noqa: E402
import io  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402
import re  # noqa: E402
import time  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Literal, cast  # noqa: E402

from harness_mem import __version__ as _HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.commands.auto_review import auto_review_candidates  # noqa: E402
from harness_mem.commands.doctor import health_summary  # noqa: E402
from harness_mem.commands.dream import (  # noqa: E402
    dream_auto_tick,
    dream_once,
    latest_dream_ledger,
    undo_dream_item,
)
from harness_mem.file_context import build_file_context  # noqa: E402
from harness_mem.config.errors import ConfigError  # noqa: E402
from harness_mem.config.merge import load_merged_config  # noqa: E402
from harness_mem.commands.ingest import cmd_ingest  # noqa: E402
from harness_mem.commands.metabolism_pass import select_metabolism_pass  # noqa: E402
from harness_mem.event_log import (  # noqa: E402
    StateEventType,
    append_state_event,
)
from harness_mem.recall import (  # noqa: E402
    build_search_recall_result,
    build_trace_recall_result,
)
from harness_mem.retrieval_signals import record_retrieval_signal  # noqa: E402
from harness_mem.commands.support import (  # noqa: E402
    SUPPORTED_INGEST_CLIENTS,
    find_project_root,
    get_active_project,
    normalize_client_name,
    resolve_ingest_client,
    set_active_project,
)
from harness_mem.commands.replay_window import (  # noqa: E402
    ReplayBudget,
    ReplayWindow,
    select_replay_window,
)
from harness_mem.commands.wake import (  # noqa: E402
    DEFAULT_SKILL_HINT_LIMIT,
    build_wake_snapshot,
    cmd_wake_up,
)
from harness_mem.task_context_runtime import orchestrate_task_context  # noqa: E402
from harness_mem.core.schemas import (  # noqa: E402
    ProceduralCandidate,
    SkillPromotionCandidate,
    SkillRevisionSuggestionCandidate,
    SupersedeCandidate,
)
from harness_mem.core.schemas.metabolism_run import MetabolismRun  # noqa: E402
from harness_mem.core.schemas.project_profile import ProjectProfile  # noqa: E402
from harness_mem.core.schemas.skill_promotion_candidate import PromotionScope  # noqa: E402
from harness_mem.core.schemas.skill_revision_suggestion_candidate import (  # noqa: E402
    RevisionTrigger,
)
from harness_mem.core.schemas.skill_deprecation_suggestion_candidate import (  # noqa: E402
    DeprecationTrigger,
    SkillDeprecationSuggestionCandidate,
)
from harness_mem.guided_flow import (  # noqa: E402
    build_guided_flow,
    guided_flow_drilldown_hint,
)
from harness_mem.knowledge_cache import (  # noqa: E402
    COMPACT_RENDERER_NAME,
    knowledge_cache_health,
    load_compact_wake_payload,
    render_compact_wake_payload,
)
from harness_mem.read_api import (  # noqa: E402
    parse_relative_time_window,
    query_temporal_truth,
    regex_search_observations,
    search_skills,
    serialize_memory_entry_search_result,
    serialize_observation,
    serialize_observation_search_result,
    serialize_relation_path,
    serialize_regex_observation_match,
    serialize_relation_fact_search_result,
    serialize_skill,
    serialize_temporal_query_result,
    serialize_timeline_observation,
    timeline_observations,
    trace_relation_paths,
)
from harness_mem.runtime_cost import (  # noqa: E402
    cost_budget_policy,
    observe_mcp_surface_cost,
    surface_cost_report,
)
from harness_mem.runtime_health import runtime_health_report  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.storage.local_project_profile_store import (  # noqa: E402
    LocalProjectProfileStore,
)
from harness_mem.storage.local_structured_store import LocalStructuredStore  # noqa: E402
from harness_mem.version import runtime_version_payload  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("harness_mem_mcp")

DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"
McpToolProfile = Literal[
    "core-read",
    "minimal",
    "distill-suggest",
    "review-write",
    "maintenance",
    "labs",
    "full",
]

_METABOLISM_PREVIEW_DOCTOR_POINTER = (
    "Run `harness-mem doctor` to inspect local data directory, "
    "signal store, and project context."
)

# Singleton backend — initialized once per MCP server process lifetime.
_backend: LocalMemoryBackend | None = None


def _get_backend() -> LocalMemoryBackend:
    global _backend
    if _backend is None:
        _backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        # Synchronous init via asyncio.run since MCP handlers are sync.
        asyncio.run(_backend.init())
    return _backend


def set_backend_override(backend: LocalMemoryBackend | None) -> None:
    """Override the singleton backend (used by tests to inject tmp_path backend)."""
    global _backend
    _backend = backend


def _observer_data_dir() -> Path:
    """Return the data dir cost observer should use without forcing backend init."""
    if _backend is not None:
        return _backend.data_dir
    return DEFAULT_DATA_DIR


def _cost_surface_budgets(project_name: str | None) -> dict[str, int] | None:
    """Load project cost budgets when a project root/config can be resolved."""
    if not project_name:
        return None
    root = find_project_root(project_name)
    if root is None:
        return None
    try:
        cfg = load_merged_config(str(root))
    except ConfigError:
        return None
    return {
        "wake": cfg.cost_budget_wake_tokens,
        "search": cfg.cost_budget_search_tokens,
        "file_context": cfg.cost_budget_file_context_tokens,
        "wiki": cfg.cost_budget_wiki_tokens,
        "dream": cfg.cost_budget_dream_tokens,
        "distill": cfg.cost_budget_distill_tokens,
    }


def _project_name_for_cost(
    arguments: dict[str, Any],
    result: dict[str, Any] | Any,
) -> str | None:
    value = arguments.get("project_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(result, dict):
        result_value = result.get("project_name")
        if isinstance(result_value, str) and result_value.strip():
            return result_value.strip()
    return None


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
        logger.exception("Failed to append state audit event for %s/%s", target_kind, target_id)
        return None


# =============================================================================
# READ TOOLS
# =============================================================================


VALID_MEMORY_TYPES: frozenset[str] = frozenset({"episodic", "semantic", "procedural"})
VALID_CONTEXT_OUTCOMES: frozenset[str] = frozenset(
    {"used", "ignored", "misleading"}
)
CONTEXT_OUTCOME_VALUES: dict[str, float] = {
    "used": 1.0,
    "ignored": 0.0,
    "misleading": -1.0,
}
VALID_MAINTENANCE_PROFILES: frozenset[str] = frozenset(
    {"weekly-dream", "post-distill-metabolism"}
)
MaintenanceProfile = Literal["weekly-dream", "post-distill-metabolism"]
VALID_RETRIEVAL_PROFILES: frozenset[str] = frozenset({"light", "quality"})
RetrievalProfile = Literal["light", "quality"]


def _action(label: str, surface: str, reason: str) -> dict[str, str]:
    return {"label": label, "surface": surface, "reason": reason}


_AS_OF_TERMS: tuple[str, ...] = (
    "as of",
    "at the time",
    "back then",
    "当时",
    "那时",
)
_HISTORY_TERMS: tuple[str, ...] = (
    "previous",
    "previously",
    "formerly",
    "legacy",
    "old",
    "history",
    "historical",
    "before",
    "以前",
    "之前",
    "历史",
    "过去",
    "旧",
)
_DATE_PATTERN = re.compile(r"\b(20\d{2}-\d{2}-\d{2})(?:[T ][0-2]\d:[0-5]\d(?::[0-5]\d)?)?\b")


def _temporal_intent_mode(query: str | None) -> Literal["as_of", "history"] | None:
    normalized = (query or "").strip().lower()
    if not normalized:
        return None
    if any(term in normalized for term in _AS_OF_TERMS):
        return "as_of"
    if _DATE_PATTERN.search(normalized):
        return "as_of"
    if any(term in normalized for term in _HISTORY_TERMS):
        return "history"
    return None


def _extract_as_of_hint(query: str | None) -> str | None:
    match = _DATE_PATTERN.search(query or "")
    if not match:
        return None
    try:
        return datetime.fromisoformat(match.group(1)).replace(tzinfo=timezone.utc).isoformat()
    except ValueError:
        return None


def _temporal_query_action(mode: str) -> dict[str, str]:
    return _action(
        "inspect_temporal_truth",
        "temporal_query",
        (
            f"Query looks time-scoped; use temporal_query mode={mode} before "
            "treating old-state answers as current truth."
        ),
    )


def _temporal_intent_drilldown_hint(
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> dict[str, Any] | None:
    if mode is None:
        return None
    as_of = _extract_as_of_hint(query) if mode == "as_of" else None
    arguments: dict[str, Any] = {
        "project_name": project_name,
        "query": query,
        "mode": mode,
        "limit": 20,
    }
    if mode == "as_of":
        arguments["as_of"] = as_of
        arguments["requires_as_of"] = as_of is None
    return {
        "source_id": None,
        "source_kind": "temporal_intent",
        "read_surface": "mcp.temporal_query",
        "tool": "temporal_query",
        "arguments": arguments,
        "why": (
            "The query appears to ask about historical or as-of truth. "
            "Use temporal_query and preserve its abstention_reason if no evidence matches."
        ),
        "abstention": "no_evidence",
    }


def _with_temporal_intent_hint(
    hints: list[dict[str, Any]],
    *,
    project_name: str | None,
    query: str,
    mode: Literal["as_of", "history"] | None,
) -> list[dict[str, Any]]:
    hint = _temporal_intent_drilldown_hint(
        project_name=project_name,
        query=query,
        mode=mode,
    )
    if hint is None:
        return list(hints)
    return [*hints, hint]


def _is_historical_truth(record: object) -> bool:
    valid_to = getattr(record, "valid_to", None)
    if not isinstance(valid_to, datetime):
        return False
    return valid_to <= datetime.now(timezone.utc)


def _is_superseded_truth(record: object) -> bool:
    return _is_historical_truth(record) and bool(list(getattr(record, "superseded_by", []) or []))


def _maintenance_profile_definition(name: str) -> dict[str, Any]:
    definitions: dict[str, dict[str, Any]] = {
        "weekly-dream": {
            "name": "weekly-dream",
            "label": "Weekly Dream",
            "enabled_by_default": False,
            "risk_level": "low",
            "surfaces": ["dream_ledger", "dream_run", "undo_dream_item"],
            "trigger": "manual_or_opt_in_scheduler",
            "summary": (
                "Preview ledger, run one dream pass, then use undo_dream_item "
                "if an applied ledger item needs reversal."
            ),
        },
        "post-distill-metabolism": {
            "name": "post-distill-metabolism",
            "label": "Post-distill Metabolism",
            "enabled_by_default": False,
            "risk_level": "low",
            "surfaces": ["metabolism_preview", "metabolism_run", "list_candidates"],
            "trigger": "manual_after_distill",
            "summary": (
                "Preview replay evidence, write pending maintenance suggestions, "
                "then review candidates explicitly."
            ),
        },
    }
    return dict(definitions[name])


def _maintenance_profile_dry_run(
    name: str,
    counts: dict[str, Any],
) -> dict[str, Any]:
    definition = _maintenance_profile_definition(name)
    generated_cache = counts.get("generated_cache", {})
    temporal_summary = counts.get("temporal_summary", {})
    pending = int(counts.get("pending_candidate_count", 0) or 0)
    stale_sources = int(generated_cache.get("stale_source_count", 0) or 0)
    invalid_claims = int(generated_cache.get("invalid_claim_count", 0) or 0)
    historical = int(temporal_summary.get("historical_total", 0) or 0)
    if name == "weekly-dream":
        candidate_counts = {
            "pending_candidates": pending,
            "stale_sources": stale_sources,
            "historical_truths": historical,
        }
        has_work = any(candidate_counts.values())
        summary = _maintenance_summary(
            candidate_counts=candidate_counts,
            risk_level="low" if has_work else "none",
            auto_applied=False,
            needs_human_review=pending > 0,
            undo_available=False,
            message=(
                "Dry-run only: weekly-dream would inspect dream ledger and run one "
                "explicit dream pass with undo metadata."
                if has_work
                else "Dry-run only: no obvious weekly-dream maintenance work is queued."
            ),
        )
    else:
        candidate_counts = {
            "pending_candidates": pending,
            "stale_sources": stale_sources,
            "invalid_generated_claims": invalid_claims,
        }
        has_work = any(candidate_counts.values())
        summary = _maintenance_summary(
            candidate_counts=candidate_counts,
            risk_level="low" if has_work else "none",
            auto_applied=False,
            needs_human_review=has_work,
            undo_available=False,
            message=(
                "Dry-run only: post-distill-metabolism would preview replay evidence "
                "and write review candidates only if explicitly run."
                if has_work
                else "Dry-run only: project appears clean for post-distill metabolism."
            ),
        )
    return {
        **definition,
        "dry_run": summary["maintenance_summary"],
    }


def _suggest_maintenance_profile(
    counts: dict[str, Any],
    active_profile: str | None,
) -> str | None:
    if active_profile:
        return active_profile
    generated_cache = counts.get("generated_cache", {})
    pending = int(counts.get("pending_candidate_count", 0) or 0)
    stale = int(generated_cache.get("stale_source_count", 0) or 0)
    invalid = int(generated_cache.get("invalid_claim_count", 0) or 0)
    if pending or stale or invalid:
        return "post-distill-metabolism"
    if int(counts.get("memory_entry_count", 0) or 0):
        return "weekly-dream"
    return None


def _normalize_retrieval_profile(value: object) -> RetrievalProfile | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_RETRIEVAL_PROFILES:
        return cast(RetrievalProfile, profile)
    return None


async def _resolve_retrieval_profile(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    requested: str | None,
) -> dict[str, Any]:
    if requested is not None:
        normalized = _normalize_retrieval_profile(requested)
        if normalized is None:
            valid = ", ".join(sorted(VALID_RETRIEVAL_PROFILES))
            return {
                "success": False,
                "error": f"retrieval_profile must be one of: {valid}",
            }
        return {
            "success": True,
            "active": normalized,
            "configured": None,
            "source": "argument",
        }

    configured: RetrievalProfile | None = None
    if project_name:
        from harness_mem.commands import support as _support

        profile = await LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name)
        if profile is not None:
            configured = _normalize_retrieval_profile(profile.retrieval_profile)

    return {
        "success": True,
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
    }


def _retrieval_profile_status(
    *,
    active_profile: str | None,
    memory_entry_count: int,
) -> dict[str, Any]:
    configured = _normalize_retrieval_profile(active_profile)
    suggested = None if configured else ("quality" if memory_entry_count > 0 else None)
    return {
        "active": configured or "light",
        "configured": configured,
        "source": "project_profile" if configured else "default",
        "suggested": suggested,
        "available": [
            {
                "name": "light",
                "default": True,
                "reranker": "noop",
                "query_rewriting_enabled": False,
                "multi_query_enabled": False,
                "hyde_enabled": False,
                "summary": "Default lightweight retrieval path.",
            },
            {
                "name": "quality",
                "default": False,
                "reranker": "noop",
                "query_rewriting_enabled": True,
                "multi_query_enabled": True,
                "hyde_enabled": False,
                "summary": (
                    "Opt-in deterministic query rewrite/fanout trace; no "
                    "heavy reranker, HyDE, ANN, Tantivy, or LanceDB is enabled."
                ),
            },
        ],
        "auto_enabled": False,
        "default_profile": "light",
        "claim_boundary": (
            "retrieval_profile=quality is component-level retrieval behavior; "
            "it does not unlock broad_memory_answer_quality"
        ),
    }


def _search_dx_metadata(
    *,
    memory_entry_count: int,
    relation_fact_count: int,
    observation_count: int,
    effective_mode: str,
    fallback_reason: str | None,
    project_name: str | None,
    query: str,
    include_history: bool,
    deep_recall: bool,
    temporal_intent_mode: Literal["as_of", "history"] | None,
) -> dict[str, Any]:
    total = memory_entry_count + relation_fact_count + observation_count
    next_actions: list[dict[str, str]] = []
    if total == 0:
        next_actions.append(
            _action(
                "distill_recent_sessions",
                "/hm:distill",
                "No confirmed memory matched this query; ingest/distill before relying on search.",
            )
        )
        next_actions.append(
            _action(
                "search_raw_evidence",
                "search_raw",
                "Use raw evidence search if you need exact transcript snippets before distill.",
            )
        )
    else:
        next_actions.append(
            _action(
                "inspect_sources",
                "drilldown_hints",
                "Use returned source ids and read surfaces when a result needs proof.",
            )
        )
        next_actions.append(
            _action(
                "record_outcome",
                "record_context_outcome",
                "After the task, record used/ignored/misleading so future opt-in ranking is explainable.",
            )
        )
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "health_summary",
                "Search degraded to a fallback path; inspect runtime health before claiming quality.",
            )
        )
    if include_history or deep_recall:
        next_actions.append(
            _action(
                "inspect_temporal_chain",
                "temporal_query",
                "History-capable search was requested; use temporal_query for current/history/as_of proof.",
            )
        )
    elif temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))

    project_fragment = f" for {project_name}" if project_name else ""
    why = (
        f"Returned {memory_entry_count} memory entries, {relation_fact_count} "
        f"relation facts, and {observation_count} observations{project_fragment} "
        f"using {effective_mode} mode for query {query!r}."
    )
    if include_history:
        why += " Historical structured truth was included because include_history=true."
    elif deep_recall:
        why += " Historical structured truth may be included because deep_recall=true."
    elif temporal_intent_mode:
        why += " Query appears temporal; current results remain current-only unless history is requested."
    return {
        "why_this_result": why,
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


def _wake_dx_metadata(
    *,
    success: bool,
    renderer: str,
    fallback_reason: str | None,
    source_coverage: dict[str, int] | None,
    temporal_intent_mode: Literal["as_of", "history"] | None = None,
) -> dict[str, Any]:
    if not success:
        return {
            "why_this_result": "Wake did not complete, so no context packet was generated.",
            "next_actions": [
                _action(
                    "check_status",
                    "get_project_status",
                    "Status explains whether the project is missing ingest, review, or local setup.",
                )
            ],
            "degraded_reason": fallback_reason or "wake_failed",
            "drilldown_hints": [],
        }
    coverage = source_coverage or {}
    next_actions = [
        _action(
            "answer_with_sources",
            "supporting_evidence",
            "Use the returned evidence ids when the task needs proof.",
        ),
        _action(
            "search_specific_gap",
            "/hm:search",
            "If the wake packet is too broad, search for the exact subsystem or decision.",
        ),
    ]
    if fallback_reason:
        next_actions.append(
            _action(
                "check_index_health",
                "health_summary",
                "Wake used a fallback search path; inspect health before release claims.",
            )
        )
    if temporal_intent_mode:
        next_actions.append(_temporal_query_action(temporal_intent_mode))
    return {
        "why_this_result": (
            f"Generated {renderer} wake context from project profile, rules, "
            f"handoffs, and task-aware retrieval; source coverage: {coverage}."
        ),
        "next_actions": next_actions,
        "degraded_reason": fallback_reason,
    }


def _status_dx_metadata(
    counts: dict[str, Any],
    triage: dict[str, Any],
    *,
    project_name: str,
) -> dict[str, Any]:
    phase = str(triage.get("phase") or "unknown")
    pending = int(counts.get("pending_candidate_count", 0) or 0)
    next_actions: list[dict[str, str]] = []
    suggested = triage.get("suggested_slash")
    if suggested:
        next_actions.append(
            _action(
                "run_suggested_entry",
                str(suggested),
                str(triage.get("reason") or "Recommended next daily-flow step."),
            )
        )
    if pending > 0:
        next_actions.append(
            _action(
                "review_pending_when_needed",
                "/hm:review",
                "Pending candidates exist; review only when correcting or rechecking candidates.",
            )
        )
    if counts.get("observation_count", 0) and counts.get("memory_entry_count", 0):
        next_actions.append(
            _action(
                "search_before_task",
                '/hm:search "<topic>"',
                "Search narrows the wake context to the current task.",
            )
        )
    temporal_summary = counts.get("temporal_summary", {})
    historical_total = int(temporal_summary.get("historical_total", 0) or 0)
    superseded_total = int(temporal_summary.get("superseded_total", 0) or 0)
    if historical_total:
        next_actions.append(
            _action(
                "inspect_temporal_history",
                "temporal_query",
                "This project has historical truth; use temporal_query when asking old-state questions.",
            )
        )
    maintenance_profiles = counts.get("maintenance_profiles", {})
    suggested_profile = maintenance_profiles.get("suggested")
    if suggested_profile:
        next_actions.append(
            _action(
                "preview_maintenance_profile",
                "get_project_status",
                (
                    f"Review the {suggested_profile} dry-run summary before "
                    "explicitly running maintenance surfaces."
                ),
            )
        )
    retrieval_profiles = counts.get("retrieval_profiles", {})
    suggested_retrieval_profile = retrieval_profiles.get("suggested")
    if suggested_retrieval_profile:
        next_actions.append(
            _action(
                "consider_retrieval_quality_profile",
                "update_project_profile",
                (
                    "retrieval_profile=quality is available as an opt-in "
                    "component profile; status only suggests it and does not "
                    "enable it automatically."
                ),
            )
        )
    degraded_reason = None
    if phase == "needs-distill":
        degraded_reason = "no_observations_ingested"
    elif counts.get("retrieval_health", {}).get("degraded"):
        degraded_reason = "retrieval_health_degraded"
    return {
        "why_this_result": (
            f"Project is in phase {phase}: {counts.get('observation_count', 0)} "
            f"observations, {counts.get('memory_entry_count', 0)} memory entries, "
            f"{pending} pending candidates."
        ),
        "next_actions": next_actions,
        "degraded_reason": degraded_reason,
        "drilldown_hints": [
            _action(
                "status_counts",
                "get_project_status",
                "Use counts to decide between wake, search, distill, and review.",
            )
        ]
        + (
            [
                {
                    "source_id": None,
                    "source_kind": "temporal_summary",
                    "read_surface": "mcp.temporal_query",
                    "tool": "temporal_query",
                    "arguments": {
                        "project_name": project_name,
                        "mode": "history",
                        "limit": 20,
                    },
                    "why": (
                        f"Project has {historical_total} historical truth records "
                        f"({superseded_total} superseded)."
                    ),
                }
            ]
            if historical_total
            else []
        ),
    }


def tool_search_memory(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    mode: str = "auto",
    memory_type: list[str] | None = None,
    include_history: bool = False,
    deep_recall: bool = False,
    retrieval_profile: str | None = None,
    task: str | None = None,
    budget_tokens: int = 6000,
) -> dict:
    """Search structured memory entries + verbatim observations.

    v1.6.1: ``memory_type`` is an optional list filter ({episodic, semantic,
    procedural}). Empty / None disables the filter; values are OR-ed.
    """
    backend = _get_backend()

    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    if memory_type:
        normalized = [str(value).strip().lower() for value in memory_type]
        invalid = [value for value in normalized if value not in VALID_MEMORY_TYPES]
        if invalid:
            return {
                "success": False,
                "error": (
                    "unknown memory_type: " + ", ".join(sorted(set(invalid)))
                    + ". Valid: episodic | semantic | procedural."
                ),
            }
        memory_type = normalized
    else:
        memory_type = None

    profile_info = asyncio.run(
        _resolve_retrieval_profile(
            backend,
            project_name=project_name if scope == "project" else None,
            requested=retrieval_profile,
        )
    )
    if not profile_info["success"]:
        return profile_info

    parsed_time = parse_relative_time_window(query)
    runtime = asyncio.run(
        orchestrate_task_context(
            backend,
            query=parsed_time.query,
            project_name=project_name,
            scope=scope,
            mode=mode,
            memory_type=memory_type,
            include_history=include_history,
            time_window=parsed_time.time_window,
            deep_recall=deep_recall,
            current_task=task,
            budget_tokens=budget_tokens,
            auto_deep_recall=True,
            retrieval_profile=profile_info["active"],
        )
    )
    response = runtime.response
    entries = runtime.entries
    obs_list = runtime.observations
    relation_facts = runtime.relation_facts
    tech_stack_by_project = runtime.tech_stack_by_project
    effective_mode = response.effective_mode
    fallback_reason = response.fallback_metadata.get("fallback_reason")
    temporal_intent = _temporal_intent_mode(query)
    drilldown_hints = _with_temporal_intent_hint(
        response.drilldown_hints,
        project_name=project_name,
        query=query,
        mode=temporal_intent,
    )
    context_payload: dict[str, Any] = {}
    if runtime.context_plan is not None:
        context_plan = runtime.context_plan
        context_plan_payload = context_plan.to_dict()
        context_plan_payload["drilldown_hints"] = drilldown_hints
        context_plan_payload["iterative_retrieval_trace"]["retrieval_quality"] = (
            response.retrieval_quality
        )
        context_payload = {
            "context_sufficiency": context_plan.context_sufficiency.to_dict(),
            "retrieval_plan": context_plan.retrieval_plan.to_dict(),
            "context_plan": context_plan_payload,
            "iterative_retrieval_trace": (
                context_plan.iterative_retrieval_trace.to_dict()
            ),
            "wake_packet": context_plan.wake_packet.to_dict(),
        }
    dx_metadata = _search_dx_metadata(
        memory_entry_count=len(entries),
        relation_fact_count=len(relation_facts),
        observation_count=len(obs_list),
        effective_mode=effective_mode,
        fallback_reason=fallback_reason,
        project_name=project_name,
        query=query,
        include_history=include_history,
        deep_recall=deep_recall,
        temporal_intent_mode=temporal_intent,
    )
    serialized_memory_entries = [
        serialize_memory_entry_search_result(entry, mode, tech_stack_by_project)
        for entry in entries
    ]
    serialized_relation_facts = [
        serialize_relation_fact_search_result(fact, tech_stack_by_project)
        for fact in relation_facts
    ]
    serialized_observations = [
        serialize_observation_search_result(
            observation,
            mode,
            query,
            tech_stack_by_project,
        )
        for observation in obs_list
    ]
    recall_result = build_search_recall_result(
        project_name=project_name,
        query=query,
        effective_query=parsed_time.query,
        requested_mode=mode,
        effective_mode=effective_mode,
        memory_entries=serialized_memory_entries,
        relation_facts=serialized_relation_facts,
        observations=serialized_observations,
        drilldown_hints=drilldown_hints,
        context=context_payload or None,
        answer_ready_context=runtime.answer_ready_context,
        warnings=[fallback_reason] if fallback_reason else [],
        effort="dynamic",
    )

    return {
        "project_name": project_name,
        "query": query,
        "effective_query": parsed_time.query,
        "scope": scope,
        "requested_mode": mode,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "include_history": include_history,
        "deep_recall": deep_recall,
        "effective_deep_recall": runtime.effective_deep_recall,
        "orchestration_actions": runtime.orchestration_actions,
        "retrieval_profile": {
            "active": profile_info["active"],
            "configured": profile_info["configured"],
            "source": profile_info["source"],
        },
        "retrieval_quality": {
            **response.retrieval_quality,
            "active": profile_info["active"],
            "source": profile_info["source"],
            "configured": profile_info["configured"],
            "can_disable": True,
        },
        "time_window": (
            {
                "start": parsed_time.start.isoformat() if parsed_time.start else None,
                "end": parsed_time.end.isoformat() if parsed_time.end else None,
                "phrase": parsed_time.phrase,
            }
            if parsed_time.time_window
            else None
        ),
        "memory_entries": serialized_memory_entries,
        "relation_facts": serialized_relation_facts,
        "observations": serialized_observations,
        "memory_entry_count": len(entries),
        "relation_fact_count": len(relation_facts),
        "observation_count": len(obs_list),
        "backend_budget": response.budget,
        "backend_truncation": response.truncation,
        "source_coverage": response.source_coverage,
        "drilldown_hints": drilldown_hints,
        **dx_metadata,
        "supporting_evidence": runtime.supporting_evidence,
        "answer_ready_context": runtime.answer_ready_context,
        "recall": recall_result.to_dict(),
        **context_payload,
    }


def tool_record_context_outcome(
    project_name: str,
    surface: str,
    source_ids: list[str],
    outcome: str,
    reason: str | None = None,
) -> dict:
    """Record whether surfaced context helped the task without mutating truth."""
    resolved_project = (project_name or "").strip()
    if not resolved_project:
        return {
            "success": False,
            "error": "project_name must not be empty",
            "truth_mutated": False,
        }
    normalized_surface = (surface or "").strip()
    if not normalized_surface:
        return {
            "success": False,
            "error": "surface must not be empty",
            "truth_mutated": False,
        }
    normalized_outcome = (outcome or "").strip().lower()
    if normalized_outcome not in VALID_CONTEXT_OUTCOMES:
        return {
            "success": False,
            "error": "outcome must be one of: used, ignored, misleading",
            "truth_mutated": False,
        }
    cleaned_source_ids = [
        str(source_id).strip()
        for source_id in (source_ids or [])
        if str(source_id).strip()
    ]
    if not cleaned_source_ids:
        return {
            "success": False,
            "error": "source_ids must contain at least one id",
            "truth_mutated": False,
        }

    backend = _get_backend()
    signal_ids: list[str] = []
    failed_source_ids: list[str] = []
    context = {
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "reason": (reason or "").strip()[:500] or None,
    }
    value = CONTEXT_OUTCOME_VALUES[normalized_outcome]
    for source_id in cleaned_source_ids:
        signal = asyncio.run(
            record_retrieval_signal(
                backend,
                project_name=resolved_project,
                signal_type="context_outcome",
                target_kind="context_source",
                target_id=source_id,
                value=value,
                context=context,
            )
        )
        if signal is None:
            failed_source_ids.append(source_id)
        else:
            signal_ids.append(signal.id)

    return {
        "success": not failed_source_ids,
        "project_name": resolved_project,
        "surface": normalized_surface,
        "outcome": normalized_outcome,
        "recorded_count": len(signal_ids),
        "failed_count": len(failed_source_ids),
        "signal_ids": signal_ids,
        "failed_source_ids": failed_source_ids,
        "truth_mutated": False,
        "next_actions": [
            _action(
                "search_again",
                "/hm:search",
                "Opt-in projects can use outcome signals as a small explainable ranking hint.",
            )
        ],
        "why_this_result": (
            f"Recorded {len(signal_ids)} context outcome signals; confirmed truth was not changed."
        ),
        "degraded_reason": "signal_write_failed" if failed_source_ids else None,
    }
def tool_timeline(project_name: str, limit: int = 50) -> dict:
    """Return chronological observation timeline for a project."""
    backend = _get_backend()
    obs_list = asyncio.run(timeline_observations(backend, project_name=project_name, limit=limit))

    return {
        "project_name": project_name,
        "limit": limit,
        "observations": [serialize_timeline_observation(observation) for observation in obs_list],
        "count": len(obs_list),
    }


def tool_trace_relations(
    project_name: str,
    source_entity: str,
    relation_type: str | None = None,
    max_depth: int = 2,
    limit: int = 10,
    min_confidence: float = 0.0,
    include_history: bool = False,
) -> dict:
    """Return bounded relation paths starting at a source entity."""
    backend = _get_backend()
    try:
        paths = asyncio.run(
            trace_relation_paths(
                backend,
                project_name=project_name,
                source_entity=source_entity,
                relation_type=relation_type,
                max_depth=max_depth,
                limit=limit,
                min_confidence=min_confidence,
                include_history=include_history,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}

    serialized_paths = [serialize_relation_path(path) for path in paths]
    recall_result = build_trace_recall_result(
        project_name=project_name,
        source_entity=source_entity,
        relation_type=relation_type,
        paths=serialized_paths,
    )
    return {
        "success": True,
        "project_name": project_name,
        "source_entity": source_entity,
        "relation_type": relation_type,
        "max_depth": max_depth,
        "limit": limit,
        "include_history": include_history,
        "paths": serialized_paths,
        "path_count": len(paths),
        "recall": recall_result.to_dict(),
    }


def tool_temporal_query(
    project_name: str,
    query: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    truth_type: str | None = None,
    mode: str = "current",
    as_of: str | None = None,
    valid_from: str | None = None,
    valid_to: str | None = None,
    recorded_from: str | None = None,
    recorded_to: str | None = None,
    limit: int = 20,
    require_unique_current: bool = False,
) -> dict:
    """Query the v3.3 temporal read model without mutating truth."""
    if mode not in {"current", "history", "as_of"}:
        return {"success": False, "error": "mode must be one of: current, history, as_of"}
    if truth_type not in {None, "memory_entry", "relation_fact", "confirmed_rule"}:
        return {
            "success": False,
            "error": "truth_type must be one of: memory_entry, relation_fact, confirmed_rule",
        }
    parsed_as_of, error = _parse_optional_iso_datetime(as_of, "as_of")
    if error:
        return {"success": False, "error": error}
    if mode == "as_of" and parsed_as_of is None:
        return {"success": False, "error": "as_of is required when mode=as_of"}
    parsed_valid_from, error = _parse_optional_iso_datetime(valid_from, "valid_from")
    if error:
        return {"success": False, "error": error}
    parsed_valid_to, error = _parse_optional_iso_datetime(valid_to, "valid_to")
    if error:
        return {"success": False, "error": error}
    parsed_recorded_from, error = _parse_optional_iso_datetime(recorded_from, "recorded_from")
    if error:
        return {"success": False, "error": error}
    parsed_recorded_to, error = _parse_optional_iso_datetime(recorded_to, "recorded_to")
    if error:
        return {"success": False, "error": error}

    backend = _get_backend()
    result = asyncio.run(
        query_temporal_truth(
            backend,
            project_name=project_name,
            query=query,
            subject=subject,
            predicate=predicate,
            truth_type=truth_type,
            mode=mode,
            as_of=parsed_as_of,
            valid_range=(parsed_valid_from, parsed_valid_to),
            recorded_range=(parsed_recorded_from, parsed_recorded_to),
            limit=limit,
            require_unique_current=require_unique_current,
        )
    )
    payload = serialize_temporal_query_result(result)
    payload.update(
        {
            "project_name": project_name,
            "query": query,
            "subject": subject,
            "predicate": predicate,
            "truth_type": truth_type,
            "mode": mode,
            "as_of": parsed_as_of.isoformat() if parsed_as_of else None,
            "valid_range": {
                "start": parsed_valid_from.isoformat() if parsed_valid_from else None,
                "end": parsed_valid_to.isoformat() if parsed_valid_to else None,
            },
            "recorded_range": {
                "start": parsed_recorded_from.isoformat() if parsed_recorded_from else None,
                "end": parsed_recorded_to.isoformat() if parsed_recorded_to else None,
            },
        }
    )
    return payload


def _parse_optional_iso_datetime(value: str | None, field_name: str) -> tuple[datetime | None, str | None]:
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None, f"{field_name} must be an ISO datetime"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed, None


def tool_search_raw(
    pattern: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 20,
) -> dict:
    """Regex search raw observation evidence."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}

    backend = _get_backend()
    try:
        matches = asyncio.run(
            regex_search_observations(
                backend,
                project_name=project_name,
                pattern=pattern,
                scope=scope,
                limit=limit,
            )
        )
    except re.error as exc:
        return {"success": False, "error": f"invalid regex: {exc}"}

    return {
        "success": True,
        "project_name": project_name,
        "pattern": pattern,
        "scope": scope,
        "limit": limit,
        "matches": [serialize_regex_observation_match(match) for match in matches],
        "count": len(matches),
    }


def tool_search_skills(
    query: str,
    project_name: str | None = None,
    scope: str = "project",
    limit: int = 10,
    include_shared: bool = False,
    shared_scope: str = "exclude",
) -> dict:
    """Search confirmed procedural skills."""
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if scope == "project" and not project_name:
        return {"success": False, "error": "project_name is required when scope=project"}
    if shared_scope not in {"exclude", "include", "only"}:
        return {
            "success": False,
            "error": "shared_scope must be one of: exclude, include, only",
        }

    effective_shared_scope = shared_scope
    if include_shared and shared_scope == "exclude":
        effective_shared_scope = "include"

    backend = _get_backend()
    skills = asyncio.run(
        search_skills(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            limit=limit,
            shared_scope=effective_shared_scope,
        )
    )
    return {
        "success": True,
        "project_name": project_name,
        "query": query,
        "scope": scope,
        "include_shared": include_shared,
        "shared_scope": effective_shared_scope,
        "limit": limit,
        "skills": [serialize_skill(skill) for skill in skills],
        "count": len(skills),
    }


def tool_get_skill(skill_id: str) -> dict:
    """Return a full confirmed skill payload by id."""
    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.get_skill(skill_id))
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    return {
        "success": True,
        "skill": serialize_skill(skill),
    }


def tool_get_observations(project_name: str, session_id: str) -> dict:
    """List all observations for a given session."""
    backend = _get_backend()
    all_obs = asyncio.run(backend.verbatim_store.list(limit=10000))
    session_obs = [
        o
        for o in all_obs
        if o.session_id == session_id
        and o.metadata.get("project_name") == project_name
    ]

    return {
        "project_name": project_name,
        "session_id": session_id,
        "observations": [serialize_observation(observation) for observation in session_obs],
        "count": len(session_obs),
    }


def tool_get_task_handoffs(project_name: str, limit: int = 5) -> dict:
    """Return recent task handoffs for a project."""
    backend = _get_backend()
    handoffs = asyncio.run(
        backend.structured_store.get_latest_handoffs(project_name, limit=limit)
    )
    return {
        "project_name": project_name,
        "limit": limit,
        "handoffs": [
            {
                "id": h.id,
                "task_id": h.task_id,
                "summary": h.summary,
                "status": h.status,
                "next_steps": h.next_steps,
                "blockers": h.blockers,
                "last_activity": h.last_activity.isoformat() if h.last_activity else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "provenance": h.provenance,
            }
            for h in handoffs
        ],
        "count": len(handoffs),
    }


def tool_get_confirmed_rules(project_name: str, include_history: bool = False) -> dict:
    """Return all confirmed rules for a project."""
    backend = _get_backend()
    rules = asyncio.run(
        backend.structured_store.list_confirmed_rules(
            project_name,
            include_history=include_history,
        )
    )
    return {
        "project_name": project_name,
        "include_history": include_history,
        "rules": [
            {
                "id": r.id,
                "pattern": r.pattern,
                "trigger": r.trigger,
                "examples": r.examples,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "valid_from": r.valid_from.isoformat() if r.valid_from else None,
                "valid_to": r.valid_to.isoformat() if r.valid_to else None,
                "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                "supersedes": r.supersedes,
                "superseded_by": r.superseded_by,
                "is_historical": bool(r.valid_to and r.valid_to <= datetime.now(timezone.utc)),
                "tags": r.tags,
                "provenance": r.provenance,
            }
            for r in rules
        ],
        "count": len(rules),
    }


def tool_get_project_profile(project_name: str) -> dict:
    """Return the project profile for a project."""
    from harness_mem.commands import support as _support

    store = asyncio.run(LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name))
    if store is None:
        return {"project_name": project_name, "found": False}

    profile = store
    return {
        "found": True,
        "project_name": profile.project_name,
        "description": profile.description,
        "stacks": profile.stacks,
        "key_files": profile.key_files,
        "curated_doc_paths": profile.curated_doc_paths,
        "mcp_tool_profile": profile.mcp_tool_profile,
        "maintenance_profile": profile.maintenance_profile,
        "retrieval_profile": profile.retrieval_profile,
    }


def tool_file_context(
    path: str,
    project_name: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Return compact, source-attributed memory already associated with a path."""
    backend = _get_backend()
    try:
        result = asyncio.run(
            build_file_context(
                backend,
                project_name=project_name,
                path=path,
                project_root=project_root,
            )
        )
    except ValueError as exc:
        return {"success": False, "error": str(exc)}
    payload = result.to_dict()
    payload["success"] = True
    return payload


async def _gather_project_status(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    from harness_mem.commands import support as _support

    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    all_memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
        include_history=True,
    )
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=5)
    confirmed_rules = await backend.structured_store.list_confirmed_rules(project_name)
    all_confirmed_rules = await backend.structured_store.list_confirmed_rules(
        project_name,
        include_history=True,
    )
    all_relation_facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100000,
        include_history=True,
    )
    pending_rules = await backend.structured_store.list_rule_candidates(
        project_name,
        status="pending",
    )
    pending_entries = await backend.structured_store.list_memory_entries(
        project_name,
        status="pending",
        limit=100000,
    )
    pending_facts = await backend.structured_store.list_relation_facts(
        project_name,
        status="pending",
        limit=100000,
    )
    data_dir = _support.DEFAULT_DATA_DIR
    profile = await LocalProjectProfileStore(data_dir).get(project_name)
    knowledge_report = await knowledge_cache_health(
        backend,
        data_dir=data_dir,
        project_name=project_name,
        profile=profile,
        project_root=find_project_root(project_name),
    )
    runtime_report = await runtime_health_report(
        backend,
        data_dir=_observer_data_dir(),
        project_name=project_name,
        profile=profile,
        project_root=find_project_root(project_name),
        repo_root=Path(__file__).resolve().parents[2],
    )
    cost_report = surface_cost_report(
        _observer_data_dir(),
        project_name=project_name,
        days=7,
        limit=100,
        surface_budgets=_cost_surface_budgets(project_name),
    )
    active_maintenance_profile = profile.maintenance_profile if profile else None
    active_retrieval_profile = profile.retrieval_profile if profile else None
    suggested_maintenance_profile = _suggest_maintenance_profile(
        {
            "memory_entry_count": len(memory_entries),
            "pending_candidate_count": (
                len(pending_rules) + len(pending_entries) + len(pending_facts)
            ),
            "generated_cache": knowledge_report,
        },
        active_maintenance_profile,
    )
    return {
        "observation_count": len(project_observations),
        "memory_entry_count": len(memory_entries),
        "task_handoff_count": len(handoffs),
        "confirmed_rule_count": len(confirmed_rules),
        "pending_candidate_count": len(pending_rules) + len(pending_entries) + len(pending_facts),
        "temporal_summary": {
            "historical_memory_entry_count": sum(
                1 for entry in all_memory_entries if _is_historical_truth(entry)
            ),
            "historical_confirmed_rule_count": sum(
                1 for rule in all_confirmed_rules if _is_historical_truth(rule)
            ),
            "historical_relation_fact_count": sum(
                1 for fact in all_relation_facts if _is_historical_truth(fact)
            ),
            "historical_total": sum(
                1
                for record in [
                    *all_memory_entries,
                    *all_confirmed_rules,
                    *all_relation_facts,
                ]
                if _is_historical_truth(record)
            ),
            "superseded_total": sum(
                1
                for record in [
                    *all_memory_entries,
                    *all_confirmed_rules,
                    *all_relation_facts,
                ]
                if _is_superseded_truth(record)
            ),
        },
        "maintenance_profiles": {
            "active": active_maintenance_profile,
            "suggested": suggested_maintenance_profile,
            "available": [
                _maintenance_profile_definition(name)
                for name in sorted(VALID_MAINTENANCE_PROFILES)
            ],
            "dry_runs": {
                name: _maintenance_profile_dry_run(
                    name,
                    {
                        "memory_entry_count": len(memory_entries),
                        "pending_candidate_count": (
                            len(pending_rules)
                            + len(pending_entries)
                            + len(pending_facts)
                        ),
                        "generated_cache": knowledge_report,
                        "temporal_summary": {
                            "historical_total": sum(
                                1
                                for record in [
                                    *all_memory_entries,
                                    *all_confirmed_rules,
                                    *all_relation_facts,
                                ]
                                if _is_historical_truth(record)
                            ),
                        },
                    },
                )
                for name in sorted(VALID_MAINTENANCE_PROFILES)
            },
        },
        "retrieval_profiles": _retrieval_profile_status(
            active_profile=active_retrieval_profile,
            memory_entry_count=len(memory_entries),
        ),
        "generated_cache": {
            "prepared": knowledge_report["prepared"],
            "generated_claim_count": knowledge_report["generated_claim_count"],
            "source_map_count": knowledge_report["source_map_count"],
            "stale_source_count": knowledge_report["stale_source_count"],
            "missing_source_count": knowledge_report["missing_source_count"],
            "orphaned_output_count": knowledge_report["orphaned_output_count"],
            "invalid_claim_count": knowledge_report["invalid_claim_count"],
            "cache_hit_ratio": knowledge_report["cache_hit_ratio"],
            "compile_duration_ms": knowledge_report["compile_duration_ms"],
            "last_compile_at": knowledge_report["last_compile_at"],
            "incremental_compile": knowledge_report["incremental_compile"],
            "skipped_source_count": knowledge_report["skipped_source_count"],
            "output_token_estimate": knowledge_report["output_token_estimate"],
        },
        "runtime_versions": runtime_version_payload(),
        "job_health": runtime_report.get("job_health", {}),
        "retrieval_health": runtime_report.get("retrieval_health", {}),
        "cost_budget": {
            "policy": cost_budget_policy(_cost_surface_budgets(project_name)),
            "summary": cost_report.get("summary", {}),
            "recent_high_output_calls": cost_report.get("recent_high_output_calls", [])[:5],
            "top_opportunities": cost_report.get("top_opportunities", [])[:5],
        },
        "install_drift": runtime_report.get("version_drift", {}),
    }


def tool_get_project_status(project_name: str | None = None) -> dict:
    """Return active project and memory counts without requiring CLI status."""
    active_project = get_active_project()
    resolved_project = project_name or active_project
    if not resolved_project:
        guided_flow = build_guided_flow(
            phase="needs-project",
            project_name=None,
            active_project=active_project,
        )
        flow_hint = guided_flow_drilldown_hint(guided_flow)
        return {
            "success": False,
            "active_project": active_project,
            "phase": "needs-project",
            "suggested_slash": None,
            "reason": "Provide project_name or set an active project before status can resolve memory context.",
            "error": "project_name is required when no active project is set",
            "why_this_result": "No project was supplied and no active project is configured.",
            "next_actions": [
                _action(
                    "set_active_project",
                    "set_active_project",
                    "Set the active project once so wake/search/status can resolve project-scoped memory.",
                )
            ],
            "degraded_reason": "missing_project",
            "guided_flow": guided_flow,
            "drilldown_hints": [flow_hint],
        }

    backend = _get_backend()
    counts = asyncio.run(_gather_project_status(backend, resolved_project))
    triage = _status_triage_hints(counts)
    guided_flow = build_guided_flow(
        phase=str(triage.get("phase") or "unknown"),
        observation_count=int(counts.get("observation_count", 0) or 0),
        pending_candidate_count=int(counts.get("pending_candidate_count", 0) or 0),
        memory_entry_count=int(counts.get("memory_entry_count", 0) or 0),
        project_name=resolved_project,
        active_project=active_project,
    )
    dx_metadata = _status_dx_metadata(counts, triage, project_name=resolved_project)
    flow_hint = guided_flow_drilldown_hint(guided_flow)
    dx_metadata["drilldown_hints"] = [flow_hint, *list(dx_metadata.get("drilldown_hints") or [])]
    return {
        "success": True,
        "project_name": resolved_project,
        "active_project": active_project,
        "truth_runtime_state": backend.runtime_state,
        "truth_runtime_error": backend.runtime_error,
        "truth_runtime_recovery_hint": backend.runtime_recovery_hint,
        **counts,
        **triage,
        **dx_metadata,
        "guided_flow": guided_flow,
    }


def _status_triage_hints(counts: dict[str, Any]) -> dict[str, Any]:
    if counts["observation_count"] == 0:
        return {
            "phase": "needs-distill",
            "suggested_slash": "/hm:distill",
            "reason": "No observations have been ingested for this project yet.",
            "repair_hint": None,
            "repair_reason": None,
        }

    hints: dict[str, Any] = {
        "phase": "ready",
        "suggested_slash": "/hm:wake",
        "reason": "Project memory is available for wake-up context.",
        "repair_hint": None,
        "repair_reason": None,
    }
    if counts["pending_candidate_count"] > 0:
        hints["repair_hint"] = "/hm:review"
        hints["repair_reason"] = (
            "Pending candidates remain; use review only for explicit recheck or correction."
        )
    return hints


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


async def _merge_project_profile(
    project_name: str,
    *,
    description: str | None,
    stacks: list[str] | None,
    key_files: list[str] | None,
    curated_doc_paths: list[str] | None,
    conventions: list[str] | None,
    service_hints: list[str] | None,
    database_hints: list[str] | None,
    weak_link_signals: bool | None,
    mcp_tool_profile: McpToolProfile | None,
    maintenance_profile: MaintenanceProfile | None,
    retrieval_profile: RetrievalProfile | None,
    replace: bool,
) -> ProjectProfile:
    """Apply a non-interactive update to ``ProjectProfile``.

    ``replace=False`` (default) merges: ``None`` keeps the existing value,
    a list extends with deduplication, and ``description`` overwrites only
    when explicitly provided. ``replace=True`` substitutes each provided
    field outright; missing fields still keep their existing values.
    """
    # Read DEFAULT_DATA_DIR through command_support so runtime overrides flow
    # through this MCP tool too. Importing at call time is intentional.
    from harness_mem.commands import support as _support

    store = LocalProjectProfileStore(_support.DEFAULT_DATA_DIR)
    existing = await store.get(project_name)

    def _merge_list(old: list[str], new: list[str] | None) -> list[str]:
        if new is None:
            return list(old)
        if replace:
            return list(new)
        combined = list(old)
        seen = {item for item in combined}
        for item in new:
            if item not in seen:
                combined.append(item)
                seen.add(item)
        return combined

    if existing is None:
        profile = ProjectProfile(
            project_name=project_name,
            description=description or "",
            stacks=list(stacks or []),
            key_files=list(key_files or []),
            curated_doc_paths=list(curated_doc_paths or []),
            conventions=list(conventions or []),
            service_hints=list(service_hints or []),
            database_hints=list(database_hints or []),
            weak_link_signals=bool(weak_link_signals) if weak_link_signals is not None else False,
            mcp_tool_profile=mcp_tool_profile,
            maintenance_profile=maintenance_profile,
            retrieval_profile=retrieval_profile,
        )
    else:
        profile = ProjectProfile(
            id=existing.id,
            project_name=project_name,
            description=description if description is not None else existing.description,
            stacks=_merge_list(existing.stacks, stacks),
            key_files=_merge_list(existing.key_files, key_files),
            curated_doc_paths=_merge_list(existing.curated_doc_paths, curated_doc_paths),
            conventions=_merge_list(existing.conventions, conventions),
            service_hints=_merge_list(existing.service_hints, service_hints),
            database_hints=_merge_list(existing.database_hints, database_hints),
            weak_link_signals=(
                weak_link_signals if weak_link_signals is not None else existing.weak_link_signals
            ),
            mcp_tool_profile=(
                mcp_tool_profile if mcp_tool_profile is not None else existing.mcp_tool_profile
            ),
            maintenance_profile=(
                maintenance_profile
                if maintenance_profile is not None
                else existing.maintenance_profile
            ),
            retrieval_profile=(
                retrieval_profile
                if retrieval_profile is not None
                else existing.retrieval_profile
            ),
            created_at=existing.created_at,
            last_updated=datetime.now(timezone.utc),
            last_ingest_at=existing.last_ingest_at,
            last_ingest_session_id=existing.last_ingest_session_id,
        )

    await store.save(profile)
    return profile


def tool_update_project_profile(
    project_name: str,
    description: str | None = None,
    stacks: list[str] | None = None,
    key_files: list[str] | None = None,
    curated_doc_paths: list[str] | None = None,
    conventions: list[str] | None = None,
    service_hints: list[str] | None = None,
    database_hints: list[str] | None = None,
    weak_link_signals: bool | None = None,
    mcp_tool_profile: str | None = None,
    maintenance_profile: str | None = None,
    retrieval_profile: str | None = None,
    replace: bool = False,
) -> dict:
    """Non-interactive project profile update.

    Adds (or, with ``replace=True``, substitutes) profile fields. Fields
    omitted from the call are left untouched on the existing profile.
    Lists are deduplicated when merged so repeated calls are idempotent
    for the same value. Returns the resulting profile.
    """
    name = (project_name or "").strip()
    if not name:
        return {"success": False, "error": "project_name must not be empty"}
    normalized_mcp_tool_profile: McpToolProfile | None = None
    if mcp_tool_profile is not None:
        normalized_mcp_tool_profile = _normalize_mcp_tool_profile(mcp_tool_profile)
        if normalized_mcp_tool_profile is None:
            return {
                "success": False,
                "error": "mcp_tool_profile must be one of: full, minimal",
            }
    normalized_maintenance_profile: MaintenanceProfile | None = None
    if maintenance_profile is not None:
        normalized_maintenance_profile = _normalize_maintenance_profile(
            maintenance_profile
        )
        if normalized_maintenance_profile is None:
            return {
                "success": False,
                "error": (
                    "maintenance_profile must be one of: "
                    "weekly-dream, post-distill-metabolism"
                ),
            }

    normalized_retrieval_profile: RetrievalProfile | None = None
    if retrieval_profile is not None:
        normalized_retrieval_profile = _normalize_retrieval_profile(retrieval_profile)
        if normalized_retrieval_profile is None:
            return {
                "success": False,
                "error": "retrieval_profile must be one of: light, quality",
            }

    profile = asyncio.run(
        _merge_project_profile(
            name,
            description=description,
            stacks=stacks,
            key_files=key_files,
            curated_doc_paths=curated_doc_paths,
            conventions=conventions,
            service_hints=service_hints,
            database_hints=database_hints,
            weak_link_signals=weak_link_signals,
            mcp_tool_profile=normalized_mcp_tool_profile,
            maintenance_profile=normalized_maintenance_profile,
            retrieval_profile=normalized_retrieval_profile,
            replace=replace,
        )
    )
    return {
        "success": True,
        "project_name": profile.project_name,
        "profile": {
            "description": profile.description,
            "stacks": profile.stacks,
            "key_files": profile.key_files,
            "curated_doc_paths": profile.curated_doc_paths,
            "conventions": profile.conventions,
            "service_hints": profile.service_hints,
            "database_hints": profile.database_hints,
            "weak_link_signals": profile.weak_link_signals,
            "mcp_tool_profile": profile.mcp_tool_profile,
            "maintenance_profile": profile.maintenance_profile,
            "retrieval_profile": profile.retrieval_profile,
            "last_updated": profile.last_updated.isoformat(),
        },
    }


def tool_wake(
    project_name: str | None = None,
    no_auto_ingest: bool = False,
    renderer: str = "default",
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
    current_task: str | None = None,
    budget_tokens: int = 6000,
    deep_recall: bool = False,
) -> dict:
    """Generate the wake-up context (project profile + recent rules / handoffs).

    Captures the printed wake-up summary as ``output`` so the agent can
    ingest it directly without spawning a CLI subprocess.
    """
    resolved = project_name or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            "why_this_result": "Wake cannot resolve a project without project_name or an active project.",
            "next_actions": [
                _action(
                    "set_active_project",
                    "set_active_project",
                    "Set the active project once before running the daily wake flow.",
                )
            ],
            "degraded_reason": "missing_project",
            "drilldown_hints": [],
        }
    normalized_renderer = str(renderer or "default").strip().lower()
    if normalized_renderer not in {"default", COMPACT_RENDERER_NAME}:
        return {
            "success": False,
            "error": "renderer must be one of: default, compact",
        }
    if normalized_renderer == COMPACT_RENDERER_NAME:
        if include_skill_hints:
            return {
                "success": False,
                "project_name": resolved,
                "renderer": normalized_renderer,
                "error": "include_skill_hints is only supported with renderer=default",
                **_wake_dx_metadata(
                    success=False,
                    renderer=normalized_renderer,
                    fallback_reason="unsupported_compact_skill_hints",
                    source_coverage=None,
                    temporal_intent_mode=_temporal_intent_mode(current_task),
                ),
            }
        backend = _get_backend()
        payload = load_compact_wake_payload(backend.data_dir, project_name=resolved)
        if payload is None:
            return {
                "success": False,
                "project_name": resolved,
                "renderer": normalized_renderer,
                "error": (
                    "compact wake is unavailable: generated wiki bridge artifacts "
                    "have not been built for this project"
                ),
                **_wake_dx_metadata(
                    success=False,
                    renderer=normalized_renderer,
                    fallback_reason="compact_wake_artifacts_missing",
                    source_coverage=None,
                    temporal_intent_mode=_temporal_intent_mode(current_task),
                ),
            }
        compact_dx = _wake_dx_metadata(
            success=True,
            renderer=normalized_renderer,
            fallback_reason=None,
            source_coverage={"compact_payload": 1},
            temporal_intent_mode=_temporal_intent_mode(current_task),
        )
        return {
            "success": True,
            "project_name": resolved,
            "renderer": normalized_renderer,
            "output": render_compact_wake_payload(payload),
            "compact_payload": payload.to_dict(),
            **compact_dx,
        }
    command_payload = _run_command_to_payload(
        cmd_wake_up(
            resolved,
            no_auto_ingest=no_auto_ingest,
            include_skill_hints=include_skill_hints,
            skill_hint_limit=skill_hint_limit,
        )
    )
    snapshot_payload: dict[str, Any] = {}
    temporal_intent = _temporal_intent_mode(current_task)
    if command_payload.get("success"):
        effective_skill_hint_limit = (
            DEFAULT_SKILL_HINT_LIMIT if skill_hint_limit is None else skill_hint_limit
        )
        runtime = asyncio.run(
            orchestrate_task_context(
                _get_backend(),
                query=current_task or "wake context",
                project_name=resolved,
                scope="project",
                mode="auto",
                include_history=deep_recall,
                deep_recall=deep_recall,
                current_task=current_task,
                budget_tokens=budget_tokens,
                search_limit=10,
                context_limit=10,
                auto_deep_recall=True,
            )
        )
        snapshot_payload = asyncio.run(
            build_wake_snapshot(
                _get_backend(),
                resolved,
                include_skill_hints=bool(include_skill_hints),
                skill_hint_limit=effective_skill_hint_limit,
            )
        )
        context_plan = runtime.context_plan
        if context_plan is None:
            raise RuntimeError("project-scoped wake runtime returned no context plan")
        drilldown_hints = _with_temporal_intent_hint(
            runtime.response.drilldown_hints,
            project_name=resolved,
            query=current_task or "wake context",
            mode=temporal_intent,
        )
        status_counts = asyncio.run(_gather_project_status(_get_backend(), resolved))
        status_triage = _status_triage_hints(status_counts)
        guided_flow = build_guided_flow(
            phase=str(status_triage.get("phase") or "ready"),
            observation_count=int(status_counts.get("observation_count", 0) or 0),
            pending_candidate_count=int(status_counts.get("pending_candidate_count", 0) or 0),
            memory_entry_count=int(status_counts.get("memory_entry_count", 0) or 0),
            project_name=resolved,
            active_project=get_active_project(),
        )
        drilldown_hints = [
            guided_flow_drilldown_hint(guided_flow),
            *drilldown_hints,
        ]
        snapshot_payload.update(
            {
                "context_sufficiency": context_plan.context_sufficiency.to_dict(),
                "retrieval_plan": context_plan.retrieval_plan.to_dict(),
                "iterative_retrieval_trace": (
                    context_plan.iterative_retrieval_trace.to_dict()
                ),
                "context_plan": {
                    **context_plan.to_dict(),
                    "drilldown_hints": drilldown_hints,
                },
                "wake_packet": context_plan.wake_packet.to_dict(),
                "requested_mode": runtime.response.requested_mode,
                "effective_mode": runtime.response.effective_mode,
                "fallback_reason": runtime.response.fallback_metadata.get(
                    "fallback_reason"
                ),
                "backend_budget": runtime.response.budget,
                "backend_truncation": runtime.response.truncation,
                "source_coverage": runtime.response.source_coverage,
                "drilldown_hints": drilldown_hints,
                "guided_flow": guided_flow,
                "supporting_evidence": runtime.supporting_evidence,
                "answer_ready_context": runtime.answer_ready_context,
                "effective_deep_recall": runtime.effective_deep_recall,
                "orchestration_actions": runtime.orchestration_actions,
            }
        )
    wake_dx = _wake_dx_metadata(
        success=bool(command_payload.get("success")),
        renderer=normalized_renderer,
        fallback_reason=snapshot_payload.get("fallback_reason"),
        source_coverage=snapshot_payload.get("source_coverage"),
        temporal_intent_mode=temporal_intent,
    )
    return {
        "project_name": resolved,
        "renderer": normalized_renderer,
        **snapshot_payload,
        **wake_dx,
        "include_skill_hints": include_skill_hints,
        "skill_hint_limit": skill_hint_limit,
        "current_task": current_task,
        "budget_tokens": budget_tokens,
        "deep_recall": deep_recall,
        **command_payload,
    }


def _run_command_to_payload(coro: Any) -> dict[str, Any]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = asyncio.run(coro)
    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": output.getvalue().strip(),
    }


def _replay_window_to_input_window(window: ReplayWindow) -> dict[str, Any]:
    """Serialize a ``ReplayWindow`` into the JSON-friendly preview shape.

    Locked in by ``test_metabolism_run_preview_shape_round_trip`` (3.5):
    ``time_range`` is an ISO ``{start, end}`` mapping, ``dimensions`` is
    a name → ``{selected_ids, truncated, total_seen}`` mapping in the
    selector's iteration order, ``signal_ids`` and ``notes`` are plain
    lists. Datetimes don't ``asdict`` cleanly, so we walk the dataclass
    by hand.
    """
    dimensions: dict[str, dict[str, Any]] = {}
    for name, dim in window.dimensions.items():
        dimensions[name] = {
            "selected_ids": list(dim.selected_ids),
            "truncated": dim.truncated,
            "total_seen": dim.total_seen,
        }
    return {
        "time_range": {
            "start": window.time_range[0].isoformat(),
            "end": window.time_range[1].isoformat(),
        },
        "dimensions": dimensions,
        "signal_ids": list(window.signal_ids),
        "notes": list(window.notes),
    }


_RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _highest_risk(values: list[str]) -> str:
    if not values:
        return "none"
    return max(values, key=lambda value: _RISK_RANK.get(value, 0))


def _maintenance_summary(
    *,
    candidate_counts: dict[str, int],
    risk_level: str,
    auto_applied: bool,
    needs_human_review: bool,
    undo_available: bool,
    message: str,
) -> dict[str, Any]:
    summary = {
        "candidate_counts": candidate_counts,
        "risk_level": risk_level,
        "auto_applied": auto_applied,
        "needs_human_review": needs_human_review,
        "undo_available": undo_available,
        "message": message,
    }
    return {"maintenance_summary": dict(summary), **summary}


def _metabolism_preview_summary(input_window: dict[str, Any]) -> dict[str, Any]:
    dimensions = input_window.get("dimensions") or {}
    pending_dim = dimensions.get("pending_candidates") or {}
    selected_pending = len(pending_dim.get("selected_ids") or [])
    candidate_counts = {
        "selected_pending_candidates": selected_pending,
        "merge_suggestions": 0,
        "stale_suggestions": 0,
        "supersede_suggestions": 0,
    }
    has_window = any(
        len((dim or {}).get("selected_ids") or []) > 0
        for dim in dimensions.values()
        if isinstance(dim, dict)
    )
    return _maintenance_summary(
        candidate_counts=candidate_counts,
        risk_level="low" if has_window else "none",
        auto_applied=False,
        needs_human_review=selected_pending > 0,
        undo_available=False,
        message=(
            "Preview only; no candidates were written and truth was not changed."
            if has_window
            else "No maintenance suggestions selected; project appears clean for this window."
        ),
    )


def _metabolism_run_summary(output_counts: dict[str, int]) -> dict[str, Any]:
    total = sum(int(value or 0) for value in output_counts.values())
    return _maintenance_summary(
        candidate_counts={key: int(value or 0) for key, value in output_counts.items()},
        risk_level="medium" if total else "none",
        auto_applied=False,
        needs_human_review=total > 0,
        undo_available=False,
        message=(
            "Metabolism wrote pending suggestion candidates for review; truth was not changed."
            if total
            else "No maintenance suggestions selected; project appears clean for this window."
        ),
    )


def _dream_run_summary(run_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not run_payload:
        return _maintenance_summary(
            candidate_counts={
                "processed": 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0,
                "pending_review": 0,
            },
            risk_level="none",
            auto_applied=False,
            needs_human_review=False,
            undo_available=False,
            message="No dream ledger exists yet; no maintenance has been applied.",
        )
    summary = {
        key: int(value or 0)
        for key, value in (run_payload.get("handling_summary") or {}).items()
    }
    items = run_payload.get("items") or []
    risk_level = _highest_risk(
        [str(item.get("risk") or "none") for item in items if isinstance(item, dict)]
    )
    undo_available = any(
        isinstance(item, dict)
        and item.get("final_action") == "applied"
        and bool(item.get("undo"))
        and not (item.get("result") or {}).get("undone_at")
        for item in items
    )
    failed = int(summary.get("failed", 0) or 0)
    archived = int(summary.get("archived", 0) or 0)
    rejected = int(summary.get("rejected", 0) or 0)
    applied = int(summary.get("applied", 0) or 0)
    return _maintenance_summary(
        candidate_counts=summary,
        risk_level=risk_level,
        auto_applied=applied > 0,
        needs_human_review=failed > 0 or archived > 0 or rejected > 0,
        undo_available=undo_available,
        message=(
            "Dream applied maintenance with undo metadata in the ledger."
            if applied
            else "No maintenance was applied in this dream run."
        ),
    )


def tool_metabolism_preview(
    project_name: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Preview the next metabolism run's input window.

    v2.3.0: read-only. Resolves the project (active-project fallback),
    normalizes the optional ``budget`` against ``ReplayBudget`` defaults,
    runs ``select_replay_window``, persists a
    ``MetabolismRun(kind="preview", status="preview")`` for audit, and
    returns the window summary. Selector / persistence failures funnel
    through a single ``except`` that records an
    ``MetabolismRun(status="error")`` (best-effort) and returns
    ``{success: False, error, doctor_pointer}``. This handler MUST NOT
    raise.
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }

    backend = _get_backend()
    started_at = datetime.now(timezone.utc)
    # Writers stay implementation-side per the StructuredStore Protocol
    # contract (only `list_metabolism_runs` is on the Protocol). Cast to
    # the local concrete store to access `save_metabolism_run`.
    structured_store = cast(LocalStructuredStore, backend.structured_store)

    try:
        budget_kwargs: dict[str, int] = {}
        if budget:
            for key in (
                "max_observations",
                "max_pending_candidates",
                "max_historical_truths",
                "max_low_success_skills",
                "max_repeat_search_hits",
                "max_total_tokens",
                "signal_lookback_days",
            ):
                if key in budget and budget[key] is not None:
                    budget_kwargs[key] = budget[key]

        normalized_budget = ReplayBudget(**budget_kwargs)
        window = asyncio.run(
            select_replay_window(
                backend,
                project_name=resolved,
                budget=normalized_budget,
            )
        )
        input_window = _replay_window_to_input_window(window)
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        run_id = asyncio.run(
            structured_store.save_metabolism_run(
                MetabolismRun(
                    project_name=resolved,
                    kind="preview",
                    status="preview",
                    started_at=started_at,
                    completed_at=completed_at,
                    input_window=input_window,
                    selected_signal_ids=list(window.signal_ids),
                    output_counts={"suggestions": 0},
                    duration_ms=duration_ms,
                    notes=list(window.notes) if window.notes else None,
                )
            )
        )
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        error_message = str(exc) or exc.__class__.__name__
        # Best-effort persist an error run record. Failure here is logged
        # and swallowed — the user-visible error payload is still returned.
        try:
            asyncio.run(
                structured_store.save_metabolism_run(
                    MetabolismRun(
                        project_name=resolved,
                        kind="preview",
                        status="error",
                        started_at=started_at,
                        completed_at=completed_at,
                        input_window={},
                        selected_signal_ids=[],
                        output_counts={"suggestions": 0},
                        duration_ms=duration_ms,
                        notes=[f"selector failed: {error_message}"],
                    )
                )
            )
        except Exception:
            logger.exception(
                "metabolism_preview: failed to persist error run for project=%s",
                resolved,
            )
        return {
            "success": False,
            "error": error_message,
            "doctor_pointer": _METABOLISM_PREVIEW_DOCTOR_POINTER,
            **_maintenance_summary(
                candidate_counts={
                    "selected_pending_candidates": 0,
                    "merge_suggestions": 0,
                    "stale_suggestions": 0,
                    "supersede_suggestions": 0,
                },
                risk_level="none",
                auto_applied=False,
                needs_human_review=True,
                undo_available=False,
                message="Metabolism preview failed before selecting maintenance suggestions.",
            ),
        }

    return {
        "success": True,
        "run_id": run_id,
        "project_name": resolved,
        "time_range": input_window["time_range"],
        "dimensions": input_window["dimensions"],
        "notes": list(window.notes),
        "signals_used": len(window.signal_ids),
        **_metabolism_preview_summary(input_window),
    }


def tool_metabolism_run(
    project_name: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Run a metabolism pass and persist suggestion candidates.

    v2.3.1: mirrors :func:`tool_metabolism_preview`'s argument shape and
    error handling but performs the full suggestion pass:

    1. Resolve the project (active-project fallback) and normalize
       ``budget`` against ``ReplayBudget`` defaults.
    2. Run :func:`select_metabolism_pass`, which wraps
       ``select_replay_window`` and produces merge / stale / supersede
       candidates (auto-supersede deferred to v2.3.2 — proposer
       returns ``[]``).
    3. Persist a ``MetabolismRun(kind="metabolism", status="completed")``
       audit record carrying per-type ``output_counts``.
    4. Persist each candidate, rewriting ``metabolism_run_id`` to the
       newly-saved run id (the pass writes a ``"pending"`` sentinel).

    On any exception the handler best-effort persists a
    ``MetabolismRun(kind="metabolism", status="error")`` and returns
    ``{success: False, error, doctor_pointer}`` without raising. This
    matches the v2.3.0 preview contract bit-for-bit so MCP callers can
    treat both tools the same way.
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }

    backend = _get_backend()
    started_at = datetime.now(timezone.utc)
    # Same Protocol-vs-impl reasoning as ``tool_metabolism_preview``:
    # writers stay implementation-side, so cast to the local concrete
    # store to access ``save_metabolism_run`` and the candidate writers.
    structured_store = cast(LocalStructuredStore, backend.structured_store)

    try:
        budget_kwargs: dict[str, int] = {}
        if budget:
            for key in (
                "max_observations",
                "max_pending_candidates",
                "max_historical_truths",
                "max_low_success_skills",
                "max_repeat_search_hits",
                "max_total_tokens",
                "signal_lookback_days",
            ):
                if key in budget and budget[key] is not None:
                    budget_kwargs[key] = budget[key]

        normalized_budget = ReplayBudget(**budget_kwargs)
        pass_result = asyncio.run(
            select_metabolism_pass(
                backend,
                project_name=resolved,
                budget=normalized_budget,
            )
        )
        window = pass_result.window
        input_window = _replay_window_to_input_window(window)

        merge_count = len(pass_result.merge)
        stale_count = len(pass_result.stale)
        supersede_count = len(pass_result.supersede)
        output_counts = {
            "merge_suggestions": merge_count,
            "stale_suggestions": stale_count,
            "supersede_suggestions": supersede_count,
        }

        # Window notes come from the replay-window selector; pass notes
        # come from the proposers (e.g. ``stale_scan_truncated``). Both
        # contribute to the run's audit trail.
        combined_notes: list[str] = []
        combined_notes.extend(window.notes)
        combined_notes.extend(pass_result.notes)

        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)

        run_record = MetabolismRun(
            project_name=resolved,
            kind="metabolism",
            status="completed",
            started_at=started_at,
            completed_at=completed_at,
            input_window=input_window,
            selected_signal_ids=list(window.signal_ids),
            output_counts=output_counts,
            duration_ms=duration_ms,
            notes=combined_notes if combined_notes else None,
        )
        run_id = asyncio.run(structured_store.save_metabolism_run(run_record))

        # Persist candidates with the real run id. The pass writes a
        # ``"pending"`` sentinel so it stays free of the run lifecycle;
        # the MCP layer is the single place that knows the run id.
        for merge_candidate in pass_result.merge:
            merge_candidate.metabolism_run_id = run_id
            asyncio.run(
                structured_store.save_merge_suggestion_candidate(merge_candidate)
            )
        for stale_candidate in pass_result.stale:
            stale_candidate.metabolism_run_id = run_id
            asyncio.run(
                structured_store.save_stale_truth_suggestion_candidate(stale_candidate)
            )
        # Supersede candidates are deferred (proposer returns []) but
        # iterating still costs nothing and keeps the shape stable for
        # the day v2.3.2 reactivates the leg.
        for supersede in pass_result.supersede:
            asyncio.run(structured_store.save_supersede_candidate(supersede))
    except Exception as exc:
        completed_at = datetime.now(timezone.utc)
        duration_ms = int((completed_at - started_at).total_seconds() * 1000)
        error_message = str(exc) or exc.__class__.__name__
        # Best-effort persist an error run record. Failure here is logged
        # and swallowed — the user-visible error payload is still returned.
        try:
            asyncio.run(
                structured_store.save_metabolism_run(
                    MetabolismRun(
                        project_name=resolved,
                        kind="metabolism",
                        status="error",
                        started_at=started_at,
                        completed_at=completed_at,
                        input_window={},
                        selected_signal_ids=[],
                        output_counts={
                            "merge_suggestions": 0,
                            "stale_suggestions": 0,
                            "supersede_suggestions": 0,
                        },
                        duration_ms=duration_ms,
                        notes=[f"metabolism_run failed: {error_message}"],
                    )
                )
            )
        except Exception:
            logger.exception(
                "metabolism_run: failed to persist error run for project=%s",
                resolved,
            )
        return {
            "success": False,
            "error": error_message,
            "doctor_pointer": _METABOLISM_PREVIEW_DOCTOR_POINTER,
            **_maintenance_summary(
                candidate_counts={
                    "merge_suggestions": 0,
                    "stale_suggestions": 0,
                    "supersede_suggestions": 0,
                },
                risk_level="none",
                auto_applied=False,
                needs_human_review=True,
                undo_available=False,
                message="Metabolism run failed before writing review candidates.",
            ),
        }

    return {
        "success": True,
        "run_id": run_id,
        "project_name": resolved,
        "time_range": input_window["time_range"],
        "dimensions": input_window["dimensions"],
        "notes": list(combined_notes),
        "signals_used": len(window.signal_ids),
        "output_counts": output_counts,
        **_metabolism_run_summary(output_counts),
    }


def _resolve_project_for_dream(project_name: str | None) -> str | None:
    return (project_name or "").strip() or get_active_project()


def _dream_budget_from_payload(budget: dict | None) -> ReplayBudget | None:
    if not budget:
        return None
    budget_kwargs: dict[str, int] = {}
    for key in (
        "max_observations",
        "max_pending_candidates",
        "max_historical_truths",
        "max_low_success_skills",
        "max_repeat_search_hits",
        "max_total_tokens",
        "signal_lookback_days",
    ):
        if key in budget and budget[key] is not None:
            budget_kwargs[key] = budget[key]
    return ReplayBudget(**budget_kwargs)


def _resolve_project_root_for_dream(project_root: str | None) -> str:
    return str(Path(project_root).resolve() if project_root else Path.cwd().resolve())


def tool_dream_ledger(
    project_name: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Return the latest v3.1 DreamRun ledger, or one run by id."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    backend = _get_backend()
    payload = asyncio.run(
        latest_dream_ledger(
            backend,
            project_name=resolved,
            run_id=run_id,
        )
    )
    return {**payload, **_dream_run_summary(payload.get("run"))}


def tool_dream_run(
    project_name: str | None = None,
    project_root: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Run one v3.1 dream maintenance pass and return its ledger payload."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    root = _resolve_project_root_for_dream(project_root)
    try:
        config = load_merged_config(root)
    except ConfigError as exc:
        return {"success": False, "error": str(exc), **_dream_run_summary(None)}
    backend = _get_backend()
    try:
        run = asyncio.run(
            dream_once(
                backend,
                project_name=resolved,
                config=config,
                source="agent",
                budget=_dream_budget_from_payload(budget),
            )
        )
    except Exception as exc:  # noqa: BLE001 - MCP tool should not crash JSON-RPC.
        return {
            "success": False,
            "error": str(exc) or exc.__class__.__name__,
            **_dream_run_summary(None),
        }
    run_payload = run.to_dict()
    return {
        "success": True,
        "project_name": resolved,
        "run": run_payload,
        **_dream_run_summary(run_payload),
    }


def tool_dream_auto_tick(
    project_name: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Host/client scheduler tick for default-off v3.1 auto dream."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    root = _resolve_project_root_for_dream(project_root)
    try:
        config = load_merged_config(root)
    except ConfigError as exc:
        return {"success": False, "error": str(exc), **_dream_run_summary(None)}
    backend = _get_backend()
    payload = asyncio.run(
        dream_auto_tick(
            backend,
            project_name=resolved,
            project_root=root,
            config=config,
            source="scheduler",
        )
    )
    if payload.get("status") == "completed" and payload.get("summary"):
        run_summary = {
            "processed": int(payload["summary"].get("processed", 0) or 0),
            "applied": int(payload["summary"].get("applied", 0) or 0),
            "rejected": int(payload["summary"].get("rejected", 0) or 0),
            "archived": int(payload["summary"].get("archived", 0) or 0),
            "failed": int(payload["summary"].get("failed", 0) or 0),
            "pending_review": int(payload["summary"].get("pending_review", 0) or 0),
        }
        return {
            **payload,
            **_maintenance_summary(
                candidate_counts=run_summary,
                risk_level="medium" if run_summary.get("processed", 0) else "none",
                auto_applied=run_summary.get("applied", 0) > 0,
                needs_human_review=run_summary.get("failed", 0) > 0,
                undo_available=run_summary.get("applied", 0) > 0,
                message="Scheduler completed one dream run and wrote a ledger.",
            ),
        }
    return {
        **payload,
        **_maintenance_summary(
            candidate_counts={
                "processed": 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0,
                "pending_review": 0,
            },
            risk_level="none",
            auto_applied=False,
            needs_human_review=False,
            undo_available=False,
            message=str(payload.get("reason") or "No dream maintenance ran."),
        ),
    }


def tool_undo_dream_item(
    project_name: str | None = None,
    run_id: str | None = None,
    item_id: str | None = None,
) -> dict:
    """Undo one applied DreamItem by replaying its stored undo metadata."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    if not run_id or not item_id:
        return {
            "success": False,
            "error": "run_id and item_id are required",
            **_dream_run_summary(None),
        }
    backend = _get_backend()
    payload = asyncio.run(
        undo_dream_item(
            backend,
            project_name=resolved,
            run_id=run_id,
            item_id=item_id,
        )
    )
    return {
        **payload,
        **_maintenance_summary(
            candidate_counts={
                "processed": 1 if payload.get("item") else 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0 if payload.get("success") else 1,
                "pending_review": 0,
            },
            risk_level="low" if payload.get("success") else "medium",
            auto_applied=False,
            needs_human_review=not bool(payload.get("success")),
            undo_available=False,
            message=(
                "Undo completed; ledger item records undone_at."
                if payload.get("success")
                else "Undo failed; inspect the returned item and error."
            ),
        ),
    }


def tool_ingest_sessions(
    project_name: str,
    client: str = "auto",
    limit: int = 10,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
) -> dict:
    """Ingest sessions through MCP so users do not need to drive CLI commands."""
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, antigravity, opencode, hermes",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}

    payload = _run_command_to_payload(
        cmd_ingest(
            normalized_client,
            project_name,
            limit,
            full_rescan,
            scope=scope,
            project_root=project_root,
        )
    )
    return {
        "project_name": project_name,
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
        "scope": scope,
        "limit": limit,
        **payload,
    }


async def _recent_project_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
) -> list[Any]:
    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    return sorted(
        project_observations,
        key=lambda observation: observation.timestamp or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:limit]


def _truncate_packet_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    omitted = len(value) - max_chars
    return f"{value[:max_chars]}\n\n[TRUNCATED: {omitted} chars omitted]"


def tool_prepare_session_distill(
    project_name: str,
    client: str = "auto",
    limit: int = 5,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
    observation_limit: int = 5,
    max_chars_per_observation: int = 6000,
    run_ingest: bool = True,
) -> dict:
    """Prepare a compact evidence packet for AI-led session-distill.

    This intentionally stops before synthesis. The model should read the
    returned observations, decide what deserves a pending candidate, then call
    suggest_* tools. Keeping the discovery work in one MCP call avoids slash
    commands probing files, shell aliases, timeline, and observation IDs by hand.
    """
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, antigravity, opencode, hermes",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}

    effective_limit = max(1, min(int(limit), 50))
    effective_observation_limit = max(1, min(int(observation_limit), 20))
    effective_max_chars = max(500, min(int(max_chars_per_observation), 20000))

    ingest_payload: dict[str, Any] = {
        "success": True,
        "skipped": True,
        "reason": "run_ingest=false",
    }
    if run_ingest:
        ingest_payload = tool_ingest_sessions(
            project_name=project_name,
            client=normalized_client,
            limit=effective_limit,
            full_rescan=full_rescan,
            scope=scope,
            project_root=project_root,
        )

    backend = _get_backend()
    observations = asyncio.run(
        _recent_project_observations(
            backend,
            project_name=project_name,
            limit=effective_observation_limit,
        )
    )
    counts = asyncio.run(_gather_project_status(backend, project_name))

    packet_observations = []
    for observation in observations:
        packet_observations.append(
            {
                "source": f"observation:{observation.id}",
                "id": observation.id,
                "session_id": observation.session_id,
                "client": observation.client,
                "content_type": observation.content_type,
                "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
                "tags": observation.tags,
                "metadata": observation.metadata,
                "raw_content": _truncate_packet_text(
                    observation.raw_content,
                    effective_max_chars,
                ),
            }
        )

    return {
        "success": bool(packet_observations) or bool(ingest_payload.get("success")),
        "project_name": project_name,
        "project_root": project_root,
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
        "scope": scope,
        "limit": effective_limit,
        "ingest": ingest_payload,
        "status": counts,
        "observation_limit": effective_observation_limit,
        "max_chars_per_observation": effective_max_chars,
        "observations": packet_observations,
        "observation_count": len(packet_observations),
        "distill_instructions": [
            "Do not call Bash, cmem, cat, ls, find, timeline, or get_observations for this slash flow unless this packet is empty.",
            "Read the observations in this response as the session-distill evidence packet.",
            "Do not create candidates from tool probing, failed commands, MCP/slash mechanics, or agent orchestration failures unless the target project is that tooling.",
            "For application/game projects, do not record AI review workflows or skill names as project architecture.",
            "Create only reusable pending candidates with suggest_memory_entry, suggest_rule, suggest_relation_fact, or create_task_handoff.",
            "Use source values from this packet, e.g. observation:<id>, unless a stronger session/file source is present.",
            "Finish by calling list_candidates(project_name, status='pending') once.",
        ],
    }


# Pure serializers extracted to mcp/serializers.py — see the future-split
# note in the module docstring. We re-export the names here so internal
# callers (and any external import that already uses them) keep working.
from harness_mem.mcp.serializers import (  # noqa: E402, F401
    _isoformat,
    _serialize_merge_suggestion_candidate,
    _serialize_memory_entry_candidate,
    _serialize_procedural_candidate,
    _serialize_relation_fact_candidate,
    _serialize_rule_candidate,
    _serialize_skill_deprecation_suggestion_candidate,
    _serialize_skill_promotion_candidate,
    _serialize_skill_revision_suggestion_candidate,
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
    list[dict],
    list[dict],
    list[dict],
    list[dict],
]:
    rules = await backend.structured_store.list_rule_candidates(project_name, status=status)
    entries = await backend.structured_store.list_memory_entries(project_name, status=status, limit=limit)
    facts = await backend.structured_store.list_relation_facts(project_name, status=status, limit=limit)
    supersedes = await backend.structured_store.list_supersede_candidates(project_name, status=status)
    procedural = await backend.structured_store.list_procedural_candidates(project_name, status=status)
    skill_promotions = await backend.structured_store.list_skill_promotion_candidates(
        project_name, status=status
    )
    skill_revisions = await backend.structured_store.list_skill_revision_suggestion_candidates(
        project_name, status=status
    )
    skill_deprecations = await backend.structured_store.list_skill_deprecation_suggestion_candidates(
        project_name, status=status
    )
    merge_suggestions = await backend.structured_store.list_merge_suggestion_candidates(project_name, status=status)
    stale_suggestions = await backend.structured_store.list_stale_truth_suggestion_candidates(project_name, status=status)
    return (
        [_serialize_rule_candidate(candidate) for candidate in rules[:limit]],
        [_serialize_memory_entry_candidate(entry) for entry in entries],
        [_serialize_relation_fact_candidate(fact) for fact in facts],
        [_serialize_supersede_candidate(candidate) for candidate in supersedes[:limit]],
        [_serialize_procedural_candidate(candidate) for candidate in procedural[:limit]],
        [_serialize_skill_promotion_candidate(candidate) for candidate in skill_promotions[:limit]],
        [_serialize_skill_revision_suggestion_candidate(candidate) for candidate in skill_revisions[:limit]],
        [_serialize_skill_deprecation_suggestion_candidate(candidate) for candidate in skill_deprecations[:limit]],
        [_serialize_merge_suggestion_candidate(candidate) for candidate in merge_suggestions[:limit]],
        [_serialize_stale_truth_suggestion_candidate(candidate) for candidate in stale_suggestions[:limit]],
    )


def tool_list_candidates(project_name: str, status: str = "pending", limit: int = 100) -> dict:
    """Return structured memory candidates for human review."""
    if status not in {"pending", "accepted", "rejected"}:
        return {
            "success": False,
            "error": "status must be one of: pending, accepted, rejected",
        }

    effective_limit = max(1, min(int(limit), 500))
    backend = _get_backend()
    (
        rule_candidates,
        memory_entries,
        relation_facts,
        supersede_candidates,
        procedural_candidates,
        skill_promotion_candidates,
        skill_revision_suggestion_candidates,
        skill_deprecation_suggestion_candidates,
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
        *procedural_candidates,
        *skill_promotion_candidates,
        *skill_revision_suggestion_candidates,
        *skill_deprecation_suggestion_candidates,
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
        "procedural_candidates": procedural_candidates,
        "skill_promotion_candidates": skill_promotion_candidates,
        "skill_revision_suggestion_candidates": skill_revision_suggestion_candidates,
        "skill_deprecation_suggestion_candidates": skill_deprecation_suggestion_candidates,
        "merge_suggestion_candidates": merge_suggestion_candidates,
        "stale_truth_suggestion_candidates": stale_truth_suggestion_candidates,
        "count": len(candidates),
        "total_count": len(all_candidates),
        "rule_count": len(rule_candidates),
        "memory_entry_count": len(memory_entries),
        "relation_fact_count": len(relation_facts),
        "supersede_count": len(supersede_candidates),
        "procedural_count": len(procedural_candidates),
        "skill_promotion_count": len(skill_promotion_candidates),
        "skill_revision_suggestion_count": len(skill_revision_suggestion_candidates),
        "skill_deprecation_suggestion_count": len(skill_deprecation_suggestion_candidates),
        "merge_suggestion_count": len(merge_suggestion_candidates),
        "stale_truth_suggestion_count": len(stale_truth_suggestion_candidates),
    }


def tool_get_candidate_detail(candidate_id: str, candidate_kind: str | None = None) -> dict:
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
            "procedural_candidate": (
                backend.structured_store.get_procedural_candidate,
                _serialize_procedural_candidate,
            ),
            "skill_promotion_candidate": (
                backend.structured_store.get_skill_promotion_candidate,
                _serialize_skill_promotion_candidate,
            ),
            "skill_revision_candidate": (
                backend.structured_store.get_skill_revision_suggestion_candidate,
                _serialize_skill_revision_suggestion_candidate,
            ),
            "skill_deprecation_candidate": (
                backend.structured_store.get_skill_deprecation_suggestion_candidate,
                _serialize_skill_deprecation_suggestion_candidate,
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
            selected = {candidate_kind: lookups[candidate_kind]} if candidate_kind in lookups else {}
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


def tool_auto_review_candidates(project_name: str, apply: bool = False) -> dict:
    """Run conservative heuristic auto-review over the project's pending candidates.

    Returns the standard summary shape
    (auto_confirmed / auto_rejected / kept_pending / needs_user_confirmation).
    With ``apply=False`` the structured store is not modified — the response
    is what auto-review *would* do. With ``apply=True`` decisions are applied
    via the same status mutators users would invoke manually.
    """
    backend = _get_backend()
    summary = asyncio.run(
        auto_review_candidates(backend, project_name=project_name, apply=apply)
    )
    payload = summary.to_dict()
    payload["success"] = True
    payload["project_name"] = project_name
    payload["applied"] = bool(apply)
    return payload


# =============================================================================
# WRITE TOOLS
# =============================================================================


def tool_create_rule_candidate(
    project_name: str,
    session_id: str,
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
) -> dict:
    """Create a rule candidate from a correction."""
    from uuid import uuid4
    from harness_mem.core.schemas import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id,
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.6,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="rule_candidate",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.create_rule_candidate",
        payload={"trigger": candidate.trigger, "session_id": candidate.session_id},
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "state_event_id": state_event_id,
    }


def tool_confirm_rule(rule_id: str) -> dict:
    """Promote a rule candidate to a confirmed rule."""
    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status == "accepted":
        return {"success": False, "error": f"Candidate already confirmed: {rule_id}"}

    confirmed = ConfirmedRule(
        id=str(uuid4()),
        project_name=candidate.project_name,
        pattern=candidate.pattern,
        trigger=candidate.trigger,
        examples=candidate.examples,
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=candidate.id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(confirmed))
    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "accepted"))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=candidate.project_name,
        target_kind="confirmed_rule",
        target_id=confirmed.id,
        status="accepted",
        source_surface="mcp.confirm_rule",
        payload={"source_candidate_id": rule_id, "trigger": confirmed.trigger},
    )

    return {
        "success": True,
        "confirmed_rule_id": confirmed.id,
        "pattern": confirmed.pattern,
        "trigger": confirmed.trigger,
        "state_event_id": state_event_id,
    }


def tool_reject_rule(rule_id: str, reason: str | None = None) -> dict:
    """Reject a rule candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status in ("accepted", "rejected"):
        return {"success": False, "error": f"Candidate already processed: {rule_id}"}

    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "rejected"))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_REJECTED,
        project_name=candidate.project_name,
        target_kind="rule_candidate",
        target_id=rule_id,
        status="rejected",
        source_surface="mcp.reject_rule",
        payload={"reason": reason or "No reason provided"},
    )
    return {
        "success": True,
        "rejected_rule_id": rule_id,
        "reason": reason or "No reason provided",
        "state_event_id": state_event_id,
    }


def tool_suggest_supersede(
    project_name: str,
    target_type: str,
    target_id: str,
    replacement_type: str,
    replacement_id: str,
    reason: str,
    evidence: str,
    source: str = "",
    confidence: float = 0.7,
) -> dict:
    backend = _get_backend()
    candidate = SupersedeCandidate(
        project_name=project_name,
        target_type=target_type,
        target_id=target_id,
        replacement_type=replacement_type,
        replacement_id=replacement_id,
        reason=reason,
        evidence=evidence,
        source=source,
        confidence=confidence,
    )
    saved_id = asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="supersede",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_supersede",
        payload={
            "target_type": target_type,
            "target_id": target_id,
            "replacement_type": replacement_type,
            "replacement_id": replacement_id,
        },
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "target_type": candidate.target_type,
        "target_id": candidate.target_id,
        "replacement_type": candidate.replacement_type,
        "replacement_id": candidate.replacement_id,
        "state_event_id": state_event_id,
    }


def tool_confirm_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    confirmed = asyncio.run(backend.structured_store.confirm_supersede_candidate(candidate_id))
    if confirmed is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.SUPERSEDE_COMPLETED,
        project_name=confirmed.project_name,
        target_kind="supersede",
        target_id=confirmed.id,
        status=confirmed.status,
        source_surface="mcp.confirm_supersede",
        payload={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
        },
    )
    return {
        "success": True,
        "candidate_id": confirmed.id,
        "status": confirmed.status,
        "state_event_id": state_event_id,
    }


def tool_reject_supersede(candidate_id: str) -> dict:
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_supersede_candidate(candidate_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {candidate_id}"}
    updated = asyncio.run(backend.structured_store.update_supersede_candidate_status(candidate_id, "rejected"))
    if not updated:
        return {"success": False, "error": f"Failed to reject candidate: {candidate_id}"}
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_REJECTED,
        project_name=candidate.project_name,
        target_kind="supersede",
        target_id=candidate_id,
        status="rejected",
        source_surface="mcp.reject_supersede",
        payload={
            "target_type": candidate.target_type,
            "target_id": candidate.target_id,
            "replacement_type": candidate.replacement_type,
            "replacement_id": candidate.replacement_id,
        },
    )
    return {
        "success": True,
        "rejected_candidate_id": candidate_id,
        "status": "rejected",
        "state_event_id": state_event_id,
    }


def tool_suggest_correction(
    project_name: str,
    supersedes_rule_id: str,
    pattern: str,
    trigger: str,
    reason: str,
    *,
    examples: list[str] | None = None,
    source_session_id: str = "",
) -> dict:
    """One-shot rule replacement: create new rule + mark old rule historical.

    This is the right tool to call when reality changed (Tauri v1 -> v2,
    framework upgrade, policy reversal) and an old confirmed rule is now
    actively wrong. The caller has already named the specific old rule, so
    no extra human confirm step is needed — the supersede chain is applied
    immediately.

    For brand-new rules (no specific old rule to replace), use
    ``create_rule_candidate`` -> ``confirm_rule`` instead.
    """
    backend = _get_backend()
    old_rule = asyncio.run(backend.structured_store.get_confirmed_rule(supersedes_rule_id))
    if old_rule is None:
        return {
            "success": False,
            "error": f"ConfirmedRule not found: {supersedes_rule_id}",
        }
    if old_rule.project_name != project_name:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} belongs to project "
                f"{old_rule.project_name!r}, not {project_name!r}"
            ),
        }
    if old_rule.valid_to is not None:
        return {
            "success": False,
            "error": (
                f"Rule {supersedes_rule_id} is already historical "
                f"(valid_to={old_rule.valid_to.isoformat()})"
            ),
        }

    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    source_id = source_session_id or "agent-correction"
    new_rule = ConfirmedRule(
        id=str(uuid4()),
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        examples=list(examples or []),
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=f"correction:{source_id}",
        source_session_id=source_id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(new_rule))

    candidate = SupersedeCandidate(
        id=str(uuid4()),
        project_name=project_name,
        target_type="confirmed_rule",
        target_id=old_rule.id,
        replacement_type="confirmed_rule",
        replacement_id=new_rule.id,
        reason=reason,
        evidence=f"Agent-driven correction (source: {source_id}).",
        source=f"correction:{source_id}",
        confidence=1.0,
    )
    asyncio.run(backend.structured_store.save_supersede_candidate(candidate))
    confirmed = asyncio.run(
        backend.structured_store.confirm_supersede_candidate(candidate.id)
    )
    if confirmed is None:
        return {
            "success": False,
            "error": (
                f"Saved new rule {new_rule.id} but supersede confirmation failed; "
                f"old rule {old_rule.id} is still current. "
                f"Call confirm_supersede with candidate_id={candidate.id} to retry."
            ),
            "new_rule_id": new_rule.id,
            "supersede_candidate_id": candidate.id,
        }
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
    )
    truth_state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=project_name,
        target_kind="confirmed_rule",
        target_id=new_rule.id,
        status="accepted",
        source_surface="mcp.suggest_correction",
        payload={"supersedes_rule_id": old_rule.id, "trigger": new_rule.trigger},
    )
    supersede_state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.SUPERSEDE_COMPLETED,
        project_name=project_name,
        target_kind="supersede",
        target_id=confirmed.id,
        status=confirmed.status,
        source_surface="mcp.suggest_correction",
        payload={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
        },
    )
    return {
        "success": True,
        "new_rule_id": new_rule.id,
        "old_rule_id": old_rule.id,
        "supersede_candidate_id": candidate.id,
        "old_rule_valid_to": confirmed.reviewed_at.isoformat() if confirmed.reviewed_at else None,
        "state_event_ids": [
            event_id
            for event_id in (truth_state_event_id, supersede_state_event_id)
            if event_id
        ],
    }


def tool_suggest_rule(
    project_name: str,
    pattern: str,
    trigger: str,
    session_id: str | None = None,
    examples: list[str] | None = None,
) -> dict:
    """Suggest a rule candidate for later review (lighter than confirm_rule)."""
    from uuid import uuid4
    from harness_mem.core.schemas.rule_candidate import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id or "",
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.5,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="rule_candidate",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_rule",
        payload={"trigger": candidate.trigger},
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "status": "suggested",
        "state_event_id": state_event_id,
    }


def tool_suggest_skill(
    project_name: str,
    activation_condition: str,
    steps: list[str],
    termination_condition: str,
    success_examples: list[str] | None = None,
    source_session_id: str | None = None,
    source: str = "",
    confidence: float = 0.7,
) -> dict:
    """Suggest a procedural skill candidate for later review."""
    backend = _get_backend()
    candidate = ProceduralCandidate(
        project_name=project_name,
        activation_condition=activation_condition,
        steps=steps,
        termination_condition=termination_condition,
        success_examples=success_examples or [],
        source_session_id=source_session_id or "",
        source=source,
        confidence=confidence,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_procedural_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="procedural_candidate",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_skill",
        payload={
            "activation_condition": candidate.activation_condition,
            "source_session_id": candidate.source_session_id,
            "source": candidate.source,
        },
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "status": "pending",
        "activation_condition": candidate.activation_condition,
        "state_event_id": state_event_id,
    }


def tool_confirm_skill(candidate_id: str) -> dict:
    """Confirm a procedural skill candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_procedural_candidate(candidate_id))
    if candidate is None or candidate.status != "pending":
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    skill = asyncio.run(backend.structured_store.confirm_procedural_candidate(candidate_id))
    if skill is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=skill.project_name,
        target_kind="skill",
        target_id=skill.id,
        status=skill.status,
        source_surface="mcp.confirm_skill",
        payload={
            "source_candidate_id": candidate_id,
            "activation_condition": candidate.activation_condition,
        },
    )
    return {
        "success": True,
        "candidate_id": candidate_id,
        "skill": serialize_skill(skill),
        "state_event_id": state_event_id,
    }


def tool_reject_skill(candidate_id: str) -> dict:
    """Reject a procedural skill candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_procedural_candidate(candidate_id))
    if candidate is None:
        return {
            "success": False,
            "candidate_id": candidate_id,
            "status": "not_found",
            "state_event_id": None,
        }
    updated = asyncio.run(
        backend.structured_store.update_procedural_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    state_event_id = None
    if updated:
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=candidate.project_name,
            target_kind="procedural_candidate",
            target_id=candidate_id,
            status="rejected",
            source_surface="mcp.reject_skill",
            payload={"activation_condition": candidate.activation_condition},
        )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
        "state_event_id": state_event_id,
    }


def tool_suggest_skill_promotion(
    skill_id: str,
    target_scope: str,
    portability_notes: str = "",
    disabled_assumptions: list[str] | None = None,
    confidence: float | None = None,
) -> dict:
    """Suggest promoting a project skill into shared scope."""
    if target_scope not in {"workspace", "global"}:
        return {
            "success": False,
            "error": "target_scope must be one of: workspace, global",
        }
    requested_scope = cast(PromotionScope, target_scope)

    backend = _get_backend()
    skill = asyncio.run(backend.structured_store.get_skill(skill_id))
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    if skill.scope != "project":
        return {
            "success": False,
            "error": f"Only project-scoped skills can be promoted: {skill_id}",
        }

    candidate = SkillPromotionCandidate(
        project_name=skill.project_name,
        source_skill_id=skill.id,
        requested_scope=requested_scope,
        origin_project=skill.origin_project,
        source_ids=skill.source_ids,
        portability_notes=portability_notes,
        disabled_assumptions=disabled_assumptions or [],
        confidence=skill.confidence if confidence is None else confidence,
    )
    saved_id = asyncio.run(backend.structured_store.save_skill_promotion_candidate(candidate))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=candidate.project_name,
        target_kind="skill_promotion_candidate",
        target_id=saved_id,
        status=candidate.status,
        source_surface="mcp.suggest_skill_promotion",
        payload={
            "source_skill_id": candidate.source_skill_id,
            "requested_scope": candidate.requested_scope,
            "origin_project": candidate.origin_project,
        },
    )
    return {
        "success": True,
        "candidate_id": saved_id,
        "skill_id": skill.id,
        "requested_scope": candidate.requested_scope,
        "status": candidate.status,
        "state_event_id": state_event_id,
    }


def tool_confirm_skill_promotion(candidate_id: str) -> dict:
    """Confirm a skill promotion candidate into shared scope."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_skill_promotion_candidate(candidate_id))
    if candidate is None or candidate.status != "pending":
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    skill = asyncio.run(backend.structured_store.confirm_skill_promotion_candidate(candidate_id))
    if skill is None:
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=skill.project_name,
        target_kind="skill",
        target_id=skill.id,
        status=skill.status,
        source_surface="mcp.confirm_skill_promotion",
        payload={
            "source_candidate_id": candidate_id,
            "source_skill_id": candidate.source_skill_id,
            "requested_scope": candidate.requested_scope,
        },
    )
    return {
        "success": True,
        "candidate_id": candidate_id,
        "skill": serialize_skill(skill),
        "state_event_id": state_event_id,
    }


def tool_reject_skill_promotion(candidate_id: str) -> dict:
    """Reject a skill promotion candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_skill_promotion_candidate(candidate_id))
    if candidate is None:
        return {
            "success": False,
            "candidate_id": candidate_id,
            "status": "not_found",
            "state_event_id": None,
        }
    updated = asyncio.run(
        backend.structured_store.update_skill_promotion_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    state_event_id = None
    if updated:
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=candidate.project_name,
            target_kind="skill_promotion_candidate",
            target_id=candidate_id,
            status="rejected",
            source_surface="mcp.reject_skill_promotion",
            payload={
                "source_skill_id": candidate.source_skill_id,
                "requested_scope": candidate.requested_scope,
            },
        )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
        "state_event_id": state_event_id,
    }


def tool_record_skill_result(
    skill_id: str,
    success: bool,
    surface: str | None = None,
    source_ids: list[str] | None = None,
    reason: str | None = None,
) -> dict:
    """Record one execution result for a confirmed skill."""
    backend = _get_backend()
    skill = asyncio.run(
        backend.structured_store.record_skill_result(
            skill_id,
            success=success,
        )
    )
    if skill is None:
        return {"success": False, "error": f"Skill not found: {skill_id}"}
    asyncio.run(
        record_retrieval_signal(
            backend,
            project_name=skill.project_name,
            signal_type=(
                "skill_result_success" if success else "skill_result_failure"
            ),
            target_kind="skill",
            target_id=skill.id,
            value=skill.success_rate,
            context={
                "surface": (surface or "unspecified").strip() or "unspecified",
                "source_ids": [
                    item.strip()
                    for item in (source_ids or [])
                    if isinstance(item, str) and item.strip()
                ],
                "reason": (reason or "").strip(),
            },
        )
    )
    return {
        "success": True,
        "skill": serialize_skill(skill),
    }


def _skill_revision_summary(skill: Any, trigger: str) -> str:
    if trigger == "zero_success_after_repeated_use":
        return (
            f"Skill has 0 successes across {skill.usage_count} uses; "
            "review activation condition and steps against recent failures."
        )
    rate = 0.0 if skill.success_rate is None else skill.success_rate
    return (
        f"Skill success rate is {rate:.2f} across {skill.usage_count} uses; "
        "review the procedure against recent failure outcomes."
    )


def tool_detect_skill_improvements(
    project_name: str,
    limit: int = 20,
    lookback_days: int = 30,
) -> dict:
    """Create reviewed revision suggestions for low-success skills."""
    backend = _get_backend()
    effective_limit = max(1, min(int(limit), 200))
    effective_lookback_days = max(1, min(int(lookback_days), 365))

    async def _run() -> dict[str, Any]:
        since = datetime.now(timezone.utc) - timedelta(days=effective_lookback_days)
        skills = await backend.structured_store.list_skills(project_name, status="active")
        pending = await backend.structured_store.list_skill_revision_suggestion_candidates(
            project_name,
            status="pending",
        )
        pending_skill_ids = {candidate.source_skill_id for candidate in pending}

        matched = [
            skill
            for skill in skills
            if (skill.success_rate is not None and skill.success_rate < 0.5)
            or (skill.usage_count >= 5 and skill.success_count == 0)
        ]
        matched.sort(
            key=lambda s: (
                s.success_rate is None,
                s.success_rate if s.success_rate is not None else 0.0,
                -s.usage_count,
            )
        )

        created: list[SkillRevisionSuggestionCandidate] = []
        state_event_ids: list[str] = []
        skipped_existing = 0
        for skill in matched[:effective_limit]:
            if skill.id in pending_skill_ids:
                skipped_existing += 1
                continue
            failure_signals = await backend.structured_store.query_retrieval_signals(
                project_name,
                signal_type="skill_result_failure",
                target_kind="skill",
                target_id=skill.id,
                since=since,
                limit=1000,
            )
            success_signals = await backend.structured_store.query_retrieval_signals(
                project_name,
                signal_type="skill_result_success",
                target_kind="skill",
                target_id=skill.id,
                since=since,
                limit=1000,
            )
            trigger = cast(
                RevisionTrigger,
                (
                "zero_success_after_repeated_use"
                if skill.usage_count >= 5 and skill.success_count == 0
                else "low_success_rate"
                ),
            )
            candidate = SkillRevisionSuggestionCandidate(
                project_name=project_name,
                source_skill_id=skill.id,
                trigger=trigger,
                summary=_skill_revision_summary(skill, trigger),
                usage_count=skill.usage_count,
                success_count=skill.success_count,
                failure_count=skill.failure_count,
                success_rate=skill.success_rate,
                recent_failure_signal_ids=[signal.id for signal in failure_signals],
                recent_success_signal_ids=[signal.id for signal in success_signals],
                confidence=0.85 if trigger == "zero_success_after_repeated_use" else 0.7,
            )
            saved_id = await backend.structured_store.save_skill_revision_suggestion_candidate(candidate)
            state_event_id = _record_state_event(
                backend,
                event_type=StateEventType.CANDIDATE_CREATED,
                project_name=candidate.project_name,
                target_kind="skill_revision_candidate",
                target_id=saved_id,
                status=candidate.status,
                source_surface="mcp.detect_skill_improvements",
                payload={
                    "source_skill_id": candidate.source_skill_id,
                    "trigger": candidate.trigger,
                    "success_rate": candidate.success_rate,
                },
            )
            if state_event_id:
                state_event_ids.append(state_event_id)
            created.append(candidate)

        return {
            "success": True,
            "project_name": project_name,
            "lookback_days": effective_lookback_days,
            "matched_skill_count": len(matched),
            "created_count": len(created),
            "skipped_existing_count": skipped_existing,
            "candidate_ids": [candidate.id for candidate in created],
            "state_event_ids": state_event_ids,
        }

    return asyncio.run(_run())


def _shared_skill_conflict_target(skills: list[Any], skill: Any) -> Any | None:
    for other in skills:
        if other.id == skill.id or other.scope not in {"workspace", "global"}:
            continue
        if other.name == skill.name and other.activation_condition == skill.activation_condition:
            if other.updated_at >= skill.updated_at:
                return other
    return None


def _skill_deprecation_summary(skill: Any, trigger: str, conflicting_skill: Any | None) -> str:
    if trigger == "conflicting_shared_skill" and conflicting_skill is not None:
        return (
            f"Shared skill overlaps with newer shared skill {conflicting_skill.id}; "
            "review whether the older one should be retired."
        )
    return (
        "Shared skill has been inactive beyond the stale window; "
        "review whether it should be retired from the shared library."
    )


def tool_detect_skill_deprecations(
    project_name: str,
    limit: int = 20,
    stale_days: int = 60,
) -> dict:
    """Create reviewed deprecation suggestions for stale/conflicting shared skills."""
    backend = _get_backend()
    effective_limit = max(1, min(int(limit), 200))
    effective_stale_days = max(1, min(int(stale_days), 3650))

    async def _run() -> dict[str, Any]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=effective_stale_days)
        skills = await backend.structured_store.list_skills_any_scope(
            project_name,
            status="active",
        )
        shared_skills = [skill for skill in skills if skill.scope in {"workspace", "global"}]
        pending = await backend.structured_store.list_skill_deprecation_suggestion_candidates(
            project_name,
            status="pending",
        )
        pending_skill_ids = {candidate.source_skill_id for candidate in pending}
        created: list[SkillDeprecationSuggestionCandidate] = []
        state_event_ids: list[str] = []
        skipped_existing = 0

        for skill in shared_skills:
            if len(created) >= effective_limit:
                break
            if skill.id in pending_skill_ids:
                skipped_existing += 1
                continue
            conflicting_skill = _shared_skill_conflict_target(shared_skills, skill)
            is_stale = (
                (skill.last_used_at is not None and skill.last_used_at < cutoff)
                or (skill.last_used_at is None and skill.created_at < cutoff)
            )
            if conflicting_skill is None and not is_stale:
                continue
            trigger = cast(
                DeprecationTrigger,
                "conflicting_shared_skill" if conflicting_skill is not None else "stale_shared_skill",
            )
            candidate = SkillDeprecationSuggestionCandidate(
                project_name=project_name,
                source_skill_id=skill.id,
                trigger=trigger,
                summary=_skill_deprecation_summary(skill, trigger, conflicting_skill),
                conflicting_skill_id=conflicting_skill.id if conflicting_skill is not None else "",
                usage_count=skill.usage_count,
                success_rate=skill.success_rate,
                last_used_at=skill.last_used_at,
                confidence=0.8 if trigger == "conflicting_shared_skill" else 0.7,
            )
            saved_id = await backend.structured_store.save_skill_deprecation_suggestion_candidate(
                candidate
            )
            state_event_id = _record_state_event(
                backend,
                event_type=StateEventType.CANDIDATE_CREATED,
                project_name=candidate.project_name,
                target_kind="skill_deprecation_candidate",
                target_id=saved_id,
                status=candidate.status,
                source_surface="mcp.detect_skill_deprecations",
                payload={
                    "source_skill_id": candidate.source_skill_id,
                    "trigger": candidate.trigger,
                    "conflicting_skill_id": candidate.conflicting_skill_id,
                },
            )
            if state_event_id:
                state_event_ids.append(state_event_id)
            created.append(candidate)

        return {
            "success": True,
            "project_name": project_name,
            "stale_days": effective_stale_days,
            "shared_skill_count": len(shared_skills),
            "created_count": len(created),
            "skipped_existing_count": skipped_existing,
            "candidate_ids": [candidate.id for candidate in created],
            "state_event_ids": state_event_ids,
        }

    return asyncio.run(_run())


def tool_confirm_skill_revision(candidate_id: str) -> dict:
    """Accept a skill revision suggestion without rewriting the skill."""
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_skill_revision_suggestion_candidate(candidate_id)
    )
    if candidate is None or candidate.status != "pending":
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    updated = asyncio.run(
        backend.structured_store.update_skill_revision_suggestion_candidate_status(
            candidate_id,
            "accepted",
        )
    )
    if not updated:
        return {"success": False, "error": f"Failed to confirm candidate: {candidate_id}"}
    skill = asyncio.run(backend.structured_store.get_skill(candidate.source_skill_id))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=candidate.project_name,
        target_kind="skill_revision_candidate",
        target_id=candidate_id,
        status="accepted",
        source_surface="mcp.confirm_skill_revision",
        payload={
            "source_skill_id": candidate.source_skill_id,
            "trigger": candidate.trigger,
        },
    )
    return {
        "success": True,
        "candidate_id": candidate_id,
        "status": "accepted",
        "skill": serialize_skill(skill) if skill is not None else None,
        "state_event_id": state_event_id,
    }


def tool_reject_skill_revision(candidate_id: str) -> dict:
    """Reject a skill revision suggestion."""
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_skill_revision_suggestion_candidate(candidate_id)
    )
    if candidate is None:
        return {
            "success": False,
            "candidate_id": candidate_id,
            "status": "not_found",
            "state_event_id": None,
        }
    updated = asyncio.run(
        backend.structured_store.update_skill_revision_suggestion_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    state_event_id = None
    if updated:
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=candidate.project_name,
            target_kind="skill_revision_candidate",
            target_id=candidate_id,
            status="rejected",
            source_surface="mcp.reject_skill_revision",
            payload={
                "source_skill_id": candidate.source_skill_id,
                "trigger": candidate.trigger,
            },
        )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
        "state_event_id": state_event_id,
    }


def tool_confirm_skill_deprecation(candidate_id: str) -> dict:
    """Accept a skill deprecation suggestion and retire the shared skill."""
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_skill_deprecation_suggestion_candidate(candidate_id)
    )
    if candidate is None or candidate.status != "pending":
        return {"success": False, "error": f"Candidate not found or not pending: {candidate_id}"}
    retired_skill = asyncio.run(
        backend.structured_store.update_skill_status(
            candidate.source_skill_id,
            "retired",
        )
    )
    if retired_skill is None:
        return {"success": False, "error": f"Skill not found: {candidate.source_skill_id}"}
    updated = asyncio.run(
        backend.structured_store.update_skill_deprecation_suggestion_candidate_status(
            candidate_id,
            "accepted",
        )
    )
    if not updated:
        return {"success": False, "error": f"Failed to confirm candidate: {candidate_id}"}
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_REJECTED,
        project_name=candidate.project_name,
        target_kind="skill",
        target_id=retired_skill.id,
        status=retired_skill.status,
        source_surface="mcp.confirm_skill_deprecation",
        payload={
            "source_candidate_id": candidate_id,
            "source_skill_id": candidate.source_skill_id,
            "trigger": candidate.trigger,
        },
    )
    return {
        "success": True,
        "candidate_id": candidate_id,
        "status": "accepted",
        "skill": serialize_skill(retired_skill),
        "state_event_id": state_event_id,
    }


def tool_reject_skill_deprecation(candidate_id: str) -> dict:
    """Reject a skill deprecation suggestion."""
    backend = _get_backend()
    candidate = asyncio.run(
        backend.structured_store.get_skill_deprecation_suggestion_candidate(candidate_id)
    )
    if candidate is None:
        return {
            "success": False,
            "candidate_id": candidate_id,
            "status": "not_found",
            "state_event_id": None,
        }
    updated = asyncio.run(
        backend.structured_store.update_skill_deprecation_suggestion_candidate_status(
            candidate_id,
            "rejected",
        )
    )
    state_event_id = None
    if updated:
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=candidate.project_name,
            target_kind="skill_deprecation_candidate",
            target_id=candidate_id,
            status="rejected",
            source_surface="mcp.reject_skill_deprecation",
            payload={
                "source_skill_id": candidate.source_skill_id,
                "trigger": candidate.trigger,
            },
        )
    return {
        "success": updated,
        "candidate_id": candidate_id,
        "status": "rejected" if updated else "not_found",
        "state_event_id": state_event_id,
    }


def tool_suggest_memory_entry(
    project_name: str,
    category: str,
    content: str,
    source: str,
    confidence: float = 0.7,
    tags: list[str] | None = None,
) -> dict:
    """Suggest a memory entry for later review."""
    from harness_mem.core.schemas.memory_entry import MemoryEntry
    backend = _get_backend()
    entry = MemoryEntry(
        project_name=project_name,
        category=category,
        content=content,
        source=source,
        confidence=confidence,
        status="pending",
        tags=tags or [],
    )
    saved_id = asyncio.run(backend.structured_store.save_memory_entry(entry))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="memory_entry",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_memory_entry",
        payload={"category": entry.category, "source": entry.source},
    )
    return {
        "success": True,
        "entry_id": saved_id,
        "category": entry.category,
        "status": "pending",
        "state_event_id": state_event_id,
    }


def tool_confirm_memory_entry(entry_id: str) -> dict:
    """Confirm a pending memory entry."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_memory_entry_status(entry_id, "accepted"))
    state_event_id = None
    if success:
        entry = asyncio.run(backend.structured_store.get_memory_entry(entry_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_CONFIRMED,
            project_name=entry.project_name if entry else None,
            target_kind="memory_entry",
            target_id=entry_id,
            status="accepted",
            source_surface="mcp.confirm_memory_entry",
            payload={"category": getattr(entry, "category", None)},
        )
    return {
        "success": success,
        "entry_id": entry_id,
        "status": "accepted" if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_reject_memory_entry(entry_id: str) -> dict:
    """Reject a pending memory entry."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_memory_entry_status(entry_id, "rejected"))
    state_event_id = None
    if success:
        entry = asyncio.run(backend.structured_store.get_memory_entry(entry_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=entry.project_name if entry else None,
            target_kind="memory_entry",
            target_id=entry_id,
            status="rejected",
            source_surface="mcp.reject_memory_entry",
            payload={"category": getattr(entry, "category", None)},
        )
    return {
        "success": success,
        "entry_id": entry_id,
        "status": "rejected" if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_suggest_relation_fact(
    project_name: str,
    source_entity: str,
    target_entity: str,
    relation_type: str,
    evidence: str,
    source: str,
    confidence: float = 0.7,
) -> dict:
    """Suggest a relation fact for later review."""
    from harness_mem.core.schemas.relation_fact import RelationFact
    backend = _get_backend()
    fact = RelationFact(
        project_name=project_name,
        source_entity=source_entity,
        target_entity=target_entity,
        relation_type=relation_type,
        evidence=evidence,
        source=source,
        confidence=confidence,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_relation_fact(fact))
    state_event_id = _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="relation_fact",
        target_id=saved_id,
        status="pending",
        source_surface="mcp.suggest_relation_fact",
        payload={
            "source_entity": source_entity,
            "target_entity": target_entity,
            "relation_type": relation_type,
        },
    )
    return {
        "success": True,
        "fact_id": saved_id,
        "relation": f"{source_entity} --{relation_type}--> {target_entity}",
        "status": "pending",
        "state_event_id": state_event_id,
    }


def tool_confirm_relation_fact(fact_id: str) -> dict:
    """Confirm a pending relation fact."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_relation_fact_status(fact_id, "accepted"))
    state_event_id = None
    if success:
        fact = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_CONFIRMED,
            project_name=fact.project_name if fact else None,
            target_kind="relation_fact",
            target_id=fact_id,
            status="accepted",
            source_surface="mcp.confirm_relation_fact",
            payload={"relation_type": getattr(fact, "relation_type", None)},
        )
    return {
        "success": success,
        "fact_id": fact_id,
        "status": "accepted" if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_reject_relation_fact(fact_id: str) -> dict:
    """Reject a pending relation fact."""
    backend = _get_backend()
    success = asyncio.run(backend.structured_store.update_relation_fact_status(fact_id, "rejected"))
    state_event_id = None
    if success:
        fact = asyncio.run(backend.structured_store.get_relation_fact(fact_id))
        state_event_id = _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=fact.project_name if fact else None,
            target_kind="relation_fact",
            target_id=fact_id,
            status="rejected",
            source_surface="mcp.reject_relation_fact",
            payload={"relation_type": getattr(fact, "relation_type", None)},
        )
    return {
        "success": success,
        "fact_id": fact_id,
        "status": "rejected" if success else "not_found",
        "state_event_id": state_event_id,
    }


def tool_create_task_handoff(
    project_name: str,
    task_id: str,
    summary: str,
    status: str,
    next_steps: list[str] | None = None,
    blockers: list[str] | None = None,
) -> dict:
    """Create a task handoff to record progress."""
    from harness_mem.core.schemas.task_handoff import TaskHandoff
    backend = _get_backend()
    handoff = TaskHandoff(
        project_name=project_name,
        task_id=task_id,
        summary=summary,
        status=status,
        next_steps=next_steps or [],
        blockers=blockers or [],
    )
    saved_id = asyncio.run(backend.structured_store.save_task_handoff(handoff))
    return {
        "success": True,
        "handoff_id": saved_id,
        "task_id": handoff.task_id,
    }


# =============================================================================
# REFLECTION JOB VISIBILITY (v2.4.0, Req 7)
# =============================================================================

# Mirrors the Literal sets on ReflectionJob so we can validate caller
# input without importing the schema at module-import time. Source of
# truth for the values is harness_mem.core.schemas.reflection_job.
_VALID_REFLECTION_JOB_STATUSES: frozenset[str] = frozenset(
    {"pending", "processing", "completed", "failed", "retryable", "needs_distill"}
)
_VALID_REFLECTION_JOB_KINDS: frozenset[str] = frozenset({"reflection", "dream"})

# Caller-facing limit window per Req 7.1 — default 50, hard ceiling 200.
_REFLECTION_JOB_LIST_DEFAULT_LIMIT = 50
_REFLECTION_JOB_LIST_MAX_LIMIT = 200


def tool_list_reflection_jobs(
    project_name: str | None = None,
    status: str | None = None,
    kind: str | None = None,
    limit: int = _REFLECTION_JOB_LIST_DEFAULT_LIMIT,
) -> dict:
    """List recent reflection jobs (Req 7.1, 7.3, 7.5, 7.6).

    Read-only filtered listing. Status / kind values outside the schema's
    Literal sets short-circuit with ``{success: false, error}`` listing
    the valid options (Req 7.5). The ``limit`` is clamped server-side to
    ``[1, 200]`` so a caller asking for ``limit=500`` still gets at most
    200 rows (Req 7.1).
    """
    if status is not None and status not in _VALID_REFLECTION_JOB_STATUSES:
        valid = ", ".join(sorted(_VALID_REFLECTION_JOB_STATUSES))
        return {
            "success": False,
            "error": f"Invalid status: {status!r}. Valid values: {valid}.",
        }
    if kind is not None and kind not in _VALID_REFLECTION_JOB_KINDS:
        valid = ", ".join(sorted(_VALID_REFLECTION_JOB_KINDS))
        return {
            "success": False,
            "error": f"Invalid kind: {kind!r}. Valid values: {valid}.",
        }

    # Clamp limit to [1, 200]. Anything non-int has already been coerced
    # by the JSON-RPC parameter handling layer; if it ever isn't, fall
    # back to the default rather than 500'ing.
    try:
        clamped = int(limit)
    except (TypeError, ValueError):
        clamped = _REFLECTION_JOB_LIST_DEFAULT_LIMIT
    clamped = max(1, min(clamped, _REFLECTION_JOB_LIST_MAX_LIMIT))

    backend = _get_backend()
    jobs = backend.reflection_job_store.list(
        project_name=project_name,
        status=status,
        kind=kind,
        limit=clamped,
    )
    return {
        "success": True,
        "jobs": [job.to_dict() for job in jobs],
    }


def tool_get_reflection_job(job_id: str) -> dict:
    """Fetch a single reflection job by id (Req 7.2, 7.4, 7.6).

    Read-only. Returns the full ``to_dict()`` payload on hit; on miss
    surfaces ``{success: false, error}`` with a "not found" message so
    Agents can branch on the result without parsing message text
    (Req 7.4).
    """
    backend = _get_backend()
    job = backend.reflection_job_store.get(job_id)
    if job is None:
        return {
            "success": False,
            "error": f"Reflection job not found: {job_id}",
        }
    return {
        "success": True,
        "job": job.to_dict(),
    }


def tool_health_summary(project_name: str | None = None) -> dict:
    """Read-only combined v2.4.0 + v2.4.2 project health summary (Req 6).

    Resolves the active project when ``project_name`` is omitted, then wraps
    the ``health_summary`` orchestrator's payload in the standard ``success``
    envelope. The orchestrator is total (never raises) and self-heals each
    failed category into a ``{"warnings": [...]}`` slice (Req 6.7), so this
    handler only needs to guard the project-resolution precondition. No
    ``print`` here per project rule P0 (MCP stdio protection).
    """
    resolved = (project_name or "").strip() or get_active_project()
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
        }
    backend = _get_backend()
    payload = asyncio.run(health_summary(backend, resolved))
    return {"success": True, "project_name": resolved, **payload}


def tool_surface_cost_report(
    project_name: str | None = None,
    days: int = 7,
    limit: int = 200,
) -> dict:
    """Return local v3.4.0 MCP surface cost observer aggregates."""
    return {
        "success": True,
        **surface_cost_report(
            _observer_data_dir(),
            project_name=project_name,
            days=days,
            limit=limit,
            surface_budgets=_cost_surface_budgets(project_name),
        ),
    }


# =============================================================================
# MCP TOOL REGISTRY
# =============================================================================

import asyncio  # noqa: E402 (moved here so the stdio redirect above is clean)

from harness_mem.mcp.tool_specs import (  # noqa: E402,F401
    ToolSpec,
    build_tools,
)
from harness_mem.mcp.tool_registry import (  # noqa: E402
    hidden_tool_error,
    normalize_mcp_tool_profile,
    tool_descriptor,
    visible_tool_name_set,
    visible_tool_names,
)

# The schema for each tool lives in ``tool_specs._SCHEMAS``. Handlers stay
# next to the backend singleton in this file. ``build_tools`` glues schemas
# and handlers together and validates that the two sets of keys match
# (so a typoed handler name fails at import time, not at request time).
TOOLS: dict[str, ToolSpec] = build_tools({
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
    "update_project_profile": tool_update_project_profile,
    "wake": tool_wake,
    "ingest_sessions": tool_ingest_sessions,
    "prepare_session_distill": tool_prepare_session_distill,
    "metabolism_preview": tool_metabolism_preview,
    "metabolism_run": tool_metabolism_run,
    "dream_ledger": tool_dream_ledger,
    "dream_run": tool_dream_run,
    "dream_auto_tick": tool_dream_auto_tick,
    "undo_dream_item": tool_undo_dream_item,
    "list_candidates": tool_list_candidates,
    "get_candidate_detail": tool_get_candidate_detail,
    "auto_review_candidates": tool_auto_review_candidates,
    "suggest_supersede": tool_suggest_supersede,
    "confirm_supersede": tool_confirm_supersede,
    "reject_supersede": tool_reject_supersede,
    "suggest_correction": tool_suggest_correction,
    "suggest_skill": tool_suggest_skill,
    "confirm_skill": tool_confirm_skill,
    "reject_skill": tool_reject_skill,
    "suggest_skill_promotion": tool_suggest_skill_promotion,
    "confirm_skill_promotion": tool_confirm_skill_promotion,
    "reject_skill_promotion": tool_reject_skill_promotion,
    "record_skill_result": tool_record_skill_result,
    "record_context_outcome": tool_record_context_outcome,
    "detect_skill_improvements": tool_detect_skill_improvements,
    "confirm_skill_revision": tool_confirm_skill_revision,
    "reject_skill_revision": tool_reject_skill_revision,
    "detect_skill_deprecations": tool_detect_skill_deprecations,
    "confirm_skill_deprecation": tool_confirm_skill_deprecation,
    "reject_skill_deprecation": tool_reject_skill_deprecation,
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
    "list_reflection_jobs": tool_list_reflection_jobs,
    "get_reflection_job": tool_get_reflection_job,
    "health_summary": tool_health_summary,
    "surface_cost_report": tool_surface_cost_report,
})


def _normalize_mcp_tool_profile(value: object) -> McpToolProfile | None:
    return cast(McpToolProfile | None, normalize_mcp_tool_profile(value))


def _normalize_maintenance_profile(value: object) -> MaintenanceProfile | None:
    profile = str(value or "").strip().lower()
    if profile in VALID_MAINTENANCE_PROFILES:
        return cast(MaintenanceProfile, profile)
    return None


def _profile_project_name(params: dict[str, Any]) -> str | None:
    project_name = params.get("project_name")
    if not project_name and isinstance(params.get("arguments"), dict):
        project_name = params["arguments"].get("project_name")
    if isinstance(project_name, str) and project_name.strip():
        return project_name.strip()
    return get_active_project()


def _project_profile_mcp_tool_profile(project_name: str | None) -> McpToolProfile | None:
    if not project_name:
        return None
    try:
        from harness_mem.commands import support as _support

        profile = asyncio.run(LocalProjectProfileStore(_support.DEFAULT_DATA_DIR).get(project_name))
    except Exception:
        logger.exception("Failed to read project MCP tool profile for %s", project_name)
        return None
    if profile is None:
        return None
    return _normalize_mcp_tool_profile(profile.mcp_tool_profile)


def _resolve_mcp_tool_profile(params: dict[str, Any]) -> dict[str, Any]:
    profile = "core-read"
    source = "default"
    degraded_reason = None

    requested_profile = params.get("mcp_tool_profile") or params.get("profile")
    if not requested_profile and isinstance(params.get("arguments"), dict):
        requested_profile = params["arguments"].get("mcp_tool_profile")
    if requested_profile:
        normalized = _normalize_mcp_tool_profile(requested_profile)
        if normalized is None:
            degraded_reason = "invalid_requested_profile"
        else:
            profile = normalized
            source = "request"
            degraded_reason = None

    env_profile = os.environ.get("HARNESS_MEM_MCP_TOOL_PROFILE")
    if env_profile:
        normalized = _normalize_mcp_tool_profile(env_profile)
        if normalized is None:
            degraded_reason = "invalid_env_profile"
        else:
            profile = normalized
            source = "env"

    project_name = _profile_project_name(params)
    project_profile = _project_profile_mcp_tool_profile(project_name)
    if project_profile is not None:
        profile = project_profile
        source = "project_profile"
        degraded_reason = None

    return {
        "profile": profile,
        "source": source,
        "project_name": project_name,
        "degraded_reason": degraded_reason,
    }


# =============================================================================
# JSON-RPC REQUEST HANDLER
# =============================================================================

SUPPORTED_PROTOCOL_VERSIONS = [
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
]


def handle_request(request: dict) -> dict | None:
    method = request.get("method") or ""
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "harness-mem",
                    "version": _HARNESS_MEM_VERSION,
                    **runtime_version_payload(),
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method.startswith("notifications/"):
        # Notifications carry no id — per JSON-RPC spec they get no response
        return None

    if method == "tools/list":
        profile_info = _resolve_mcp_tool_profile(params)
        profile = profile_info["profile"]
        visible_names = visible_tool_names(TOOLS, profile)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "profile": profile,
                "profile_source": profile_info["source"],
                "profile_project_name": profile_info["project_name"],
                "degraded_reason": profile_info["degraded_reason"],
                "tool_count": len(visible_names),
                "total_tool_count": len(TOOLS),
                "hidden_tool_count": len(TOOLS) - len(visible_names),
                "tools": [
                    tool_descriptor(name, TOOLS[name], profile)
                    for name in visible_names
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        profile_info = _resolve_mcp_tool_profile(params)
        profile = profile_info["profile"]
        visible_for_profile = visible_tool_name_set(TOOLS, profile)
        if tool_name not in visible_for_profile:
            return hidden_tool_error(req_id, str(tool_name), profile)
        profile_enforcement: dict[str, Any] | None = None
        if (
            profile not in {"full", "review-write"}
            and tool_name == "auto_review_candidates"
            and bool(tool_args.get("apply"))
        ):
            tool_args = dict(tool_args)
            tool_args["apply"] = False
            profile_enforcement = {
                "profile": profile,
                "reason": "auto_review_apply_requires_review_write_profile",
                "requested_apply": True,
                "effective_apply": False,
            }

        # Whitelist arguments to declared schema properties
        import inspect

        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        try:
            handler = TOOLS[tool_name]["handler"]
            sig = inspect.signature(handler)
            accepts_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (ValueError, TypeError):
            accepts_var_keyword = False

        if not accepts_var_keyword:
            tool_args = {k: v for k, v in tool_args.items() if k in schema_props}

        # Coerce integer/float types per schema
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            try:
                if declared_type == "integer" and not isinstance(value, int):
                    tool_args[key] = int(value)
                elif declared_type == "number" and not isinstance(value, (int, float)):
                    tool_args[key] = float(value)
            except (ValueError, TypeError):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid value for parameter '{key}'"},
                }

        try:
            started_at = time.perf_counter()
            result = TOOLS[tool_name]["handler"](**tool_args)
            if profile_enforcement is not None and isinstance(result, dict):
                result["profile_enforcement"] = profile_enforcement
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            try:
                observe_mcp_surface_cost(
                    data_dir=_observer_data_dir(),
                    tool_name=tool_name,
                    arguments=tool_args,
                    result=result,
                    duration_ms=duration_ms,
                    surface_budgets=_cost_surface_budgets(
                        _project_name_for_cost(tool_args, result)
                    ),
                )
            except Exception:
                logger.exception("MCP surface cost observer failed for %s", tool_name)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception as exc:
            # Full traceback to stderr for postmortem; concise class+message
            # surfaced to the client so an agent can debug without SSH-ing
            # to the MCP server's logs. We deliberately keep this short:
            # leaking the full traceback over JSON-RPC could expose
            # filesystem paths or third-party stack frames.
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {
                    "code": -32000,
                    "message": f"Internal tool error in {tool_name}: {exc.__class__.__name__}: {exc}",
                },
            }

    # Notifications (missing id) must never get a response
    if req_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


# =============================================================================
# STDOUT RESTORATION + MAIN LOOP
# =============================================================================


def _restore_stdout():
    """Restore real stdout for MCP JSON-RPC output."""
    global _REAL_STDOUT_FD
    if _REAL_STDOUT_FD is not None:
        try:
            os.dup2(_REAL_STDOUT_FD, 1)
        except OSError:
            pass
        finally:
            try:
                os.close(_REAL_STDOUT_FD)
            except OSError:
                pass
        _REAL_STDOUT_FD = None
    try:
        sys.stdout = os.fdopen(
            os.dup(1),
            "w",
            buffering=1,
            encoding=_REAL_STDOUT_ENCODING,
            errors=_REAL_STDOUT_ERRORS,
        )
    except OSError:
        sys.stdout = sys.__stdout__


def main():
    _restore_stdout()
    logger.info("harness-mem MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
