"""Optional v4.2 retrieval quality helpers.

The default runtime path stays lightweight: no reranker model is loaded and no
multi-query fanout happens for simple queries. These helpers only describe and
bound explicit quality-pack behavior so runtime traces can inspect it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, TypeVar

from harness_mem.core.schemas.context_sufficiency import deterministic_query_rewrites


T = TypeVar("T")


@dataclass(frozen=True)
class RetrievalQualityProfile:
    reranker_enabled: bool = False
    query_rewriting_enabled: bool = False
    multi_query_enabled: bool = False
    hyde_enabled: bool = False
    max_fanout: int = 1
    trigger: str = "default_light_path"

    def to_dict(self) -> dict:
        return {
            "reranker_enabled": self.reranker_enabled,
            "query_rewriting_enabled": self.query_rewriting_enabled,
            "multi_query_enabled": self.multi_query_enabled,
            "hyde_enabled": self.hyde_enabled,
            "max_fanout": self.max_fanout,
            "trigger": self.trigger,
        }


@dataclass(frozen=True)
class RetrievalQualityTrace:
    profile: RetrievalQualityProfile
    query_variants: list[str] = field(default_factory=list)
    fanout_count: int = 1
    duplicate_rate: float = 0.0
    reranker: str = "noop"
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile": self.profile.to_dict(),
            "query_variants": list(self.query_variants),
            "fanout_count": self.fanout_count,
            "duplicate_rate": self.duplicate_rate,
            "reranker": self.reranker,
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class RetrievalABReport:
    """Golden-suite A/B gate for retrieval ranking experiments."""

    baseline_name: str
    candidate_name: str
    baseline: dict[str, Any]
    candidate: dict[str, Any]
    deltas: dict[str, float]
    allowed_to_ship: bool
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "baseline_name": self.baseline_name,
            "candidate_name": self.candidate_name,
            "baseline": dict(self.baseline),
            "candidate": dict(self.candidate),
            "deltas": dict(self.deltas),
            "allowed_to_ship": self.allowed_to_ship,
            "reasons": list(self.reasons),
        }


class Reranker(Protocol[T]):
    def rerank(self, query: str, results: Sequence[T]) -> list[T]:
        """Return results sorted for the query without mutating the inputs."""


class NoopReranker(Reranker[T]):
    """Default reranker: preserves order and carries no model dependency."""

    def rerank(self, query: str, results: Sequence[T]) -> list[T]:
        return list(results)


def quality_profile_for_query(
    *,
    classifier: str,
    insufficient: bool = False,
    explicit_quality_pack: bool = False,
    max_fanout: int = 3,
) -> RetrievalQualityProfile:
    """Choose the bounded v4.2 quality profile for a query."""

    if not explicit_quality_pack and classifier == "simple" and not insufficient:
        return RetrievalQualityProfile(max_fanout=1)
    fanout = max(1, min(max_fanout, 4))
    trigger = "insufficiency" if insufficient else "explicit_quality_pack"
    if classifier in {"multi_hop", "cross_corpus", "temporal"}:
        trigger = f"{trigger}:{classifier}"
    return RetrievalQualityProfile(
        query_rewriting_enabled=True,
        multi_query_enabled=explicit_quality_pack or insufficient,
        max_fanout=fanout,
        trigger=trigger,
    )


def build_query_variants(
    query: str,
    *,
    classifier: str,
    insufficiency_queries: list[str] | None = None,
    profile: RetrievalQualityProfile | None = None,
) -> list[str]:
    profile = profile or quality_profile_for_query(classifier=classifier)
    normalized = " ".join(query.split())
    if not profile.query_rewriting_enabled and not insufficiency_queries:
        return [normalized]

    variants = deterministic_query_rewrites(normalized, classifier=classifier)
    variants.extend(insufficiency_queries or [])
    deduped: list[str] = []
    for variant in variants:
        compact = " ".join(str(variant).split())
        if compact and compact not in deduped:
            deduped.append(compact)
    return deduped[: profile.max_fanout]


def duplicate_rate(source_ids: Sequence[str]) -> float:
    if not source_ids:
        return 0.0
    unique = len(set(source_ids))
    duplicates = max(0, len(source_ids) - unique)
    return round(duplicates / len(source_ids), 3)


def build_quality_trace(
    *,
    query: str,
    classifier: str,
    source_ids: Sequence[str] = (),
    insufficient: bool = False,
    explicit_quality_pack: bool = False,
    insufficiency_queries: list[str] | None = None,
) -> RetrievalQualityTrace:
    profile = quality_profile_for_query(
        classifier=classifier,
        insufficient=insufficient,
        explicit_quality_pack=explicit_quality_pack,
    )
    variants = build_query_variants(
        query,
        classifier=classifier,
        insufficiency_queries=insufficiency_queries,
        profile=profile,
    )
    notes = ["default reranker is noop"]
    if profile.query_rewriting_enabled:
        notes.append("query variants are deterministic and fanout-capped")
    return RetrievalQualityTrace(
        profile=profile,
        query_variants=variants,
        fanout_count=len(variants),
        duplicate_rate=duplicate_rate(source_ids),
        notes=notes,
    )


def build_golden_ab_report(
    *,
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    baseline_name: str = "sqlite_fts_baseline",
    candidate_name: str = "adaptive_rrf_candidate",
) -> RetrievalABReport:
    """Compare two golden-suite reports before enabling a ranking candidate.

    This keeps adaptive IDF/RRF work behind an explicit, LLM-free benchmark
    gate. The candidate cannot ship if it loses recall, introduces forbidden
    hits/project leaks, or breaks vector-off fallback.
    """

    deltas = {
        "overall_recall_at_5": _metric(candidate, "overall_recall_at_5")
        - _metric(baseline, "overall_recall_at_5"),
        "project_leak_rate": _metric(candidate, "project_leak_rate")
        - _metric(baseline, "project_leak_rate"),
        "forbidden_hit_count": _metric(candidate, "forbidden_hit_count")
        - _metric(baseline, "forbidden_hit_count"),
        "p95_latency_ms": _metric(candidate, "p95_latency_ms")
        - _metric(baseline, "p95_latency_ms"),
    }
    reasons: list[str] = []
    if deltas["overall_recall_at_5"] < 0:
        reasons.append("candidate reduced overall_recall_at_5")
    if _metric(candidate, "project_leak_rate") > _metric(baseline, "project_leak_rate"):
        reasons.append("candidate increased project_leak_rate")
    if _metric(candidate, "forbidden_hit_count") > _metric(baseline, "forbidden_hit_count"):
        reasons.append("candidate increased forbidden_hit_count")
    if bool(baseline.get("vector_disabled")) and not bool(candidate.get("vector_disabled")):
        reasons.append("candidate broke vector-off fallback")
    if not bool(candidate.get("llm_free")):
        reasons.append("candidate is not llm_free")
    if not bool(candidate.get("read_path_only")):
        reasons.append("candidate is not read_path_only")

    return RetrievalABReport(
        baseline_name=baseline_name,
        candidate_name=candidate_name,
        baseline=baseline,
        candidate=candidate,
        deltas={key: round(value, 3) for key, value in deltas.items()},
        allowed_to_ship=not reasons,
        reasons=reasons,
    )


def _metric(report: dict[str, Any], key: str) -> float:
    value = report.get(key, 0.0)
    return float(value) if isinstance(value, (int, float)) else 0.0


__all__ = [
    "NoopReranker",
    "RetrievalQualityProfile",
    "RetrievalQualityTrace",
    "RetrievalABReport",
    "Reranker",
    "build_golden_ab_report",
    "build_quality_trace",
    "build_query_variants",
    "duplicate_rate",
    "quality_profile_for_query",
]
