"""SearchBackend contract for v4.0.3 index-fabric runtime surfaces."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal, Protocol

from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


SearchMode = Literal["auto", "fts", "hybrid"]


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
    """SearchBackend adapter over the existing SQLite FTS/vector stores."""

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
        entry_limit = max(1, limit)
        observation_limit = max(1, limit)
        include_history = filters.include_history or filters.deep_recall
        entries, observations = await search_memory(
            self.backend,
            project_name=filters.project_name,
            query=query,
            scope=filters.scope,
            mode=mode,
            memory_entry_limit=entry_limit,
            observation_limit=observation_limit,
            memory_type=filters.memory_type,
            include_history=include_history,
            deep_recall=filters.deep_recall,
            time_window=filters.time_window,
            record_signals=False,
        )
        results: list[BackendSearchResult] = []
        allowed_tiers = set(filters.tier or _default_tiers(filters.deep_recall))
        allowed_truth = set(filters.truth_status or [])
        for entry in entries:
            tier = str(getattr(entry, "tier", "hot") or "hot")
            truth_status = "historical" if getattr(entry, "valid_to", None) else str(getattr(entry, "status", "accepted"))
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
                        "tier": tier,
                        "memory_type": getattr(entry, "memory_type", None),
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
                    },
                )
            )
        truncated = len(results) > limit
        selected = results[:limit]
        effective_mode = _effective_mode(selected, mode)
        return SearchBackendResponse(
            query=query,
            requested_mode=mode,
            effective_mode=effective_mode,
            results=selected,
            fallback_metadata={
                "backend": "sqlite",
                "requested_mode": mode,
                "effective_mode": effective_mode,
                "fallback_reason": _fallback_reason(selected),
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
                {
                    "source_id": result.source_id,
                    "source_kind": result.source_kind,
                    "read_surface": _read_surface(result.source_kind),
                }
                for result in selected
            ],
        )


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


def _estimate_tokens(results: list[BackendSearchResult]) -> int:
    chars = sum(len(result.preview) for result in results)
    return max(1, chars // 4) if results else 0


def _read_surface(source_kind: str) -> str:
    if source_kind == "observation":
        return "read_api.get_observations"
    return "read_api.get_memory_entry"


__all__ = [
    "BackendSearchResult",
    "SearchBackend",
    "SearchBackendResponse",
    "SearchFilters",
    "SQLiteSearchBackend",
]
