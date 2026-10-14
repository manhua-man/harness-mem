"""Structural text validation; semantic quality belongs to the active Agent."""

from __future__ import annotations


def validate_atomic_knowledge_statement(value: str) -> str:
    """Normalize prose without guessing its meaning from words or punctuation.

    Keep the existing callable for provider/runtime compatibility. Whether a
    statement represents one useful fact is an Agent decision, not a comma,
    conjunction, action-word or domain-keyword quota.
    """
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError("knowledge statement must not be empty")
    return normalized


__all__ = ["validate_atomic_knowledge_statement"]
