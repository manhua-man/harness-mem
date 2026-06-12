"""v4.1 context sufficiency and task-aware wake schemas."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from harness_mem.search.backend import BackendSearchResult, SearchBackendResponse


SufficiencyStatus = Literal["sufficient", "partial", "insufficient"]
SupportLevel = Literal["direct", "inferential", "weak", "missing"]


class MetadataFilter(BaseModel):
    project_id: str | None = None
    corpus_id: str | None = None
    types: list[str] = Field(default_factory=list)
    truth_status: list[str] = Field(default_factory=list)
    tiers: list[str] = Field(default_factory=list)
    valid_from: str | None = None
    valid_to: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MetadataFilter":
        return cls(**data)


class CorpusProfile(BaseModel):
    corpus_id: str
    description: str = ""
    domain: str = ""
    entities: list[str] = Field(default_factory=list)
    time_range: dict[str, str | None] = Field(default_factory=dict)
    source_types: list[str] = Field(default_factory=list)
    trust_level: str = "local"
    metadata_schema: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CorpusProfile":
        return cls(**data)


class RetrievalPlan(BaseModel):
    query: str
    classifier: str = "simple"
    corpora: list[str] = Field(default_factory=list)
    skipped_corpora: list[dict[str, str]] = Field(default_factory=list)
    filters: MetadataFilter = Field(default_factory=MetadataFilter)
    budget_tokens: int = 6000
    mode: str = "auto"
    max_rounds: int = 2
    reasons: list[str] = Field(default_factory=list)
    query_rewrites: list[str] = Field(default_factory=list)
    quality_gates: list[str] = Field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["filters"] = self.filters.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalPlan":
        data = dict(data)
        if isinstance(data.get("filters"), dict):
            data["filters"] = MetadataFilter.from_dict(data["filters"])
        return cls(**data)


class SufficiencyReport(BaseModel):
    status: SufficiencyStatus
    support_level: SupportLevel
    missing_evidence: list[str] = Field(default_factory=list)
    safe_to_answer: bool
    recommended_action: list[str] = Field(default_factory=list)
    covered: list[str] = Field(default_factory=list)
    conflicting: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    next_queries: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SufficiencyReport":
        return cls(**data)


class RetrievalRound(BaseModel):
    round: int
    query: str
    corpus_ids: list[str] = Field(default_factory=list)
    filters: MetadataFilter = Field(default_factory=MetadataFilter)
    result_count: int = 0
    sufficiency_status: SufficiencyStatus = "insufficient"

    def to_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        data["filters"] = self.filters.to_dict()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RetrievalRound":
        data = dict(data)
        if isinstance(data.get("filters"), dict):
            data["filters"] = MetadataFilter.from_dict(data["filters"])
        return cls(**data)


class IterativeRetrievalTrace(BaseModel):
    rounds: list[RetrievalRound] = Field(default_factory=list)
    max_rounds: int = 2
    stopped_reason: str = "not_started"
    budget_remaining: int | None = None
    retrieval_quality: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rounds": [round_item.to_dict() for round_item in self.rounds],
            "max_rounds": self.max_rounds,
            "stopped_reason": self.stopped_reason,
            "budget_remaining": self.budget_remaining,
            "retrieval_quality": dict(self.retrieval_quality),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "IterativeRetrievalTrace":
        data = dict(data)
        data["rounds"] = [
            RetrievalRound.from_dict(item) if isinstance(item, dict) else item
            for item in list(data.get("rounds") or [])
        ]
        return cls(**data)


class WakePacket(BaseModel):
    budget_tokens: int = 6000
    hard_include: list[str] = Field(default_factory=list)
    soft_include: list[str] = Field(default_factory=list)
    evict_first: list[str] = Field(default_factory=list)
    why_included: list[dict[str, str]] = Field(default_factory=list)
    why_omitted: list[dict[str, str]] = Field(default_factory=list)
    budget_trace: dict[str, Any] = Field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump()


class ContextPlan(BaseModel):
    project_name: str
    query: str | None = None
    source_ids: list[str] = Field(default_factory=list)
    why_included: list[dict[str, str]] = Field(default_factory=list)
    why_omitted: list[dict[str, str]] = Field(default_factory=list)
    drilldown_hints: list[dict[str, Any]] = Field(default_factory=list)
    wake_packet: WakePacket
    context_sufficiency: SufficiencyReport
    retrieval_plan: RetrievalPlan
    iterative_retrieval_trace: IterativeRetrievalTrace
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_name": self.project_name,
            "query": self.query,
            "source_ids": list(self.source_ids),
            "why_included": list(self.why_included),
            "why_omitted": list(self.why_omitted),
            "drilldown_hints": list(self.drilldown_hints),
            "wake_packet": self.wake_packet.to_dict(),
            "context_sufficiency": self.context_sufficiency.to_dict(),
            "retrieval_plan": self.retrieval_plan.to_dict(),
            "iterative_retrieval_trace": self.iterative_retrieval_trace.to_dict(),
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ContextPlan":
        data = dict(data)
        if isinstance(data.get("created_at"), str):
            data["created_at"] = datetime.fromisoformat(data["created_at"])
        if isinstance(data.get("wake_packet"), dict):
            data["wake_packet"] = WakePacket(**data["wake_packet"])
        if isinstance(data.get("context_sufficiency"), dict):
            data["context_sufficiency"] = SufficiencyReport.from_dict(
                data["context_sufficiency"]
            )
        if isinstance(data.get("retrieval_plan"), dict):
            data["retrieval_plan"] = RetrievalPlan.from_dict(data["retrieval_plan"])
        if isinstance(data.get("iterative_retrieval_trace"), dict):
            data["iterative_retrieval_trace"] = IterativeRetrievalTrace.from_dict(
                data["iterative_retrieval_trace"]
            )
        return cls(**data)


def build_retrieval_plan(
    *,
    query: str,
    project_name: str | None,
    corpus_profiles: list[CorpusProfile] | None = None,
    metadata_filter: MetadataFilter | None = None,
    budget_tokens: int = 6000,
    mode: str = "auto",
    deep_recall: bool = False,
) -> RetrievalPlan:
    classifier = classify_query(query)
    filters = metadata_filter or MetadataFilter(project_id=project_name)
    if not filters.tiers:
        filters.tiers = ["hot", "warm", "cold", "archive"] if deep_recall else ["hot", "warm"]
    corpora = [profile.corpus_id for profile in corpus_profiles or []]
    if not corpora:
        corpora = [filters.corpus_id or "default"]
    reasons = ["simple query uses current hybrid search"]
    if classifier != "simple":
        reasons = ["multi-hop or cross-corpus query uses local retrieval planner"]
    if deep_recall:
        reasons.append("deep recall includes cold/archive lifecycle tiers")
    return RetrievalPlan(
        query=query,
        classifier=classifier,
        corpora=corpora,
        filters=filters,
        budget_tokens=budget_tokens,
        mode=mode,
        reasons=reasons,
        query_rewrites=deterministic_query_rewrites(query, classifier=classifier),
        quality_gates=[
            "entity_coverage",
            "source_diversity",
            "truth_status",
            "top_k_cliff",
            "required_slots",
        ],
    )


def classify_query(query: str) -> str:
    lowered = query.lower()
    if any(marker in lowered for marker in (" latest ", " current ", " changed ", " after ", " before ")):
        return "temporal"
    if any(marker in lowered for marker in (" across ", " compare ", " versus ", " vs ")):
        return "cross_corpus"
    if any(marker in lowered for marker in (" and ", " then ", " why ", " root cause")):
        return "multi_hop"
    return "simple"


def deterministic_query_rewrites(query: str, *, classifier: str | None = None) -> list[str]:
    """Return bounded local rewrites used for audit, not silent truth mutation."""
    normalized = " ".join(query.split())
    kind = classifier or classify_query(normalized)
    rewrites = [normalized]
    if kind in {"multi_hop", "cross_corpus"}:
        parts = re.split(r"\b(?:and|then|versus|vs|compare|across)\b", normalized, flags=re.I)
        rewrites.extend(part.strip(" ,;:") for part in parts if len(part.strip()) >= 3)
    if kind == "temporal" and "current" not in normalized.lower():
        rewrites.append(f"current {normalized}")
    deduped: list[str] = []
    for item in rewrites:
        if item and item not in deduped:
            deduped.append(item)
    return deduped[:4]


def evaluate_sufficiency(
    *,
    query: str,
    results: list[BackendSearchResult],
    required_slots: list[str] | None = None,
) -> SufficiencyReport:
    tokens = _query_tokens(query)
    required = required_slots or []
    if not results:
        missing = required or ["no matching memory evidence"]
        return SufficiencyReport(
            status="insufficient",
            support_level="missing",
            missing_evidence=missing,
            safe_to_answer=False,
            recommended_action=["expand_observations", "ask_user"],
            confidence=0.0,
            next_queries=[query],
            checks={
                "entity_coverage": 0.0,
                "source_diversity": 0,
                "top_k_cliff": None,
                "conflict_count": 0,
            },
        )
    covered_tokens = _covered_tokens(tokens, results)
    coverage = _coverage(tokens, covered_tokens)
    source_kinds = {result.source_kind for result in results}
    conflicts = _conflicts(results)
    missing = _missing_required_slots(required, results)
    if conflicts:
        status: SufficiencyStatus = "partial"
        support: SupportLevel = "weak"
    elif coverage >= 0.75 and len(source_kinds) >= 1 and not missing:
        status = "sufficient"
        support = "direct"
    elif coverage >= 0.4:
        status = "partial"
        support = "inferential"
    else:
        status = "insufficient"
        support = "weak"
    safe = status == "sufficient" and not conflicts
    actions: list[str] = []
    if not safe:
        actions.append("answer_with_caveat" if status == "partial" else "ask_user")
    if missing or status == "insufficient":
        actions.append("expand_observations")
    return SufficiencyReport(
        status=status,
        support_level=support,
        missing_evidence=missing,
        safe_to_answer=safe,
        recommended_action=actions,
        covered=sorted(covered_tokens),
        conflicting=conflicts,
        confidence=round(min(1.0, coverage), 3),
        next_queries=[] if safe else [_next_query(query, missing)],
        checks={
            "entity_coverage": round(coverage, 3),
            "source_diversity": len(source_kinds),
            "top_k_cliff": _top_k_cliff(results),
            "conflict_count": len(conflicts),
            "required_slots": required,
            "missing_required_slots": missing,
        },
    )


def context_plan_from_response(
    *,
    project_name: str,
    response: SearchBackendResponse,
    retrieval_plan: RetrievalPlan,
    sufficiency: SufficiencyReport | None = None,
    iterative_trace: IterativeRetrievalTrace | None = None,
) -> ContextPlan:
    report = sufficiency or evaluate_sufficiency(
        query=response.query,
        results=response.results,
    )
    used_tokens = int(response.budget.get("estimated_tokens") or 0)
    budget_tokens = retrieval_plan.budget_tokens
    included = [
        {"source_id": result.source_id, "reason": _include_reason(result)}
        for result in response.results
        if used_tokens <= budget_tokens or result.source_kind != "observation"
    ]
    omitted = []
    if response.truncation.get("truncated"):
        omitted.append(
            {
                "source_id": "truncated-results",
                "reason": "result limit or budget reached",
            }
        )
    packet = WakePacket(
        budget_tokens=budget_tokens,
        hard_include=[
            result.source_id
            for result in response.results
            if result.metadata.get("truth_status") in {"accepted", "confirmed_current"}
        ],
        soft_include=[
            result.source_id
            for result in response.results
            if result.metadata.get("truth_status") not in {"accepted", "confirmed_current"}
        ],
        evict_first=["stale truths", "low-support summaries", "repeated handoffs"],
        why_included=included,
        why_omitted=omitted,
        budget_trace={
            "requested": budget_tokens,
            "used": used_tokens,
            "truncated": bool(response.truncation.get("truncated")),
            "available": response.truncation.get("available", len(response.results)),
        },
    )
    return ContextPlan(
        project_name=project_name,
        query=response.query,
        source_ids=[result.source_id for result in response.results],
        why_included=included,
        why_omitted=omitted,
        drilldown_hints=response.drilldown_hints,
        wake_packet=packet,
        context_sufficiency=report,
        retrieval_plan=retrieval_plan,
        iterative_retrieval_trace=iterative_trace or IterativeRetrievalTrace(
            stopped_reason="sufficient" if report.safe_to_answer else "budget_or_evidence_limit"
        ),
    )


def retrieval_round_from_response(
    response: SearchBackendResponse,
    *,
    round_number: int,
    retrieval_plan: RetrievalPlan,
    sufficiency: SufficiencyReport,
) -> RetrievalRound:
    return RetrievalRound(
        round=round_number,
        query=response.query,
        corpus_ids=list(retrieval_plan.corpora),
        filters=retrieval_plan.filters,
        result_count=len(response.results),
        sufficiency_status=sufficiency.status,
    )


def _query_tokens(query: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[A-Za-z0-9_]+", query.lower())
        if len(token) >= 3
    }


def _covered_tokens(
    tokens: set[str],
    results: list[BackendSearchResult],
) -> set[str]:
    if not tokens:
        return set()
    haystack = " ".join(result.preview.lower() for result in results)
    return {token for token in tokens if token in haystack}


def _coverage(tokens: set[str], covered_tokens: set[str]) -> float:
    if not tokens:
        return 1.0
    return len(covered_tokens) / len(tokens)


def _missing_required_slots(
    required: list[str],
    results: list[BackendSearchResult],
) -> list[str]:
    missing: list[str] = []
    for slot in required:
        slot_tokens = _query_tokens(slot)
        if not slot_tokens:
            continue
        covered = _covered_tokens(slot_tokens, results)
        if len(covered) / len(slot_tokens) < 0.6:
            missing.append(slot)
    return missing


def _conflicts(results: list[BackendSearchResult]) -> list[str]:
    historical = {
        result.source_id
        for result in results
        if result.metadata.get("truth_status") == "historical"
    }
    current = {
        result.source_id
        for result in results
        if result.metadata.get("truth_status") in {"accepted", "confirmed_current"}
    }
    if historical and current:
        return ["current and historical truth both surfaced"]
    return []


def _top_k_cliff(results: list[BackendSearchResult]) -> float | None:
    if len(results) < 2:
        return None
    first = results[0].score
    second = results[1].score
    if first is None or second is None or second == 0:
        return None
    return round(float(first) / max(abs(float(second)), 0.0001), 3)


def _next_query(query: str, missing: list[str]) -> str:
    if missing:
        return f"{query} {' '.join(missing)}"
    return query


def _include_reason(result: BackendSearchResult) -> str:
    if result.source_kind == "memory_entry":
        return "task/query matched confirmed memory"
    if result.source_kind == "observation":
        return "raw evidence supports recall"
    return "retrieval result selected"


__all__ = [
    "ContextPlan",
    "CorpusProfile",
    "IterativeRetrievalTrace",
    "MetadataFilter",
    "RetrievalPlan",
    "RetrievalRound",
    "SufficiencyReport",
    "WakePacket",
    "build_retrieval_plan",
    "classify_query",
    "context_plan_from_response",
    "deterministic_query_rewrites",
    "evaluate_sufficiency",
    "retrieval_round_from_response",
]
