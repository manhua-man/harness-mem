"""Shared vocabulary for the post-verification memory decision."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ReviewEvidence(BaseModel):
    """Exact quote in a point's typed reference, supplied to manual finalization."""

    model_config = ConfigDict(extra="forbid")

    ref: int = Field(ge=1, strict=True)
    target: Literal["claim", "condition", "undecided_state"]
    condition: str | None = None
    quote: str = Field(min_length=1, max_length=2000)
    message_index: int | None = Field(default=None, ge=1, strict=True)


class ReviewOperation(BaseModel):
    """Claim and exact, paired native call/result passages for an observed operation."""

    model_config = ConfigDict(extra="forbid")

    ref: int = Field(ge=1, strict=True)
    phrase: str = Field(min_length=4, max_length=600)
    observed_as: Literal["inspection", "execution", "interaction"]
    call_id: str = Field(min_length=1, max_length=180)
    call_line: int = Field(ge=1, strict=True)
    result_line: int = Field(ge=1, strict=True)
    call_quote: str = Field(min_length=1, max_length=2000)
    result_quote: str = Field(min_length=1, max_length=2000)


class AgentKnowledgeReview(BaseModel):
    """A current Agent's content judgment, separate from runtime-owned bindings.

    This is one semantic review, not a second independent verification. The
    runtime supplies exact output bytes, source identities and target versions.
    Conditions are literal phrases in the final statement so their retention
    can be checked without asking the Agent to copy entire statements twice.
    """

    model_config = ConfigDict(extra="forbid")

    support: Literal["supported", "partial", "contradicted", "unclear"]
    use: Literal["standing_decision", "reusable_knowledge", "explicit_undecided", "task_context", "unclear"]
    reason: str = Field(min_length=8, max_length=1000)
    conditions: list[str]
    undecided_state: str | None
    preserves_meaning: bool | None = Field(default=None, strict=True)
    same_topic: bool | None = Field(default=None, strict=True)
    evidence: list[ReviewEvidence] | None = Field(default=None, min_length=1, max_length=64)
    operations: list[ReviewOperation] = Field(default_factory=list, max_length=12)

    @field_validator("reason", "undecided_state")
    @classmethod
    def nonempty_line(cls, value: str | None) -> str | None:
        if value is not None and (not value.strip() or "\n" in value or "\r" in value):
            raise ValueError("knowledge review values must be nonempty single lines")
        return value.strip() if value is not None else None

    @field_validator("conditions")
    @classmethod
    def condition_lines(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or "\n" in value or "\r" in value for value in values):
            raise ValueError("knowledge review conditions must be nonempty single lines")
        return [value.strip() for value in values]


AssimilationDisposition = Literal[
    "add",
    "refine",
    "confirm",
    "replace",
    "no_write",
    "handoff",
    "defer",
    "conflict",
    "reject",
]


__all__ = ["AssimilationDisposition", "AgentKnowledgeReview"]
