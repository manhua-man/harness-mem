"""A bounded report of what a source speaker said, never external truth."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class SourceReport(BaseModel):
    """Runtime-bound attribution retained with current knowledge.

    The source identity is private revalidation metadata. ``period`` is a native
    source-session timestamp, not the exact time of each cited utterance.
    The readable statement
    retains speaker, period and source scope even in ordinary compact retrieval.
    A missing native date is explicitly unknown, not the capture time.
    """

    speaker: Literal["user", "assistant"]
    period: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    exchange_indexes: list[int] = Field(min_length=1)
    text: str = Field(min_length=1)

    model_config = {"extra": "forbid"}

    @field_validator("period", "session_id", "source_id", "source_revision", "text")
    @classmethod
    def single_line(cls, value: str) -> str:
        if not value.strip() or "\n" in value or "\r" in value:
            raise ValueError("source-report fields must be nonempty single lines")
        return value.strip()

    @field_validator("exchange_indexes")
    @classmethod
    def valid_exchanges(cls, value: list[int]) -> list[int]:
        if any(index < 1 for index in value) or len(value) != len(set(value)):
            raise ValueError("source-report exchanges must be distinct positive indexes")
        return sorted(value)

    def render_statement(self) -> str:
        return (
            f"Source-scoped report — {self.speaker}, source-session timestamp: {self.period}, "
            f"in that session's cited exchanges: {self.text} "
            "[Reports that speaker's account only; not independently established "
            "current fact or user approval.]"
        )

    def render_title(self) -> str:
        return f"Source report — {self.speaker} account (source-session timestamp: {self.period})"

    def same_account_source(self, other: SourceReport) -> bool:
        """A later complete revision may update this speaker's same source account."""
        return (
            self.speaker == other.speaker
            and self.period == other.period
            and self.session_id == other.session_id
            and self.source_id == other.source_id
        )


__all__ = ["SourceReport"]
