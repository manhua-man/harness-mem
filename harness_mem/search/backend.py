"""SearchBackend contract for the default SQLite runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Protocol

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.signal_influence import pull_recent_signals
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


SearchMode = Literal["auto", "fts", "hybrid"]

# v2.3.1 weak-link repeat-hit boost constants shared by backend and facade.
REPEAT_BOOST_BASE = 0.1
REPEAT_BOOST_WINDOW_DAYS = 7
REPEAT_BOOST_MIN_HITS = 2
CONTEXT_OUTCOME_WINDOW_DAYS = 30
CONTEXT_OUTCOME_MAX_ABS_SCORE = 0.2


def _optional_isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


@dataclass(frozen=True)
class SearchFilters:
    project_name: str | None = None
    scope: str = "project"
    memory_type: list[str] | None = None
    include_history: bool = False
    time_window: tuple[datetime | None, datetime | None] | None = None
    corpus_id: str | None = None
    tier: list[str] | None = None
    truth_status: list[str] | None = None
    deep_recall: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "scope": self.scope,
            "memory_type": list(self.memory_type or []),
            "include_history": self.include_history,
            "time_window": (
                {
                    "start": self.time_window[0].isoformat() if self.time_window and self.time_window[0] else None,
                    "end": self.time_window[1].isoformat() if self.time_window and self.time_window[1] else None,
                }
                if self.time_window
                else None
            ),
            "corpus_id": self.corpus_id,
            "tier": list(self.tier or []),
            "truth_status": list(self.truth_status or []),
            "deep_recall": self.deep_recall,
        }


@dataclass(frozen=True)
class BackendSearchResult:
    source_id: str
    source_kind: str
    score: float | None
    preview: str
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "score": self.score,
            "preview": self.preview,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class SearchBackendResponse:
    query: str
    requested_mode: str
    effective_mode: str
    results: list[BackendSearchResult]
    fallback_metadata: dict[str, Any]
    budget: dict[str, Any]
    truncation: dict[str, Any]
    source_coverage: dict[str, int]
    drilldown_hints: list[dict[str, Any]]
    retrieval_quality: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "requested_mode": self.requested_mode,
            "effective_mode": self.effective_mode,
            "results": [result.to_dict() for result in self.results],
            "fallback_metadata": dict(self.fallback_metadata),
            "budget": dict(self.budget),
            "truncation": dict(self.truncation),
            "source_coverage": dict(self.source_coverage),
            "drilldown_hints": list(self.drilldown_hints),
            "retrieval_quality": dict(self.retrieval_quality),
        }


class SearchBackend(Protocol):
    async def search(
        self,
        query: str,
        *,
        filters: SearchFilters,
        mode: SearchMode = "auto",
        limit: int = 20,
        budget_tokens: int | None = None,
    ) -> SearchBackendResponse:
        """Return unified search results with fallback and budget metadata."""


class SQLiteSearchBackend:
    """SearchBackend adapter over the local SQLite truth + derived indexes."""

    def __init__(self, backend: LocalMemoryBackend):
        self.backend = backend

    async def search(
        self,
        query: str,
        *,
        filters: SearchFilters,
        mode: SearchMode = "auto",
        limit: int = 20,
        budget_tokens: int | None = None,
    ) -> SearchBackendResponse:
        source_limit = max(1, limit)
        project_filter = None if filters.scope == "all" else filters.project_name
        include_history = filters.include_history or filters.deep_recall

        entries = await self.backend.structured_store.search_memory_entries(
            query,
            project_name=project_filter,
            limit=source_limit,
            mode=mode,
            memory_type=filters.memory_type,
            include_history=include_history,
            deep_recall=filters.deep_recall,
            time_window=filters.time_window,
        )
        entries = await _apply_signal_influence(
            self.backend,
            entries,
            project_filter,
        )
        observations = await self.backend.verbatim_store.search(
            query,
            project_name=project_filter,
            limit=source_limit,
            mode=mode,
            time_window=filters.time_window,
        )
        relation_facts = await self.backend.structured_store.search_relation_facts(
            query,
            project_name=project_filter,
            limit=source_limit,
            include_history=include_history,
            time_window=filters.time_window,
        )
        skills = await self.backend.structured_store.search_skills(
            query,
            project_name=project_filter,
            limit=min(source_limit, 10),
        )

        results: list[BackendSearchResult] = []
        allowed_tiers = set(filters.tier or _default_tiers(filters.deep_recall))
        allowed_truth = set(filters.truth_status or [])

        for entry in entries:
            tier = str(getattr(entry, "tier", "hot") or "hot")
            truth_status = _entry_truth_status(entry)
            if tier not in allowed_tiers:
                continue
            if allowed_truth and truth_status not in allowed_truth:
                continue
            if filters.corpus_id and getattr(entry, "corpus_id", None) != filters.corpus_id:
                continue
            results.append(
                BackendSearchResult(
                    source_id=entry.id,
                    source_kind="memory_entry",
                    score=_score(entry),
                    preview=_preview(entry.content),
                    metadata={
                        "project_name": entry.project_name,
                        "truth_status": truth_status,
                        **_temporal_metadata(
                            entry,
                            history_included_reason=_history_included_reason(filters),
                        ),
                        "tier": tier,
                        "memory_type": getattr(entry, "memory_type", None),
                        "corpus_id": getattr(entry, "corpus_id", None),
                        "search_mode": getattr(entry, "_search_mode", mode),
                        "search_requested_mode": getattr(entry, "_search_requested_mode", mode),
                        "fallback_reason": getattr(entry, "_search_fallback_reason", None),
                        "repeat_boost": getattr(entry, "_repeat_boost", 0.0) or 0.0,
                        "context_outcome_counts": getattr(
                            entry, "_context_outcome_counts", {}
                        ),
                        "context_outcome_score": getattr(
                            entry, "_context_outcome_score", 0.0
                        )
                        or 0.0,
                        "last_context_outcome_at": _optional_isoformat(
                            getattr(entry, "_last_context_outcome_at", None)
                        ),
                        "ranking_explanation": _ranking_explanation(entry),
                    },
                )
            )

        for fact in relation_facts:
            truth_status = "historical" if getattr(fact, "valid_to", None) else str(
                getattr(fact, "status", "accepted")
            )
            if allowed_truth and truth_status not in allowed_truth:
                continue
            results.append(
                BackendSearchResult(
                    source_id=fact.id,
                    source_kind="relation_fact",
                    score=_score(fact),
                    preview=_preview(
                        f"{fact.source_entity} {fact.relation_type} {fact.target_entity}"
                    ),
                    metadata={
                        "project_name": fact.project_name,
                        "truth_status": truth_status,
                        **_temporal_metadata(
                            fact,
                            history_included_reason=_history_included_reason(filters),
                        ),
                        "tier": "hot",
                        "search_mode": "fts",
                        "search_requested_mode": mode,
                        "fallback_reason": None,
                    },
                )
            )

        for skill in skills:
            results.append(
                BackendSearchResult(
                    source_id=skill.id,
                    source_kind="skill",
                    score=_score(skill),
                    preview=_preview(
                        f"skill {skill.id}: {skill.name} | when: {skill.activation_condition}"
                    ),
                    metadata={
                        "project_name": skill.project_name,
                        "truth_status": str(getattr(skill, "status", "active")),
                        "tier": "hot",
                        "search_mode": "fts",
                        "search_requested_mode": mode,
                        "fallback_reason": None,
                    },
                )
            )

        for observation in observations:
            corpus_id = observation.metadata.get("corpus_id")
            if filters.corpus_id and corpus_id != filters.corpus_id:
                continue
            results.append(
                BackendSearchResult(
                    source_id=observation.id,
                    source_kind="observation",
                    score=_score(observation),
                    preview=_preview(observation.raw_content),
                    metadata={
                        "project_name": observation.metadata.get("project_name"),
                        "truth_status": "raw",
                        "tier": "hot",
                        "corpus_id": corpus_id,
                        "search_mode": getattr(observation, "_search_mode", mode),
                        "search_requested_mode": getattr(observation, "_search_requested_mode", mode),
                        "fallback_reason": getattr(observation, "_search_fallback_reason", None),
                    },
                )
            )

        truncated = len(results) > limit
        selected = results[:limit]
        effective_mode = _effective_mode(selected, mode)
        fallback_reason = _fallback_reason(selected)
        return SearchBackendResponse(
            query=query,
            requested_mode=mode,
            effective_mode=effective_mode,
            results=selected,
            fallback_metadata={
                "backend": "sqlite",
                "requested_mode": mode,
                "effective_mode": effective_mode,
                "fallback_reason": fallback_reason,
                "index_fabric": "sqlite-default",
            },
            budget={
                "requested_tokens": budget_tokens,
                "estimated_tokens": _estimate_tokens(selected),
                "result_limit": limit,
            },
            truncation={
                "available": len(results),
                "included": len(selected),
                "dropped": max(0, len(results) - len(selected)),
                "truncated": truncated,
            },
            source_coverage=_source_coverage(selected),
            drilldown_hints=[
                _drilldown_hint(result, query)
                for result in selected
            ],
        )


class SearchFacade:
    """Stable read-path facade over a concrete SearchBackend.

    This is the product boundary for search return semantics. Storage/index
    implementations can change underneath it, but callers should receive the
    same source ids, kinds, project scope, evidence metadata, and fallback
    diagnostics.
    """

    def __init__(
        self,
        backend: LocalMemoryBackend,
        *,
        search_backend: SearchBackend | None = None,
    ) -> None:
        self.backend = backend
        self.search_backend = search_backend or SQLiteSearchBackend(backend)

    async def search(
        self,
        query: str,
        *,
        filters: SearchFilters,
        mode: SearchMode = "auto",
        limit: int = 20,
        budget_tokens: int | None = None,
    ) -> SearchBackendResponse:
        return await self.search_backend.search(
            query,
            filters=filters,
            mode=mode,
            limit=limit,
            budget_tokens=budget_tokens,
        )

    async def hydrate(
        self,
        response: SearchBackendResponse,
    ) -> dict[str, list[Any]]:
        return await hydrate_backend_results(self.backend, response)


async def hydrate_backend_results(
    backend: LocalMemoryBackend,
    response: SearchBackendResponse,
) -> dict[str, list[Any]]:
    """Hydrate typed source records from a backend response."""

    hydrated: dict[str, list[Any]] = {
        "memory_entry": [],
        "observation": [],
        "relation_fact": [],
        "skill": [],
    }
    for result in response.results:
        if result.source_kind == "memory_entry":
            entry = await backend.structured_store.get_memory_entry(result.source_id)
            if entry is None:
                continue
            _apply_result_metadata(entry, result, response)
            hydrated["memory_entry"].append(entry)
            continue
        if result.source_kind == "observation":
            observation = await backend.verbatim_store.get(result.source_id)
            if observation is None:
                continue
            _apply_result_metadata(observation, result, response)
            hydrated["observation"].append(observation)
            continue
        if result.source_kind == "relation_fact":
            fact = await backend.structured_store.get_relation_fact(result.source_id)
            if fact is None:
                continue
            _apply_result_metadata(fact, result, response)
            hydrated["relation_fact"].append(fact)
            continue
        if result.source_kind == "skill":
            skill = await backend.structured_store.get_skill(result.source_id)
            if skill is None:
                continue
            _apply_result_metadata(skill, result, response)
            hydrated["skill"].append(skill)
    return hydrated


def _apply_result_metadata(
    target: object,
    result: BackendSearchResult,
    response: SearchBackendResponse,
) -> None:
    search_mode = str(
        result.metadata.get("search_mode")
        or result.metadata.get("search_requested_mode")
        or response.effective_mode
    )
    setattr(target, "_search_mode", search_mode)
    setattr(
        target,
        "_search_requested_mode",
        str(result.metadata.get("search_requested_mode") or response.requested_mode),
    )
    setattr(
        target,
        "_search_fallback_reason",
        result.metadata.get("fallback_reason")
        or response.fallback_metadata.get("fallback_reason"),
    )
    if isinstance(result.score, (int, float)):
        setattr(target, "_score", float(result.score))
        if search_mode == "fts":
            setattr(target, "_fts_score", float(result.score))
        else:
            setattr(target, "_hybrid_score", float(result.score))
    repeat_boost = result.metadata.get("repeat_boost")
    if isinstance(repeat_boost, (int, float)) and repeat_boost:
        setattr(target, "_repeat_boost", float(repeat_boost))
    outcome_score = result.metadata.get("context_outcome_score")
    if isinstance(outcome_score, (int, float)) and outcome_score:
        setattr(target, "_context_outcome_score", float(outcome_score))
    outcome_counts = result.metadata.get("context_outcome_counts")
    if isinstance(outcome_counts, dict):
        setattr(target, "_context_outcome_counts", dict(outcome_counts))
    last_context_outcome_at = result.metadata.get("last_context_outcome_at")
    if isinstance(last_context_outcome_at, str) and last_context_outcome_at:
        try:
            setattr(
                target,
                "_last_context_outcome_at",
                datetime.fromisoformat(last_context_outcome_at),
            )
        except ValueError:
            pass
    ranking_explanation = result.metadata.get("ranking_explanation")
    if isinstance(ranking_explanation, list):
        setattr(target, "_ranking_explanation", list(ranking_explanation))
    history_included_reason = result.metadata.get("history_included_reason")
    if isinstance(history_included_reason, str) and history_included_reason:
        setattr(target, "_history_included_reason", history_included_reason)


async def _apply_signal_influence(
    backend: LocalMemoryBackend,
    entries: list[MemoryEntry],
    project_name: str | None,
) -> list[MemoryEntry]:
    if not entries or not project_name:
        return entries

    profile = await LocalProjectProfileStore(backend.data_dir).get(project_name)
    if profile is None or not profile.weak_link_signals:
        return entries

    now = datetime.now(timezone.utc)
    repeat_summaries = await pull_recent_signals(
        backend,
        project_name=project_name,
        target_ids=[entry.id for entry in entries],
        since=now - timedelta(days=REPEAT_BOOST_WINDOW_DAYS),
    )
    outcome_summaries = await pull_recent_signals(
        backend,
        project_name=project_name,
        target_ids=[entry.id for entry in entries],
        since=now - timedelta(days=CONTEXT_OUTCOME_WINDOW_DAYS),
    )

    for entry in entries:
        summary = repeat_summaries.get(entry.id)
        if summary and summary.search_hit_count >= REPEAT_BOOST_MIN_HITS:
            _boost_entry(entry, REPEAT_BOOST_BASE)
        outcome_summary = outcome_summaries.get(entry.id)
        if outcome_summary is None:
            continue
        outcome_score = _clamp(
            outcome_summary.context_outcome_score,
            -CONTEXT_OUTCOME_MAX_ABS_SCORE,
            CONTEXT_OUTCOME_MAX_ABS_SCORE,
        )
        setattr(
            entry,
            "_context_outcome_counts",
            dict(outcome_summary.context_outcome_counts),
        )
        setattr(entry, "_context_outcome_score", outcome_score)
        setattr(
            entry,
            "_last_context_outcome_at",
            outcome_summary.last_context_outcome_at,
        )
        if outcome_score:
            _apply_score_delta(entry, outcome_score)

    if any(hasattr(entry, "_hybrid_score") for entry in entries):
        entries.sort(key=lambda item: getattr(item, "_hybrid_score", 0.0), reverse=True)
    elif any(hasattr(entry, "_score") for entry in entries):
        entries.sort(key=lambda item: getattr(item, "_score", 0.0), reverse=True)
    return entries


def _boost_entry(entry: MemoryEntry, boost: float) -> None:
    for attr in ("_hybrid_score", "_score"):
        current = getattr(entry, attr, None)
        if isinstance(current, (int, float)):
            setattr(entry, attr, float(current) + boost)
            break
    setattr(entry, "_repeat_boost", boost)


def _apply_score_delta(entry: MemoryEntry, delta: float) -> None:
    for attr in ("_hybrid_score", "_score"):
        current = getattr(entry, attr, None)
        if isinstance(current, (int, float)):
            setattr(entry, attr, float(current) + delta)
            return
    setattr(entry, "_score", delta)


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _ranking_explanation(entry: MemoryEntry) -> list[dict[str, Any]]:
    explanations: list[dict[str, Any]] = []
    repeat_boost = getattr(entry, "_repeat_boost", 0.0) or 0.0
    if isinstance(repeat_boost, (int, float)) and repeat_boost:
        explanations.append(
            {
                "kind": "repeat_search_hit",
                "score_delta": float(repeat_boost),
                "source": "RetrievalSignal.search_hit",
                "window_days": REPEAT_BOOST_WINDOW_DAYS,
            }
        )
    outcome_score = getattr(entry, "_context_outcome_score", 0.0) or 0.0
    if isinstance(outcome_score, (int, float)) and outcome_score:
        explanations.append(
            {
                "kind": "context_outcome",
                "score_delta": float(outcome_score),
                "source": "RetrievalSignal.context_outcome",
                "window_days": CONTEXT_OUTCOME_WINDOW_DAYS,
                "counts": getattr(entry, "_context_outcome_counts", {}),
            }
        )
    return explanations


def _history_included_reason(filters: SearchFilters) -> str | None:
    if filters.include_history:
        return "include_history=true"
    if filters.deep_recall:
        return "deep_recall=true"
    return None


def _temporal_scope(record: object) -> str:
    valid_to = getattr(record, "valid_to", None)
    is_historical = isinstance(valid_to, datetime) and valid_to <= datetime.now(timezone.utc)
    if not is_historical:
        return "current"
    if list(getattr(record, "superseded_by", []) or []):
        return "superseded"
    return "historical"


def _temporal_metadata(
    record: object,
    *,
    history_included_reason: str | None,
) -> dict[str, Any]:
    scope = _temporal_scope(record)
    is_historical = scope in {"historical", "superseded"}
    metadata: dict[str, Any] = {
        "temporal_scope": scope,
        "is_historical": is_historical,
        "valid_from": _optional_isoformat(getattr(record, "valid_from", None)),
        "valid_to": _optional_isoformat(getattr(record, "valid_to", None)),
        "recorded_at": _optional_isoformat(getattr(record, "recorded_at", None)),
        "supersedes": list(getattr(record, "supersedes", []) or []),
        "superseded_by": list(getattr(record, "superseded_by", []) or []),
    }
    if is_historical and history_included_reason:
        metadata["history_included_reason"] = history_included_reason
    return metadata


def _entry_truth_status(entry: MemoryEntry) -> str:
    if getattr(entry, "valid_to", None):
        return "historical"
    return str(getattr(entry, "status", "accepted"))


def _default_tiers(deep_recall: bool) -> list[str]:
    if deep_recall:
        return ["hot", "warm", "cold", "archive"]
    return ["hot", "warm"]


def _score(value: object) -> float | None:
    for attr in ("_score", "_hybrid_score", "_fts_score"):
        score = getattr(value, attr, None)
        if isinstance(score, (int, float)):
            return float(score)
    return None


def _preview(text: str, *, max_chars: int = 200) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 1].rstrip() + "..."


def _effective_mode(results: list[BackendSearchResult], requested: str) -> str:
    for result in results:
        mode = result.metadata.get("search_mode")
        if isinstance(mode, str) and mode:
            return mode
    return requested


def _fallback_reason(results: list[BackendSearchResult]) -> str | None:
    for result in results:
        reason = result.metadata.get("fallback_reason")
        if isinstance(reason, str) and reason:
            return reason
    return None


def _source_coverage(results: list[BackendSearchResult]) -> dict[str, int]:
    coverage: dict[str, int] = {}
    for result in results:
        coverage[result.source_kind] = coverage.get(result.source_kind, 0) + 1
    return coverage


def _drilldown_hint(result: BackendSearchResult, query: str) -> dict[str, Any]:
    hint: dict[str, Any] = {
        "source_id": result.source_id,
        "source_kind": result.source_kind,
        "read_surface": _read_surface(result.source_kind),
    }
    temporal_scope = result.metadata.get("temporal_scope")
    if isinstance(temporal_scope, str):
        hint["temporal_scope"] = temporal_scope

    if result.source_kind in {"memory_entry", "relation_fact"}:
        project_name = result.metadata.get("project_name")
        mode = "history" if temporal_scope in {"historical", "superseded"} else "current"
        hint.update(
            {
                "tool": "temporal_query",
                "arguments": {
                    "project_name": project_name,
                    "query": query,
                    "truth_type": result.source_kind,
                    "mode": mode,
                    "limit": 20,
                },
                "why": (
                    "Use temporal_query to inspect current/history/as_of semantics "
                    "for this structured truth hit."
                ),
            }
        )
        if result.metadata.get("valid_to"):
            hint["valid_to"] = result.metadata["valid_to"]
        if result.metadata.get("superseded_by"):
            hint["superseded_by"] = list(result.metadata["superseded_by"])
    return hint


def _estimate_tokens(results: list[BackendSearchResult]) -> int:
    chars = sum(len(result.preview) for result in results)
    return max(1, chars // 4) if results else 0


def _read_surface(source_kind: str) -> str:
    if source_kind == "observation":
        return "read_api.get_observations"
    if source_kind == "relation_fact":
        return "read_api.search_relation_facts"
    if source_kind == "skill":
        return "mcp.get_skill"
    return "read_api.get_memory_entry"


__all__ = [
    "BackendSearchResult",
    "CONTEXT_OUTCOME_MAX_ABS_SCORE",
    "CONTEXT_OUTCOME_WINDOW_DAYS",
    "REPEAT_BOOST_BASE",
    "REPEAT_BOOST_MIN_HITS",
    "REPEAT_BOOST_WINDOW_DAYS",
    "SearchBackend",
    "SearchBackendResponse",
    "SearchFacade",
    "SearchFilters",
    "SQLiteSearchBackend",
    "hydrate_backend_results",
]
