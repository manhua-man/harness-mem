"""Recent-context index for session-start wake output.

This view is intentionally derived from existing transcript observations. It
does not claim that a transcript has been distilled into confirmed truth; it
gives a new session a compact, drillable index of recent work first.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from harness_mem.core.schemas.context_assembly_plan import ContextAssemblyPlan
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

DEFAULT_RECENT_CONTEXT_LIMIT = 20
CHARS_PER_TOKEN_ESTIMATE = 4

_TYPE_ICONS = {
    "bugfix": "*",
    "feature": "+",
    "refactor": "~",
    "change": "✓",
    "discovery": "o",
    "decision": "⚖",
    "session": "@",
}
_PATH_PATTERN = re.compile(
    r"(?:[A-Za-z]:[\\\\/]|(?:\\.\\.?[\\\\/])|(?:[\\w.-]+[\\\\/]))[^\\s,;:)]+"
)


@dataclass(frozen=True)
class RecentContextItem:
    """One compact, drillable item in the recent work index."""

    observation_id: str
    session_id: str
    timestamp: datetime
    client: str
    title: str
    summary: str
    kind: str
    read_tokens: int
    work_tokens: int
    files: tuple[str, ...]

    @property
    def display_id(self) -> str:
        return f"O-{self.observation_id[:8]}"


@dataclass(frozen=True)
class RecentContextIndex:
    project_name: str
    items: tuple[RecentContextItem, ...]
    total_read_tokens: int
    total_work_tokens: int


async def build_recent_context(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    limit: int = DEFAULT_RECENT_CONTEXT_LIMIT,
) -> RecentContextIndex:
    """Build a recent index from project-scoped transcript observations."""

    observations = await backend.verbatim_store.list(
        limit=max(limit, 1),
        project_name=project_name,
    )
    project_observations = [
        observation for observation in observations if not observation.compacted
    ]
    project_observations.sort(key=lambda observation: observation.timestamp, reverse=True)
    items = tuple(
        _observation_to_item(observation)
        for observation in project_observations[: max(0, limit)]
    )
    return RecentContextIndex(
        project_name=project_name,
        items=items,
        total_read_tokens=sum(item.read_tokens for item in items),
        total_work_tokens=sum(item.work_tokens for item in items),
    )


def render_recent_context(
    index: RecentContextIndex,
    plan: ContextAssemblyPlan,
    *,
    compact: bool = True,
) -> str:
    """Render a human-readable or agent-compact recent-context packet."""

    lines = [
        f"# [{index.project_name}] recent context",
        "",
        (
            f"Stats: {len(index.items)} observations | "
            f"~{index.total_read_tokens:,}t read | "
            f"{index.total_work_tokens:,}t work preserved"
        ),
        "",
    ]
    if not compact:
        lines[1:1] = [
            "Legend: @ session  * bugfix  + feature  ~ refactor  ✓ change  "
            "o discovery  ⚖ decision",
            "",
            "Context Index: recent work is summarized here; fetch details by ID.",
            "",
        ]

    if not index.items:
        lines.append("No previous work has been recorded for this workspace yet.")
    else:
        grouped: dict[str, list[RecentContextItem]] = defaultdict(list)
        for item in reversed(index.items):
            grouped[_format_day(item.timestamp)].append(item)
        for day, day_items in grouped.items():
            lines.append(day)
            for item in day_items:
                icon = _TYPE_ICONS.get(item.kind, _TYPE_ICONS["session"])
                time_text = item.timestamp.astimezone().strftime("%H:%M")
                source = f" [{item.client}]" if item.client else ""
                lines.append(
                    f"  {item.display_id}  {time_text}  {icon}  {item.title}{source}"
                )
                if not compact and item.files:
                    lines.append(f"    files: {', '.join(item.files[:3])}")
                if not compact and item.summary and item.summary != item.title:
                    lines.append(f"    {item.summary}")
            lines.append("")

    active_entries = _plan_entries(plan, "L2")
    if active_entries:
        lines.extend(["Active", ""])
        lines.extend(
            f"  H-{entry.source_ids[0][:8]}  {entry.summary}"
            for entry in active_entries[:3]
        )
        lines.append("")

    truth_entries = _plan_entries(plan, "L1")
    if truth_entries:
        lines.extend(["Stable truths", ""])
        lines.extend(
            f"  R-{entry.source_ids[0][:8]}  {entry.summary}"
            for entry in truth_entries[:3]
        )
        lines.append("")

    if index.items:
        ids = ", ".join(f'"{item.observation_id}"' for item in index.items[:8])
        lines.append(f"Details: get_observations(observation_ids=[{ids}])")
        lines.append(
            "Search: search_memory(query=...)"
            if compact
            else "Search history: search_memory(query=...)"
        )

    return "\n".join(lines).rstrip()


def _observation_to_item(observation: Observation) -> RecentContextItem:
    raw_content = observation.raw_content.strip()
    title = (
        _first_user_line(raw_content)
        or _first_content_line(raw_content)
        or observation.session_id
    )
    title = _clean_text(title, 120)
    summary = _clean_text(_first_content_line(raw_content) or title, 220)
    metadata = observation.metadata or {}
    kind = str(metadata.get("observation_type") or "session").strip().lower()
    if kind not in _TYPE_ICONS:
        kind = "session"
    files = _extract_files(metadata, raw_content)
    read_tokens = max(1, math.ceil(len(raw_content) / CHARS_PER_TOKEN_ESTIMATE))
    work_tokens = _integer_metadata(metadata, "work_tokens", "discovery_tokens")
    timestamp = observation.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return RecentContextItem(
        observation_id=observation.id,
        session_id=observation.session_id,
        timestamp=timestamp,
        client=observation.client,
        title=title,
        summary=summary,
        kind=kind,
        read_tokens=read_tokens,
        work_tokens=work_tokens,
        files=files,
    )


def _first_user_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip()
        if cleaned.lower().startswith("user:"):
            return cleaned.split(":", 1)[1].strip()
    return ""


def _first_content_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = line.strip().lstrip("#").strip()
        if not cleaned or cleaned.lower().startswith(("user:", "assistant:", "tools:")):
            continue
        if cleaned.lower().endswith("session:") or " session: " in cleaned.lower():
            continue
        return cleaned
    return ""


def _extract_files(metadata: dict[str, Any], raw_content: str) -> tuple[str, ...]:
    values: list[str] = []
    for key in ("files", "files_read", "files_modified"):
        value = metadata.get(key)
        if isinstance(value, str):
            values.append(value)
        elif isinstance(value, list):
            values.extend(str(item) for item in value if item)
    if not values:
        values.extend(match.rstrip(".,") for match in _PATH_PATTERN.findall(raw_content))
    return tuple(dict.fromkeys(values))[:5]


def _integer_metadata(metadata: dict[str, Any], *keys: str) -> int:
    for key in keys:
        try:
            return max(0, int(metadata.get(key) or 0))
        except (TypeError, ValueError):
            continue
    return 0


def _clean_text(value: str, limit: int) -> str:
    value = " ".join(value.split())
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "..."


def _format_day(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d")


def _plan_entries(plan: ContextAssemblyPlan, layer_id: str) -> list[Any]:
    try:
        layer = plan.layer(layer_id)  # type: ignore[arg-type]
    except ValueError:
        return []
    return [entry for entry in layer.entries if entry.source_ids]


__all__ = [
    "DEFAULT_RECENT_CONTEXT_LIMIT",
    "RecentContextIndex",
    "RecentContextItem",
    "build_recent_context",
    "render_recent_context",
]
