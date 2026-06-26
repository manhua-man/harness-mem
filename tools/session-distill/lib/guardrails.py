"""Pure guardrail helpers shared by session-distill modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from .models import ReadinessDecision

FORBIDDEN_DURABLE_WRITE_TOOLS = frozenset(
    {
        "confirm_candidate",
        "reject_candidate",
        "replace_candidate",
        "confirm_memory_entry",
        "reject_memory_entry",
        "confirm_rule",
        "reject_rule",
        "confirm_relation_fact",
        "reject_relation_fact",
        "auto_review_candidates",
        "direct_truth_write",
    }
)


def iter_dicts(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from iter_dicts(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_dicts(item)


def contains_pending_draft(payload: Any) -> bool:
    for item in iter_dicts(payload):
        for field in ("status", "review_status", "readiness"):
            if str(item.get(field, "")).lower() == "pending":
                return True
    return False


def is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def raw_deletion_root(path: Path, roots: Iterable[Path]) -> Path | None:
    for root in roots:
        if is_relative_to(path, root):
            return root
    return None


def suggest_only_violations(tool_names: Iterable[str]) -> list[str]:
    return [
        tool_name
        for tool_name in tool_names
        if tool_name in FORBIDDEN_DURABLE_WRITE_TOOLS
    ]


def can_auto_apply(decision: ReadinessDecision, *, review_apply: bool) -> bool:
    return review_apply and decision.auto_apply_allowed
