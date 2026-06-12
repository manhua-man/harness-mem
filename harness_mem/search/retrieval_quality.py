"""Optional v4.2 retrieval quality helpers.

The default runtime path stays lightweight: no reranker model is loaded and no
multi-query fanout happens for simple queries. These helpers only describe and
bound explicit quality-pack behavior so benchmark artifacts can audit it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, Sequence, TypeVar

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


__all__ = [
    "NoopReranker",
    "RetrievalQualityProfile",
    "RetrievalQualityTrace",
    "Reranker",
    "build_quality_trace",
    "build_query_variants",
    "duplicate_rate",
    "quality_profile_for_query",
]
