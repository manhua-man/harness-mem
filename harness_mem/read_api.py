"""Shared read-path helpers used by CLI commands and the MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Sequence

from harness_mem.commands.retrieval_signals import record_retrieval_signal
from harness_mem.commands.signal_influence import pull_recent_signals
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.skill import Skill
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_verbatim_store import RegexObservationMatch

RELATION_TRACE_DEFAULT_DEPTH = 2
RELATION_TRACE_MAX_DEPTH = 3

# v2.3.1 weak-link signal application — search ranker boost. Gated on
# ``ProjectProfile.weak_link_signals`` (default off; same flag as the
# wake re-grouping in ``cmd_wake_up``, so users have one switch instead
# of two). Boost is additive on the hybrid score; the constant is a
# heuristic — first deployments use 0.1; v2.3.2 revisits if calibration
# data shows a need.
REPEAT_BOOST_BASE = 0.1
REPEAT_BOOST_WINDOW_DAYS = 7
REPEAT_BOOST_MIN_HITS = 2  # "repeat" = at least 2 hits in the window


@dataclass(frozen=True)
class ParsedTimeWindow:
    """A parsed relative query window with a cleaner query for FTS."""

    query: str
    start: datetime | None
    end: datetime | None
    phrase: str | None = None

    @property
    def time_window(self) -> tuple[datetime | None, datetime | None] | None:
        if self.start is None and self.end is None:
            return None
        return self.start, self.end


@dataclass(frozen=True)
class RelationPath:
    """A bounded relation traversal result."""

    facts: tuple[RelationFact, ...]

    @property
    def depth(self) -> int:
        return len(self.facts)

    @property
    def entities(self) -> list[str]:
        if not self.facts:
            return []
        entities = [self.facts[0].source_entity]
        entities.extend(fact.target_entity for fact in self.facts)
        return entities

    @property
    def confidence(self) -> float:
        if not self.facts:
            return 0.0
        return min(fact.confidence for fact in self.facts)


async def search_memory(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    mode: str = "auto",
    memory_entry_limit: int = 20,
    observation_limit: int = 20,
    memory_type: list[str] | None = None,
    include_history: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
    record_signals: bool = True,
) -> tuple[list[MemoryEntry], list[Observation]]:
    """Return structured and verbatim search results with shared filtering.

    v1.6.1: ``memory_type`` is an optional list filter on
    ``MemoryEntry.memory_type``. Multiple values are OR-ed; ``None`` / ``[]``
    means no filtering. Filter only applies to memory entries — observations
    have no memory_type concept.
    """
    if scope == "all":
        entries = await backend.structured_store.search_memory_entries(
            query,
            project_name=None,
            limit=memory_entry_limit,
            mode=mode,
            memory_type=memory_type,
            include_history=include_history,
            time_window=time_window,
        )
        observations = await backend.verbatim_store.search(
            query,
            limit=observation_limit,
            mode=mode,
            time_window=time_window,
        )
        # Cross-project search has no single profile → flag is implicitly
        # off, no boost. Keep the v2.2 ranking when ``scope == "all"``.
        if record_signals:
            await _emit_search_hit_signals(backend, entries, query)
        return entries, observations

    entries = await backend.structured_store.search_memory_entries(
        query,
        project_name,
        limit=memory_entry_limit,
        mode=mode,
        memory_type=memory_type,
        include_history=include_history,
        time_window=time_window,
    )
    observations = await backend.verbatim_store.search(
        query,
        project_name=project_name,
        limit=observation_limit,
        mode=mode,
        time_window=time_window,
    )
    # v2.3.1: apply repeat-search-hit boost before recording this query's
    # own search_hit signal so the current call doesn't double-count
    # against itself.
    entries = await _apply_repeat_boost(backend, entries, project_name)
    if record_signals:
        await _emit_search_hit_signals(backend, entries, query)
    return entries, observations


async def _emit_search_hit_signals(
    backend: LocalMemoryBackend,
    entries: Sequence[MemoryEntry],
    query: str,
) -> None:
    """Shadow-write one ``search_hit`` per memory entry returned to the user.

    Capped naturally by the caller's ``memory_entry_limit`` — we only iterate
    what already flowed back. Truncate the query to keep the signal context
    compact even if the user pastes a very long payload.
    """
    truncated_query = query[:200]
    for entry in entries:
        project = getattr(entry, "project_name", None)
        if not project:
            continue
        await record_retrieval_signal(
            backend,
            project_name=project,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=entry.id,
            context={"query": truncated_query},
        )


def _boost_entry(entry: MemoryEntry, boost: float) -> None:
    """Apply ``boost`` to whichever ranking score the entry carries.

    Hybrid mode populates both ``_hybrid_score`` and ``_score`` on the
    entry's ``model_extra``; vector-only mode populates ``_score``.
    FTS-only mode populates ``_fts_score`` (lower-is-better, sign
    inverted) which we deliberately leave alone — boosting it would
    require a sign flip and would mix BM25 with a fused ranker.

    Stashes the applied boost in ``_repeat_boost`` so doctor (task 4.4)
    can report how many entries got boosted in any given run.
    """
    for attr in ("_hybrid_score", "_score"):
        current = getattr(entry, attr, None)
        if isinstance(current, (int, float)):
            setattr(entry, attr, float(current) + boost)
            break
    setattr(entry, "_repeat_boost", boost)


async def _apply_repeat_boost(
    backend: LocalMemoryBackend,
    entries: list[MemoryEntry],
    project_name: str | None,
) -> list[MemoryEntry]:
    """Apply the v2.3.1 weak-link search boost to entries (in-place + reorder).

    Skips when:
    - ``entries`` is empty (nothing to do, no IO).
    - ``project_name`` is None — cross-project search has no single
      profile to read the flag from. ``scope == "all"`` callers in
      :func:`search_memory` short-circuit before reaching this helper;
      this guard is defense in depth for direct callers.
    - The profile doesn't exist or ``weak_link_signals`` is False.

    Returns the (possibly reordered) entries list. Re-sorts by the
    boosted ranking score so a user-visible reorder happens. Doesn't
    touch the observations list — this boost is entry-only by design.
    """
    if not entries or not project_name:
        return entries

    profile_store = LocalProjectProfileStore(backend.data_dir)
    profile = await profile_store.get(project_name)
    if profile is None or not profile.weak_link_signals:
        return entries

    now = datetime.now(timezone.utc)
    summaries = await pull_recent_signals(
        backend,
        project_name=project_name,
        target_ids=[entry.id for entry in entries],
        since=now - timedelta(days=REPEAT_BOOST_WINDOW_DAYS),
    )

    for entry in entries:
        summary = summaries.get(entry.id)
        if summary and summary.search_hit_count >= REPEAT_BOOST_MIN_HITS:
            _boost_entry(entry, REPEAT_BOOST_BASE)

    # Re-sort by whichever ranking field the search mode populated. FTS-only
    # mode (``_fts_score`` only, lower-is-better) doesn't get a boost above,
    # so its order is preserved here.
    if any(hasattr(e, "_hybrid_score") for e in entries):
        entries.sort(key=lambda e: getattr(e, "_hybrid_score", 0.0), reverse=True)
    elif any(hasattr(e, "_score") for e in entries):
        entries.sort(key=lambda e: getattr(e, "_score", 0.0), reverse=True)

    return entries


async def search_relation_facts(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    limit: int = 10,
    include_history: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
) -> list[RelationFact]:
    """Return relation facts matching the query with shared project scoping."""
    if scope == "all":
        return await backend.structured_store.search_relation_facts(
            query,
            project_name=None,
            limit=limit,
            include_history=include_history,
            time_window=time_window,
        )

    return await backend.structured_store.search_relation_facts(
        query,
        project_name=project_name,
        limit=limit,
        include_history=include_history,
        time_window=time_window,
    )


async def search_skills(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    limit: int = 10,
) -> list[Skill]:
    """Search confirmed procedural skills with shared project scoping."""
    if scope == "all":
        return await backend.structured_store.search_skills(
            query,
            project_name=None,
            limit=limit,
        )
    return await backend.structured_store.search_skills(
        query,
        project_name=project_name,
        limit=limit,
    )


def parse_relative_time_window(
    query: str,
    *,
    now: datetime | None = None,
) -> ParsedTimeWindow:
    """Parse a small, deterministic relative time phrase from a query.

    This intentionally handles a conservative set of English phrases. Unknown
    phrasing falls back to the original query and no time filter.
    """
    reference = _normalize_datetime(now) or datetime.now(timezone.utc)
    lowered = query.lower()
    specs: tuple[tuple[str, str], ...] = (
        ("yesterday", "yesterday"),
        ("last week", "last_week"),
        ("last month", "last_month"),
        ("two months ago", "months_ago:2"),
        ("2 months ago", "months_ago:2"),
        ("one month ago", "months_ago:1"),
        ("1 month ago", "months_ago:1"),
    )
    for phrase, spec in specs:
        if phrase not in lowered:
            continue
        start, end = _window_for_spec(spec, reference)
        cleaned = _clean_time_phrase(query, phrase)
        return ParsedTimeWindow(query=cleaned, start=start, end=end, phrase=phrase)
    return ParsedTimeWindow(query=query, start=None, end=None, phrase=None)


async def trace_relation_paths(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    source_entity: str,
    relation_type: str | None = None,
    max_depth: int = RELATION_TRACE_DEFAULT_DEPTH,
    limit: int = 10,
    min_confidence: float = 0.0,
    include_history: bool = False,
) -> list[RelationPath]:
    """Return bounded current relation paths starting at ``source_entity``."""
    if max_depth < 1:
        raise ValueError("max_depth must be >= 1")
    if max_depth > RELATION_TRACE_MAX_DEPTH:
        raise ValueError(f"max_depth must be <= {RELATION_TRACE_MAX_DEPTH}")

    paths: list[RelationPath] = []
    queue: list[tuple[str, tuple[RelationFact, ...], set[str]]] = [
        (source_entity, (), {source_entity})
    ]
    effective_limit = max(1, limit)
    while queue and len(paths) < effective_limit:
        current_entity, current_path, seen_entities = queue.pop(0)
        next_facts = await backend.structured_store.list_relation_facts(
            project_name,
            source_entity=current_entity,
            relation_type=relation_type,
            limit=effective_limit * 5,
            include_history=include_history,
        )
        next_facts = [
            fact for fact in next_facts
            if fact.confidence >= min_confidence and fact.target_entity not in seen_entities
        ]
        next_facts.sort(key=lambda fact: (fact.confidence, fact.created_at), reverse=True)
        for fact in next_facts:
            next_path = (*current_path, fact)
            paths.append(RelationPath(next_path))
            if len(paths) >= effective_limit:
                break
            if len(next_path) < max_depth:
                queue.append(
                    (
                        fact.target_entity,
                        next_path,
                        {*seen_entities, fact.target_entity},
                    )
                )
    return paths[:effective_limit]


async def timeline_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int = 50,
) -> list[Observation]:
    """Return a project-scoped observation timeline."""
    return await backend.verbatim_store.timeline(project_name=project_name, limit=limit)


async def regex_search_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    pattern: str,
    scope: str = "project",
    limit: int = 20,
) -> list[RegexObservationMatch]:
    """Return exact evidence matches from raw observation text."""
    effective_project = None if scope == "all" else project_name
    return await backend.verbatim_store.regex_search_observations(
        pattern,
        project_name=effective_project,
        limit=limit,
    )


async def resolve_observation_identifier(
    backend: LocalMemoryBackend,
    identifier: str,
    *,
    project_name: str | None = None,
) -> tuple[Observation | None, str | None]:
    """Resolve either an observation id or a unique session id."""
    observation = await backend.verbatim_store.get(identifier)
    if observation is not None:
        return observation, None

    session_matches = await backend.verbatim_store.list(session_id=identifier, limit=100)
    if project_name:
        session_matches = [
            match for match in session_matches if match.metadata.get("project_name") == project_name
        ]

    if len(session_matches) == 1:
        return session_matches[0], None

    if len(session_matches) > 1:
        choices = ", ".join(match.id for match in session_matches[:5])
        more = "" if len(session_matches) <= 5 else f", ... (+{len(session_matches) - 5} more)"
        return (
            None,
            f"Multiple observations found for session: {identifier}. Use one of these observation ids: {choices}{more}",
        )

    return None, None


async def build_search_project_context_map(
    backend: LocalMemoryBackend,
    *,
    entries: Sequence[MemoryEntry] = (),
    observations: Sequence[Observation] = (),
    relation_facts: Sequence[RelationFact] = (),
) -> dict[str, list[str]]:
    """Resolve project profile stacks for search results."""
    project_names = {
        entry.project_name
        for entry in entries
        if entry.project_name
    }
    project_names.update(
        str(observation.metadata["project_name"])
        for observation in observations
        if isinstance(observation.metadata.get("project_name"), str)
    )
    project_names.update(
        fact.project_name
        for fact in relation_facts
        if fact.project_name
    )
    project_names.discard(None)
    if not project_names:
        return {}

    store = LocalProjectProfileStore(backend.data_dir)
    tech_stack_by_project: dict[str, list[str]] = {}
    for project_name in sorted(project_names):
        if not project_name:
            continue
        profile = await store.get(project_name)
        tech_stack_by_project[project_name] = list(profile.stacks) if profile else []
    return tech_stack_by_project


def search_header(results: Sequence[object], requested_mode: str) -> str:
    """Format a stable search header based on the effective search mode."""
    if not results:
        return f"[{requested_mode.upper()} Search]"
    first = results[0]
    effective_mode = getattr(first, "_search_mode", requested_mode)
    fallback_reason = getattr(first, "_search_fallback_reason", None)
    if effective_mode == "hybrid":
        return "[Hybrid Search]"
    if fallback_reason:
        return f"[FTS Search] ({fallback_reason}, using full-text search)"
    return "[FTS Search]"


def format_search_score(result: object) -> str:
    """Return the best available score field for display."""
    score = getattr(result, "_score", None)
    if score is None:
        score = getattr(result, "_hybrid_score", None)
    if score is None:
        score = getattr(result, "_fts_score", None)
    if isinstance(score, (int, float)):
        return f"{score:.3f}"
    return "n/a"


def format_observation_reference(observation: Observation) -> str:
    """Show the observation id that can be passed back into `show`."""
    return f"[{observation.id}] session: {observation.session_id}"


def format_validity_marker(result: object) -> str:
    """Return a compact marker for historical structured truth."""
    valid_to = _normalize_datetime(getattr(result, "valid_to", None))
    if valid_to is None or valid_to > datetime.now(timezone.utc):
        return ""
    return f" [historical valid_to={valid_to.isoformat()}]"


def preview_search_text(text: str, query: str, *, max_chars: int = 200) -> str:
    """Return a compact preview centered near the first query match."""
    cleaned_query = query.strip()
    candidates = [cleaned_query, *cleaned_query.split()]
    lowered = text.lower()
    match_index = -1
    for candidate in sorted({c for c in candidates if c}, key=len, reverse=True):
        match_index = lowered.find(candidate.lower())
        if match_index >= 0:
            break

    if match_index < 0:
        preview = text[:max_chars]
        if len(text) > max_chars:
            preview += "..."
        return preview.replace("\n", " ")

    context_before = max_chars // 3
    start = max(0, match_index - context_before)
    end = min(len(text), start + max_chars)
    if end - start < max_chars:
        start = max(0, end - max_chars)

    preview = text[start:end].replace("\n", " ")
    if start > 0:
        preview = "..." + preview
    if end < len(text):
        preview += "..."
    return preview


def serialize_memory_entry_search_result(
    entry: object,
    requested_mode: str,
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize a structured memory result for MCP responses."""
    project_name = getattr(entry, "project_name", None)
    return {
        "id": getattr(entry, "id"),
        "project_name": project_name,
        "tech_stack": _tech_stack_for_project(project_name, tech_stack_by_project),
        "category": getattr(entry, "category"),
        # v1.6.0: read-only exposure of the new memory_type field. Falls back
        # to "semantic" for any object that lacks it (defensive: legacy or
        # synthetic fixtures), keeping the contract stable.
        "memory_type": getattr(entry, "memory_type", "semantic"),
        "content": getattr(entry, "content"),
        "confidence": getattr(entry, "confidence"),
        "tags": getattr(entry, "tags"),
        "provenance": getattr(entry, "provenance"),
        "search_mode": getattr(entry, "_search_mode", requested_mode),
        "score": _raw_search_score(entry),
        **_serialize_validity_fields(entry),
    }


def serialize_observation_search_result(
    observation: Observation,
    requested_mode: str,
    query: str = "",
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize an observation search result for MCP responses."""
    project_name = observation.metadata.get("project_name")
    return {
        "id": observation.id,
        "project_name": project_name,
        "tech_stack": _tech_stack_for_project(project_name, tech_stack_by_project),
        "session_id": observation.session_id,
        "content_type": observation.content_type,
        "preview": preview_search_text(observation.raw_content, query, max_chars=200),
        "search_mode": getattr(observation, "_search_mode", requested_mode),
        "score": _raw_search_score(observation),
    }


def serialize_relation_fact_search_result(
    fact: RelationFact,
    tech_stack_by_project: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Serialize a relation fact search result for MCP responses."""
    return {
        "id": fact.id,
        "project_name": fact.project_name,
        "tech_stack": _tech_stack_for_project(fact.project_name, tech_stack_by_project),
        "source_entity": fact.source_entity,
        "target_entity": fact.target_entity,
        "relation_type": fact.relation_type,
        "confidence": fact.confidence,
        "evidence": fact.evidence,
        "source": fact.source,
        "tags": fact.tags,
        "provenance": fact.provenance,
        "search_mode": "fts",
        "score": _raw_search_score(fact),
        **_serialize_validity_fields(fact),
    }


def serialize_relation_path(path: RelationPath) -> dict[str, Any]:
    """Serialize a bounded relation path for CLI/MCP/API clients."""
    return {
        "depth": path.depth,
        "entities": path.entities,
        "confidence": path.confidence,
        "edges": [
            serialize_relation_fact_search_result(fact)
            for fact in path.facts
        ],
        "evidence": [fact.evidence for fact in path.facts],
    }


def serialize_skill(skill: Skill) -> dict[str, Any]:
    """Serialize a confirmed procedural skill for CLI/MCP/API clients."""
    return {
        "id": skill.id,
        "project_name": skill.project_name,
        "name": skill.name,
        "activation_condition": skill.activation_condition,
        "steps": skill.steps,
        "termination_condition": skill.termination_condition,
        "success_examples": skill.success_examples,
        "source_candidate_id": skill.source_candidate_id,
        "source_session_id": skill.source_session_id,
        "scope": skill.scope,
        "origin_project": skill.origin_project,
        "source_ids": skill.source_ids,
        "portability_notes": skill.portability_notes,
        "disabled_assumptions": skill.disabled_assumptions,
        "confidence": skill.confidence,
        "status": skill.status,
        "usage_count": skill.usage_count,
        "success_count": skill.success_count,
        "failure_count": skill.failure_count,
        "success_rate": skill.success_rate,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
        "last_used_at": skill.last_used_at.isoformat() if skill.last_used_at else None,
        "score": _raw_search_score(skill),
    }


def serialize_timeline_observation(observation: Observation) -> dict[str, Any]:
    """Serialize a timeline item for MCP responses."""
    return {
        "id": observation.id,
        "session_id": observation.session_id,
        "client": observation.client,
        "content_type": observation.content_type,
        "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
        "preview": observation.raw_content[:150].replace("\n", " "),
        "tags": observation.tags,
    }


def serialize_observation(observation: Observation) -> dict[str, Any]:
    """Serialize a full observation payload."""
    return {
        "id": observation.id,
        "session_id": observation.session_id,
        "client": observation.client,
        "content_type": observation.content_type,
        "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
        "raw_content": observation.raw_content,
        "tags": observation.tags,
        "metadata": observation.metadata,
    }


def serialize_regex_observation_match(match: RegexObservationMatch) -> dict[str, Any]:
    """Serialize a regex observation match for CLI/MCP/API clients."""
    observation = getattr(match, "observation")
    return {
        "id": observation.id,
        "project_name": observation.metadata.get("project_name"),
        "session_id": observation.session_id,
        "content_type": observation.content_type,
        "timestamp": observation.timestamp.isoformat() if observation.timestamp else None,
        "snippet": getattr(match, "snippet"),
        "match_start": getattr(match, "match_start"),
        "match_end": getattr(match, "match_end"),
        "candidate_count": getattr(match, "candidate_count"),
        "tags": observation.tags,
    }


def _raw_search_score(result: object) -> float | None:
    score = getattr(result, "_score", None)
    if score is None:
        score = getattr(result, "_hybrid_score", None)
    if score is None:
        score = getattr(result, "_fts_score", None)
    return score if isinstance(score, (int, float)) else None


def _serialize_validity_fields(result: object) -> dict[str, Any]:
    valid_to = _normalize_datetime(getattr(result, "valid_to", None))
    valid_from = _normalize_datetime(getattr(result, "valid_from", None))
    recorded_at = _normalize_datetime(getattr(result, "recorded_at", None))
    return {
        "valid_from": valid_from.isoformat() if valid_from else None,
        "valid_to": valid_to.isoformat() if valid_to else None,
        "recorded_at": recorded_at.isoformat() if recorded_at else None,
        "supersedes": list(getattr(result, "supersedes", []) or []),
        "superseded_by": list(getattr(result, "superseded_by", []) or []),
        "is_historical": bool(valid_to and valid_to <= datetime.now(timezone.utc)),
    }


def _normalize_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        normalized = value
    elif isinstance(value, str) and value:
        try:
            normalized = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized


def _window_for_spec(
    spec: str,
    reference: datetime,
) -> tuple[datetime, datetime]:
    local_ref = reference.astimezone(timezone.utc)
    if spec == "yesterday":
        day = (local_ref - timedelta(days=1)).date()
        start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        return start, start + timedelta(days=1)
    if spec == "last_week":
        today = local_ref.date()
        this_week_start = today - timedelta(days=today.weekday())
        start_date = this_week_start - timedelta(days=7)
        start = datetime(start_date.year, start_date.month, start_date.day, tzinfo=timezone.utc)
        return start, start + timedelta(days=7)
    if spec == "last_month":
        month_start = datetime(local_ref.year, local_ref.month, 1, tzinfo=timezone.utc)
        prior_month_end = month_start
        prior_month_start = _shift_month(month_start, -1)
        return prior_month_start, prior_month_end
    if spec.startswith("months_ago:"):
        months = int(spec.split(":", 1)[1])
        end = _shift_month(datetime(local_ref.year, local_ref.month, 1, tzinfo=timezone.utc), -(months - 1))
        start = _shift_month(end, -1)
        return start, end
    raise ValueError(f"unknown time window spec: {spec}")


def _shift_month(value: datetime, months: int) -> datetime:
    month_index = value.year * 12 + (value.month - 1) + months
    year = month_index // 12
    month = month_index % 12 + 1
    return value.replace(year=year, month=month)


def _clean_time_phrase(query: str, phrase: str) -> str:
    cleaned = re.sub(re.escape(phrase), " ", query, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned or query


def _tech_stack_for_project(
    project_name: object,
    tech_stack_by_project: dict[str, list[str]] | None,
) -> list[str]:
    if not isinstance(project_name, str) or not tech_stack_by_project:
        return []
    return list(tech_stack_by_project.get(project_name, []))
