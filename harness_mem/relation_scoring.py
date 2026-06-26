"""Typed relation scoring for explainable relation tracing.

This is a small, local-first adaptation of the useful Core-Memory idea:
relations are not all equivalent. A causal edge should influence recall more
than a generic association, and reviewed/manual provenance should outrank a
low-confidence heuristic hint.
"""

from __future__ import annotations

import math
from typing import Any


RELATION_TYPE_WEIGHTS: dict[str, float] = {
    "caused_by": 0.95,
    "causes": 0.95,
    "led_to": 0.92,
    "results_in": 0.92,
    "enables": 0.88,
    "unblocks": 0.86,
    "blocked_by": 0.84,
    "blocks": 0.84,
    "resolves": 0.84,
    "diagnoses": 0.84,
    "supersedes": 0.82,
    "superseded_by": 0.82,
    "contradicts": 0.80,
    "invalidates": 0.80,
    "supports": 0.76,
    "derived_from": 0.74,
    "refines": 0.72,
    "depends_on": 0.70,
    "part_of": 0.64,
    "follows": 0.52,
    "precedes": 0.52,
    "associated_with": 0.48,
    "related_to": 0.45,
}

CAUSAL_RELATION_TYPES: frozenset[str] = frozenset(
    {
        "caused_by",
        "causes",
        "led_to",
        "results_in",
        "enables",
        "resolves",
        "diagnoses",
    }
)

DEFAULT_RELATION_WEIGHT = 0.55
HOP_DECAY = 0.82


def normalize_relation_type(value: str | None) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def relation_type_weight(value: str | None) -> float:
    return RELATION_TYPE_WEIGHTS.get(
        normalize_relation_type(value),
        DEFAULT_RELATION_WEIGHT,
    )


def _provenance_factor(provenance: Any, source: str | None = None) -> float:
    text = ""
    if isinstance(provenance, dict):
        text = " ".join(
            str(provenance.get(key) or "")
            for key in ("source", "kind", "agent_type", "tool_name", "confidence_class")
        )
    elif provenance is not None:
        text = str(provenance)
    text = f"{text} {source or ''}".strip().lower()
    if any(marker in text for marker in ("manual", "user", "confirmed", "review")):
        return 1.0
    if any(marker in text for marker in ("llm", "distill", "agent")):
        return 0.85
    if any(marker in text for marker in ("heuristic", "regex", "fallback")):
        return 0.65
    return 0.75


def score_relation_fact(fact: Any, *, depth: int = 1) -> float:
    """Return a bounded score for one relation fact at traversal depth."""

    relation_type = getattr(fact, "relation_type", None)
    confidence = max(0.0, min(1.0, float(getattr(fact, "confidence", 0.7) or 0.0)))
    provenance = getattr(fact, "provenance", None)
    source = getattr(fact, "source", "")
    depth_multiplier = HOP_DECAY ** max(0, depth - 1)
    return round(
        relation_type_weight(relation_type)
        * confidence
        * _provenance_factor(provenance, source)
        * depth_multiplier,
        6,
    )


def score_relation_path(facts: list[Any] | tuple[Any, ...]) -> float:
    """Score a path as normalized accumulated edge evidence.

    A one-hop causal edge is useful, but a complete two-hop chain carries more
    attribution evidence. Normalize by sqrt(depth) so longer paths are rewarded
    for coverage without letting arbitrary length dominate.
    """

    if not facts:
        return 0.0
    total = sum(
        score_relation_fact(fact, depth=index)
        for index, fact in enumerate(facts, start=1)
    )
    return round(min(1.0, total / math.sqrt(len(facts))), 6)


def relation_family(value: str | None) -> str:
    rel = normalize_relation_type(value)
    if rel in CAUSAL_RELATION_TYPES:
        return "causal"
    if rel in {"supersedes", "superseded_by", "contradicts", "invalidates"}:
        return "truth_revision"
    if rel in {"supports", "derived_from", "refines", "depends_on"}:
        return "support"
    if rel in {"follows", "precedes"}:
        return "temporal"
    return "association"


__all__ = [
    "CAUSAL_RELATION_TYPES",
    "DEFAULT_RELATION_WEIGHT",
    "HOP_DECAY",
    "RELATION_TYPE_WEIGHTS",
    "normalize_relation_type",
    "relation_family",
    "relation_type_weight",
    "score_relation_fact",
    "score_relation_path",
]
