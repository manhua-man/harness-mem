"""Job-time source input for knowledge assimilation.

Markdown documents are projections, not schemas or persistence authorities.
This module intentionally contains no project-document, parser, or write-back
model.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


def _single_line(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    if "\n" in normalized or "\r" in normalized:
        raise ValueError(f"{field_name} must be a single line")
    return normalized


class ProjectKnowledgeSourceRef(BaseModel):
    """Readable job input before conversion to a durable knowledge source."""

    label: str = Field(min_length=1)
    target: str = Field(min_length=1)
    kind: str | None = None
    digest: str | None = None

    model_config = {"extra": "forbid"}

    @field_validator("label", "target")
    @classmethod
    def normalize_required_line(cls, value: str, info) -> str:
        return _single_line(value, field_name=info.field_name)

    @field_validator("kind", "digest")
    @classmethod
    def normalize_optional_line(cls, value: str | None, info) -> str | None:
        if value is None:
            return None
        return _single_line(value, field_name=info.field_name)


__all__ = ["ProjectKnowledgeSourceRef"]
