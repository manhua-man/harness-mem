"""Read-only file-context helper for v2.5.2."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
import re

from harness_mem.commands.support import chars_to_tokens, disclosure_level, resolve_project_name
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.context_assembly_plan import DrilldownPointer
from harness_mem.core.schemas.file_context import (
    CostHint,
    FileContextItem,
    FileContextResult,
    FileContextTruthStatus,
    StaleFileSignal,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.read_api import regex_search_observations, search_memory, search_skills
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

_MAX_OBSERVATION_MATCHES = 25
_MAX_MEMORY_ENTRY_MATCHES = 50
_MAX_SKILL_MATCHES = 20
_MAX_HANDOFF_MATCHES = 50
_PATH_SEPARATOR = "/"
_MULTI_SLASH = re.compile(r"/+")


@dataclass(frozen=True)
class _PathQuery:
    raw: str
    normalized: str
    basename: str
    exact_needles: tuple[str, ...]


@dataclass
class _CollectedContext:
    items: list[FileContextItem] = field(default_factory=list)
    key_file_match: bool = False
    current_truth_timestamps: list[datetime] = field(default_factory=list)
    recent_edit_timestamps: list[datetime] = field(default_factory=list)

    def extend(self, other: "_CollectedContext") -> None:
        self.items.extend(other.items)
        self.key_file_match = self.key_file_match or other.key_file_match
        self.current_truth_timestamps.extend(other.current_truth_timestamps)
        self.recent_edit_timestamps.extend(other.recent_edit_timestamps)


async def build_file_context(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    path: str,
) -> FileContextResult:
    """Return a compact, source-attributed memory view for a file path."""
    resolved_project = resolve_project_name(
        project_name,
        required=False,
        action_label="file-context",
    )
    raw_path = path.strip()
    normalized_path = _normalize_path(raw_path)
    if not normalized_path:
        return FileContextResult(
            project_name=resolved_project,
            path=raw_path,
            normalized_path="",
            path_provided=False,
            notice="no path provided",
            items=[],
            cost_hint=CostHint(estimated_tokens=0, disclosure_level="L0"),
            stale_file_signal=StaleFileSignal(
                state="none",
                reason="no staleness detected",
            ),
        )
    if not resolved_project:
        raise ValueError(
            "project_name is required when no active project is set "
            "(pass project_name, set HARNESS_MEM_PROJECT, or set an active project)"
        )

    profile = await LocalProjectProfileStore(backend.data_dir).get(resolved_project)
    query = _prepare_query(raw_path, normalized_path, profile)

    collected = _CollectedContext()
    collected.extend(_collect_profile_key_file_matches(profile, query))
    collected.extend(await _collect_confirmed_rule_matches(backend, resolved_project, query))
    collected.extend(await _collect_memory_entry_matches(backend, resolved_project, query))
    collected.extend(await _collect_recent_handoff_matches(backend, resolved_project, query))
    collected.extend(await _collect_observation_matches(backend, resolved_project, query))
    collected.extend(await _collect_skill_hints(backend, resolved_project, query))

    return FileContextResult(
        project_name=resolved_project,
        path=raw_path,
        normalized_path=query.normalized,
        items=collected.items,
        cost_hint=_compute_cost_hint(collected.items),
        stale_file_signal=_compute_stale_signal(
            profile=profile,
            key_file_match=collected.key_file_match,
            items=collected.items,
            current_truth_timestamps=collected.current_truth_timestamps,
            recent_edit_timestamps=collected.recent_edit_timestamps,
        ),
    )


def _normalize_path(path: str) -> str:
    normalized = path.strip().replace("\\", _PATH_SEPARATOR)
    normalized = _MULTI_SLASH.sub(_PATH_SEPARATOR, normalized)
    if normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.rstrip(_PATH_SEPARATOR)


def _prepare_query(
    raw_path: str,
    normalized_path: str,
    profile: ProjectProfile | None,
) -> _PathQuery:
    exact_needles = {
        raw_path,
        normalized_path,
        normalized_path.replace(_PATH_SEPARATOR, "\\"),
    }
    normalized_query = normalized_path.lower()
    for key_file in profile.key_files if profile else []:
        normalized_key_file = _normalize_path(key_file)
        if not normalized_key_file:
            continue
        lowered = normalized_key_file.lower()
        if _same_path(normalized_query, lowered):
            exact_needles.add(normalized_key_file)
            exact_needles.add(normalized_key_file.replace(_PATH_SEPARATOR, "\\"))
    basename = normalized_path.split(_PATH_SEPARATOR)[-1]
    ordered_needles = tuple(
        sorted(
            {needle for needle in exact_needles if needle},
            key=len,
            reverse=True,
        )
    )
    return _PathQuery(
        raw=raw_path,
        normalized=normalized_path,
        basename=basename,
        exact_needles=ordered_needles,
    )


def _same_path(left: str, right: str) -> bool:
    return left == right or left.endswith(f"/{right}") or right.endswith(f"/{left}")


def _text_matches(text: str, query: _PathQuery) -> bool:
    lowered = text.lower()
    return any(needle.lower() in lowered for needle in query.exact_needles)


def _truncate_summary(text: str, *, max_chars: int = 200) -> str:
    stripped = text.strip()
    if len(stripped) <= max_chars:
        return stripped
    return stripped[: max_chars - 1].rstrip() + "\u2026"


def _collect_profile_key_file_matches(
    profile: ProjectProfile | None,
    query: _PathQuery,
) -> _CollectedContext:
    if profile is None or not profile.id:
        return _CollectedContext()

    items: list[FileContextItem] = []
    matched = False
    lowered_query = query.normalized.lower()
    for key_file in profile.key_files:
        normalized_key_file = _normalize_path(key_file)
        if not normalized_key_file or not _same_path(lowered_query, normalized_key_file.lower()):
            continue
        matched = True
        items.append(
            FileContextItem(
                kind="project_profile_key_file",
                source_ids=[profile.id],
                why_included="path_association:project_profile_key_file",
                summary=_truncate_summary(f"key file: {normalized_key_file}"),
                truth_status="reference",
            )
        )
    return _CollectedContext(items=items, key_file_match=matched)


async def _collect_observation_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    matches_by_id: dict[str, FileContextItem] = {}
    timestamps: list[datetime] = []
    for needle in query.exact_needles:
        matches = await regex_search_observations(
            backend,
            project_name=project_name,
            pattern=f"(?i){re.escape(needle)}",
            limit=_MAX_OBSERVATION_MATCHES,
        )
        for match in matches:
            observation = match.observation
            if not observation.id or observation.id in matches_by_id:
                continue
            timestamps.append(observation.timestamp)
            matches_by_id[observation.id] = FileContextItem(
                kind="observation",
                source_ids=[observation.id],
                why_included="recent_edit:observation",
                summary=_truncate_summary(match.snippet),
                truth_status="reference",
                drilldown=DrilldownPointer(
                    source_id=observation.id,
                    read_surface="read_api.get_observations",
                    locator={
                        "project_name": project_name,
                        "session_id": observation.session_id,
                    },
                ),
            )
    items = sorted(matches_by_id.values(), key=lambda item: item.source_ids[0])
    return _CollectedContext(items=items, recent_edit_timestamps=timestamps)


async def _collect_memory_entry_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    lookup_query = query.basename or query.normalized
    entries, _observations = await search_memory(
        backend,
        project_name=project_name,
        query=lookup_query,
        include_history=True,
        memory_entry_limit=_MAX_MEMORY_ENTRY_MATCHES,
        observation_limit=0,
        record_signals=False,
    )
    items: list[FileContextItem] = []
    timestamps: list[datetime] = []
    seen_ids: set[str] = set()
    for entry in entries:
        if not entry.id or entry.id in seen_ids or not _text_matches(entry.content, query):
            continue
        seen_ids.add(entry.id)
        truth_status: FileContextTruthStatus = (
            "historical" if entry.valid_to is not None else "confirmed_current"
        )
        if truth_status == "confirmed_current":
            timestamps.append(entry.recorded_at or entry.created_at)
        items.append(
            FileContextItem(
                kind="memory_entry",
                source_ids=[entry.id],
                why_included="path_association:memory_entry",
                summary=_truncate_summary(entry.content),
                truth_status=truth_status,
                drilldown=DrilldownPointer(
                    source_id=entry.id,
                    read_surface="read_api.get_memory_entry",
                    locator={"project_name": project_name},
                ),
            )
        )
    return _CollectedContext(items=items, current_truth_timestamps=timestamps)


async def _collect_confirmed_rule_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    rules: list[ConfirmedRule] = await backend.structured_store.list_confirmed_rules(
        project_name,
        include_history=True,
    )
    items: list[FileContextItem] = []
    timestamps: list[datetime] = []
    for rule in rules:
        if not rule.id:
            continue
        haystack = " ".join([rule.pattern, rule.trigger, *rule.examples])
        if not _text_matches(haystack, query):
            continue
        truth_status: FileContextTruthStatus = (
            "historical" if rule.valid_to is not None else "confirmed_current"
        )
        if truth_status == "confirmed_current":
            timestamps.append(rule.recorded_at or rule.confirmed_at)
        items.append(
            FileContextItem(
                kind="confirmed_rule",
                source_ids=[rule.id],
                why_included="path_association:confirmed_rule",
                summary=_truncate_summary(rule.pattern),
                truth_status=truth_status,
                drilldown=DrilldownPointer(
                    source_id=rule.id,
                    read_surface="mcp.get_confirmed_rules",
                    locator={"project_name": project_name},
                ),
            )
        )
    return _CollectedContext(items=items, current_truth_timestamps=timestamps)


async def _collect_recent_handoff_matches(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    handoffs: list[TaskHandoff] = await backend.structured_store.get_latest_handoffs(
        project_name,
        limit=_MAX_HANDOFF_MATCHES,
    )
    items: list[FileContextItem] = []
    timestamps: list[datetime] = []
    for handoff in handoffs:
        if not handoff.id:
            continue
        haystack = " ".join(
            [
                handoff.summary,
                " ".join(handoff.next_steps),
                " ".join(handoff.blockers),
                json.dumps(handoff.context, default=str, ensure_ascii=False),
            ]
        )
        if not _text_matches(haystack, query):
            continue
        timestamps.append(handoff.last_activity)
        items.append(
            FileContextItem(
                kind="task_handoff",
                source_ids=[handoff.id],
                why_included="recent_edit:task_handoff",
                summary=_truncate_summary(handoff.summary),
                truth_status="reference",
                drilldown=DrilldownPointer(
                    source_id=handoff.id,
                    read_surface="mcp.get_task_handoffs",
                    locator={"project_name": project_name},
                ),
            )
        )
    return _CollectedContext(items=items, recent_edit_timestamps=timestamps)


async def _collect_skill_hints(
    backend: LocalMemoryBackend,
    project_name: str,
    query: _PathQuery,
) -> _CollectedContext:
    lookup_query = query.basename or query.normalized
    skills: list[Skill] = await search_skills(
        backend,
        project_name=project_name,
        query=lookup_query,
        limit=_MAX_SKILL_MATCHES,
    )
    items: list[FileContextItem] = []
    seen_ids: set[str] = set()
    for skill in skills:
        if not skill.id or skill.id in seen_ids:
            continue
        if not _text_matches(f"{skill.name} {skill.activation_condition}", query):
            continue
        seen_ids.add(skill.id)
        items.append(
            FileContextItem(
                kind="skill_hint",
                source_ids=[skill.id],
                why_included="path_association:skill_hint",
                summary=_truncate_summary(
                    f"skill {skill.id}: {skill.name} | when: {skill.activation_condition}"
                ),
                truth_status="reference",
            )
        )
    return _CollectedContext(items=items)


def _compute_cost_hint(items: list[FileContextItem]) -> CostHint:
    chars = sum(len(item.summary) for item in items)
    estimated_tokens = chars_to_tokens(chars)
    return CostHint(
        estimated_tokens=estimated_tokens,
        disclosure_level=disclosure_level(estimated_tokens),
    )


def _compute_stale_signal(
    *,
    profile: ProjectProfile | None,
    key_file_match: bool,
    items: list[FileContextItem],
    current_truth_timestamps: list[datetime],
    recent_edit_timestamps: list[datetime],
) -> StaleFileSignal:
    has_confirmed_current = any(item.truth_status == "confirmed_current" for item in items)
    if (
        profile is not None
        and profile.key_files
        and not key_file_match
        and items
        and not has_confirmed_current
    ):
        return StaleFileSignal(
            state="historical_path_match",
            reason=(
                "current project key_files do not include this path, but older "
                "memory references were found"
            ),
        )
    if current_truth_timestamps and recent_edit_timestamps:
        newest_truth = max(current_truth_timestamps)
        newest_edit = max(recent_edit_timestamps)
        if newest_truth < newest_edit:
            return StaleFileSignal(
                state="newer_activity_exists",
                reason="newer path-associated activity exists after the stored truth",
            )
    return StaleFileSignal(
        state="none",
        reason="no staleness detected",
    )
