"""RecallResult schema - explainable retrieval contract.

The storage layer is already auditable; this contract makes the read path
auditable too. It is intentionally a response wrapper over existing wake,
search, trace, and context assembly surfaces rather than a new retrieval
engine.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


RECALL_RESULT_SCHEMA_VERSION = "harness_mem.recall_result.v1"

RecallStatus = Literal["answered", "partial", "empty", "failed"]
RecallEffort = Literal["low", "medium", "high", "dynamic"]


class RecallEvidence(BaseModel):
    """One selected memory/evidence item with its inclusion reason."""

    source_id: str
    source_kind: str
    content_excerpt: str = ""
    title: str = ""
    score: float | None = None
    reason: str = ""
    truth_status: str = "confirmed_current"
    source_ref: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RecallSource(BaseModel):
    """A source pointer that can be used for drilldown/hydration."""

    source_id: str
    source_kind: str
    read_surface: str = ""
    locator: dict[str, Any] = Field(default_factory=dict)
    availability: str = "available"
    label: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RecallStep(BaseModel):
    """Observable retrieval/planning step for debugging and audit."""

    tier: str
    query: str = ""
    status: str = ""
    result_count: int = 0
    why: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RecallPlanning(BaseModel):
    """Planner metadata explaining the selected read effort."""

    selected_effort: RecallEffort = "medium"
    reason: str = ""
    expected_shape: dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "allow"}


class RecallResult(BaseModel):
    """Stable explainable recall result shared by MCP, CLI, and tests."""

    answer: str | None = None
    why: str | None = None
    evidence: list[RecallEvidence] = Field(default_factory=list)
    sources: list[RecallSource] = Field(default_factory=list)
    steps: list[RecallStep] = Field(default_factory=list)
    planning: RecallPlanning = Field(default_factory=RecallPlanning)
    tier_path: list[str] = Field(default_factory=list)
    status: RecallStatus = "empty"
    warnings: list[str] = Field(default_factory=list)
    drilldown_hints: list[dict[str, Any]] = Field(default_factory=list)
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    schema_version: str = RECALL_RESULT_SCHEMA_VERSION
    contract: str = "harness_mem.recall_result"

    model_config = {"extra": "allow"}

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RecallResult":
        return cls(**dict(data or {}))


def validate_recall_effort(effort: str | None) -> RecallEffort:
    """Normalize public effort names."""

    normalized = str(effort or "medium").strip().lower()
    if normalized not in {"low", "medium", "high", "dynamic"}:
        raise ValueError("recall effort must be one of: low, medium, high, dynamic")
    return normalized  # type: ignore[return-value]


__all__ = [
    "RECALL_RESULT_SCHEMA_VERSION",
    "RecallEffort",
    "RecallEvidence",
    "RecallPlanning",
    "RecallResult",
    "RecallSource",
    "RecallStatus",
    "RecallStep",
    "validate_recall_effort",
]
