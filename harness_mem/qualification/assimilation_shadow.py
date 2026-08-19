"""Read-only golden-corpus checks for the planned assimilation boundary.

This module deliberately has no dependency on a backend, provider, or store.
It originated as the 0.9.13 safety contract without changing the then-current
write path: a fixture point receives one proposed disposition, while the
returned report proves that no canonical mutation was attempted.

It is not the semantic absorber planned for 0.9.14.  Fixture authors provide
the already-reviewed relationship to current truth; this module verifies the
non-negotiable routing and safety invariants around that relationship.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence


AnswerStatus = Literal[
    "ANSWERED",
    "PARTIAL",
    "UNANSWERED",
    "CONTRADICTED",
    "STALE",
    "NOT_APPLICABLE",
]
Disposition = Literal[
    "add",
    "refine",
    "confirm",
    "supersede",
    "no_write",
    "handoff",
    "defer",
    "conflict",
    "reject",
]
TruthRelationship = Literal[
    "new",
    "equivalent",
    "refines",
    "supersedes",
    "conflicts",
]


@dataclass(frozen=True)
class ShadowPoint:
    """A reviewed promotion point used only by the 0.9.13 golden corpus."""

    id: str
    answer_status: AnswerStatus
    title: str
    statement: str
    long_term_utility: bool
    relationship: TruthRelationship = "new"
    matched_truth_id: str | None = None
    route: Literal["memory", "handoff"] = "memory"
    rule_has_condition: bool = True
    rule_has_required_behavior: bool = True

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ShadowPoint":
        return cls(
            id=str(value["id"]),
            answer_status=str(value["answer_status"]),  # type: ignore[arg-type]
            title=str(value.get("title") or ""),
            statement=str(value.get("statement") or ""),
            long_term_utility=bool(value.get("long_term_utility")),
            relationship=str(value.get("relationship") or "new"),  # type: ignore[arg-type]
            matched_truth_id=(
                str(value["matched_truth_id"])
                if value.get("matched_truth_id") is not None
                else None
            ),
            route=str(value.get("route") or "memory"),  # type: ignore[arg-type]
            rule_has_condition=bool(value.get("rule_has_condition", True)),
            rule_has_required_behavior=bool(
                value.get("rule_has_required_behavior", True)
            ),
        )


@dataclass(frozen=True)
class ShadowDisposition:
    candidate_id: str
    disposition: Disposition
    matched_truth_ids: tuple[str, ...]
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "disposition": self.disposition,
            "matched_truth_ids": list(self.matched_truth_ids),
            "reason": self.reason,
        }


@dataclass(frozen=True)
class ShadowReport:
    """A proposed plan. ``mutation_count`` is always zero by construction."""

    fixture_id: str
    dispositions: tuple[ShadowDisposition, ...]
    forbidden_write_ids: tuple[str, ...]
    mutation_count: Literal[0] = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "dispositions": [item.to_dict() for item in self.dispositions],
            "forbidden_write_ids": list(self.forbidden_write_ids),
            "mutation_count": self.mutation_count,
        }


_MATCH_REQUIRED = frozenset({"equivalent", "refines", "supersedes", "conflicts"})


def propose_disposition(
    point: ShadowPoint,
    *,
    current_truth_ids: Sequence[str],
) -> ShadowDisposition:
    """Apply deterministic no-write-first boundaries to one reviewed point."""

    available_truth = {str(value) for value in current_truth_ids}
    matched = (point.matched_truth_id,) if point.matched_truth_id else ()
    if point.answer_status in {"CONTRADICTED", "STALE"}:
        return _result(point, "reject", (), "evidence is contradicted or stale")
    if point.answer_status == "NOT_APPLICABLE":
        return _result(point, "no_write", (), "evidence does not establish durable truth")
    if point.answer_status == "PARTIAL":
        disposition: Disposition = "handoff" if point.route == "handoff" else "defer"
        return _result(point, disposition, (), "evidence is incomplete")
    if point.answer_status == "UNANSWERED":
        return _result(point, "no_write", (), "no qualifying evidence")
    if point.route == "handoff":
        return _result(point, "handoff", (), "point is an unfinished handoff")
    if not point.long_term_utility:
        return _result(point, "no_write", (), "content is task-local or audit navigation")
    if not point.title.strip() or not point.statement.strip():
        return _result(point, "reject", (), "canonical wording is incomplete")
    if not point.rule_has_condition or not point.rule_has_required_behavior:
        return _result(point, "reject", (), "rule needs condition and required behavior")
    if point.relationship in _MATCH_REQUIRED and (
        point.matched_truth_id is None or point.matched_truth_id not in available_truth
    ):
        return _result(point, "defer", (), "referenced current truth is unavailable")
    if point.relationship == "equivalent":
        return _result(point, "confirm", matched, "equivalent current truth already exists")
    if point.relationship == "refines":
        return _result(point, "refine", matched, "candidate is a compatible improvement")
    if point.relationship == "supersedes":
        return _result(point, "supersede", matched, "candidate is a verified temporal replacement")
    if point.relationship == "conflicts":
        return _result(point, "conflict", matched, "current truth cannot be reconciled safely")
    return _result(point, "add", (), "new durable project knowledge")


def shadow_fixture(value: Mapping[str, Any]) -> ShadowReport:
    """Evaluate a fixture without contacting a provider or persistent store."""

    current_truth_ids = tuple(
        str(item["id"])
        for item in value.get("current_truth", [])
        if isinstance(item, Mapping) and item.get("id")
    )
    points = [
        ShadowPoint.from_dict(item)
        for item in value.get("promotion_points", [])
        if isinstance(item, Mapping)
    ]
    dispositions = tuple(
        propose_disposition(point, current_truth_ids=current_truth_ids)
        for point in points
    )
    forbidden = tuple(str(item) for item in value.get("forbidden_write_ids", []))
    proposed_by_id = {item.candidate_id: item.disposition for item in dispositions}
    invalid_forbidden = [
        candidate_id
        for candidate_id in forbidden
        if proposed_by_id.get(candidate_id) not in {"no_write", "handoff", "defer", "conflict", "reject"}
    ]
    if invalid_forbidden:
        raise ValueError(
            "forbidden write points must remain non-mutating: "
            + ", ".join(invalid_forbidden)
        )
    return ShadowReport(
        fixture_id=str(value["fixture_id"]),
        dispositions=dispositions,
        forbidden_write_ids=forbidden,
    )


def project_clean_memory(value: Mapping[str, Any]) -> dict[str, str]:
    """Project a fixture truth record into the future default retrieval shape.

    This is a golden-corpus projection only. The production retrieval source
    switch remains a 0.9.15 change.
    """

    projected = {
        key: str(value[key]).strip()
        for key in ("title", "statement")
        if str(value.get(key) or "").strip()
    }
    for optional in ("scope", "freshness"):
        if str(value.get(optional) or "").strip():
            projected[optional] = str(value[optional]).strip()
    return projected


def _result(
    point: ShadowPoint,
    disposition: Disposition,
    matched_truth_ids: tuple[str, ...],
    reason: str,
) -> ShadowDisposition:
    return ShadowDisposition(
        candidate_id=point.id,
        disposition=disposition,
        matched_truth_ids=matched_truth_ids,
        reason=reason,
    )


__all__ = [
    "Disposition",
    "ShadowDisposition",
    "ShadowPoint",
    "ShadowReport",
    "project_clean_memory",
    "propose_disposition",
    "shadow_fixture",
]
