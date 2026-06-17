"""Shared read-path helpers used by CLI commands and the MCP server."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Sequence

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.skill import Skill
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.search import backend as search_backend
from harness_mem.search.backend import (
    SearchFilters,
    SQLiteSearchBackend,
    hydrate_backend_results,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_verbatim_store import RegexObservationMatch

REPEAT_BOOST_BASE = search_backend.REPEAT_BOOST_BASE
REPEAT_BOOST_WINDOW_DAYS = search_backend.REPEAT_BOOST_WINDOW_DAYS
REPEAT_BOOST_MIN_HITS = search_backend.REPEAT_BOOST_MIN_HITS

RELATION_TRACE_DEFAULT_DEPTH = 2
RELATION_TRACE_MAX_DEPTH = 3


def _optional_isoformat(value: Any) -> str | None:
    if isinstance(value, datetime):
        return value.isoformat()
    return None


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


@dataclass(frozen=True)
class TemporalRecord:
    """Uniform read-model projection for confirmed temporal truth."""

    id: str
    truth_type: str
    project_name: str
    subject: str
    predicate: str
    object: str
    confidence: float | None
    valid_from: datetime | None
    valid_to: datetime | None
    recorded_at: datetime | None
    source_ids: tuple[str, ...]
    supersedes: tuple[str, ...]
    superseded_by: tuple[str, ...]
    provenance: dict | None
    tags: tuple[str, ...]
    payload: dict[str, Any]

    @property
    def is_current(self) -> bool:
        valid_to = _normalize_datetime(self.valid_to)
        return valid_to is None or valid_to > datetime.now(timezone.utc)

    def valid_at(self, as_of: datetime) -> bool:
        valid_from = _normalize_datetime(self.valid_from)
        valid_to = _normalize_datetime(self.valid_to)
        if valid_from is not None and valid_from > as_of:
            return False
        return valid_to is None or valid_to > as_of


@dataclass(frozen=True)
class TemporalQueryResult:
    """Temporal query response with explainability and abstention metadata."""

    records: tuple[TemporalRecord, ...]
    timeline: tuple[TemporalRecord, ...]
    supersede_chain: tuple[TemporalRecord, ...]
    explanations: tuple[dict[str, Any], ...]
    abstain: bool
    abstention_reason: str | None
    truncated: bool
    read_model_count: int


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
    deep_recall: bool = False,
    time_window: tuple[datetime | None, datetime | None] | None = None,
    record_signals: bool = True,
) -> tuple[list[MemoryEntry], list[Observation]]:
    """Compatibility facade over the runtime SearchBackend mainline."""

    backend_limit = max(20, memory_entry_limit + observation_limit + 20)
    response = await SQLiteSearchBackend(backend).search(
        query,
        filters=SearchFilters(
            project_name=project_name,
            scope=scope,
            memory_type=memory_type,
            include_history=include_history,
            time_window=time_window,
            deep_recall=deep_recall,
        ),
        mode=mode,  # type: ignore[arg-type]
        limit=backend_limit,
    )
    hydrated = await hydrate_backend_results(backend, response)
    entries = list(hydrated["memory_entry"])[:memory_entry_limit]
    observations = list(hydrated["observation"])[:observation_limit]
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


async def query_temporal_truth(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str | None = None,
    subject: str | None = None,
    predicate: str | None = None,
    truth_type: str | None = None,
    mode: str = "current",
    as_of: datetime | None = None,
    valid_range: tuple[datetime | None, datetime | None] | None = None,
    recorded_range: tuple[datetime | None, datetime | None] | None = None,
    limit: int = 20,
    require_unique_current: bool = False,
) -> TemporalQueryResult:
    """Project confirmed truth into a temporal read model and query it.

    This is intentionally read-only: it rebuilds the projection from
    MemoryEntry / RelationFact / ConfirmedRule blobs on every call and never
    persists derived state.
    """
    effective_limit = max(1, min(limit, 100))
    normalized_as_of = _normalize_datetime(as_of)
    normalized_valid_range = _normalize_optional_range(valid_range)
    normalized_recorded_range = _normalize_optional_range(recorded_range)
    records = await build_temporal_read_model(
        backend,
        project_name=project_name,
        include_history=True,
    )
    filtered = [
        record for record in records
        if _record_matches_temporal_filters(
            record,
            query=query,
            subject=subject,
            predicate=predicate,
            truth_type=truth_type,
            mode=mode,
            as_of=normalized_as_of,
            valid_range=normalized_valid_range,
            recorded_range=normalized_recorded_range,
        )
    ]
    filtered.sort(key=_temporal_sort_key, reverse=True)
    truncated = len(filtered) > effective_limit
    selected = tuple(filtered[:effective_limit])

    timeline_subject, timeline_predicate = _timeline_key(selected, subject, predicate)
    timeline = tuple(
        sorted(
            (
                record for record in records
                if _same_optional(record.subject, timeline_subject)
                and _same_optional(record.predicate, timeline_predicate)
            ),
            key=_temporal_sort_key,
            reverse=True,
        )
    )
    chain = tuple(_supersede_chain(records, selected))
    explanations = tuple(
        _temporal_explanation(record, records)
        for record in selected
    )

    conflict = (
        require_unique_current
        and mode == "current"
        and len([
            record for record in filtered
            if record.is_current
        ]) > 1
    )
    abstain = not selected or conflict
    reason = None
    if not selected:
        reason = "no_evidence"
    elif conflict:
        reason = "temporal_conflict"

    return TemporalQueryResult(
        records=selected,
        timeline=timeline,
        supersede_chain=chain,
        explanations=explanations,
        abstain=abstain,
        abstention_reason=reason,
        truncated=truncated,
        read_model_count=len(records),
    )


async def build_temporal_read_model(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    include_history: bool = True,
) -> tuple[TemporalRecord, ...]:
    """Rebuild the temporal read model from source-of-truth collections."""
    entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=10000,
        include_history=include_history,
    )
    rules = await backend.structured_store.list_confirmed_rules(
        project_name,
        include_history=include_history,
    )
    facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=10000,
        include_history=include_history,
    )
    records = [
        *(_record_from_memory_entry(entry) for entry in entries),
        *(_record_from_confirmed_rule(rule) for rule in rules),
        *(_record_from_relation_fact(fact) for fact in facts),
    ]
    return tuple(sorted(records, key=_temporal_sort_key, reverse=True))


async def search_skills(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str,
    scope: str = "project",
    limit: int = 10,
    shared_scope: str = "exclude",
) -> list[Skill]:
    """Search confirmed procedural skills with shared project scoping."""
    if scope == "all":
        return await backend.structured_store.search_skills(
            query,
            project_name=None,
            limit=limit,
            shared_scope=shared_scope,
        )
    return await backend.structured_store.search_skills(
        query,
        project_name=project_name,
        limit=limit,
        shared_scope=shared_scope,
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
        "repeat_boost": getattr(entry, "_repeat_boost", 0.0) or 0.0,
        "context_outcome_counts": getattr(entry, "_context_outcome_counts", {}),
        "context_outcome_score": getattr(entry, "_context_outcome_score", 0.0)
        or 0.0,
        "last_context_outcome_at": _optional_isoformat(
            getattr(entry, "_last_context_outcome_at", None)
        ),
        "ranking_explanation": getattr(entry, "_ranking_explanation", []),
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


def serialize_temporal_query_result(result: TemporalQueryResult) -> dict[str, Any]:
    """Serialize a temporal read-model query for MCP/API clients."""
    return {
        "success": True,
        "abstain": result.abstain,
        "abstention_reason": result.abstention_reason,
        "records": [serialize_temporal_record(record) for record in result.records],
        "record_count": len(result.records),
        "timeline": [serialize_temporal_record(record) for record in result.timeline],
        "timeline_count": len(result.timeline),
        "supersede_chain": [
            serialize_temporal_record(record) for record in result.supersede_chain
        ],
        "supersede_chain_count": len(result.supersede_chain),
        "explanations": list(result.explanations),
        "truncated": result.truncated,
        "read_model_count": result.read_model_count,
    }


def serialize_temporal_record(record: TemporalRecord) -> dict[str, Any]:
    """Serialize one projected temporal truth record."""
    return {
        "id": record.id,
        "truth_type": record.truth_type,
        "project_name": record.project_name,
        "subject": record.subject,
        "predicate": record.predicate,
        "object": record.object,
        "confidence": record.confidence,
        "valid_from": record.valid_from.isoformat() if record.valid_from else None,
        "valid_to": record.valid_to.isoformat() if record.valid_to else None,
        "recorded_at": record.recorded_at.isoformat() if record.recorded_at else None,
        "source_ids": list(record.source_ids),
        "supersedes": list(record.supersedes),
        "superseded_by": list(record.superseded_by),
        "is_current": record.is_current,
        "provenance": record.provenance,
        "tags": list(record.tags),
        "payload": record.payload,
    }


def serialize_skill(skill: Skill) -> dict[str, Any]:
    """Serialize a confirmed procedural skill for CLI/MCP/API clients."""
    activation_warnings: list[str] = []
    if skill.scope in {"workspace", "global"}:
        if skill.portability_notes:
            activation_warnings.append(skill.portability_notes)
        activation_warnings.extend(skill.disabled_assumptions)
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
        "activation_warnings": activation_warnings,
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


def _record_from_memory_entry(entry: MemoryEntry) -> TemporalRecord:
    return TemporalRecord(
        id=entry.id,
        truth_type="memory_entry",
        project_name=entry.project_name,
        subject=entry.category,
        predicate="memory_entry",
        object=entry.content,
        confidence=entry.confidence,
        valid_from=_normalize_datetime(entry.valid_from),
        valid_to=_normalize_datetime(entry.valid_to),
        recorded_at=_normalize_datetime(entry.recorded_at),
        source_ids=tuple(_source_ids(entry.source, entry.provenance, entry.id)),
        supersedes=tuple(entry.supersedes),
        superseded_by=tuple(entry.superseded_by),
        provenance=entry.provenance,
        tags=tuple(entry.tags),
        payload={
            "category": entry.category,
            "content": entry.content,
            "memory_type": entry.memory_type,
            "status": entry.status,
        },
    )


def _record_from_confirmed_rule(rule: Any) -> TemporalRecord:
    return TemporalRecord(
        id=rule.id,
        truth_type="confirmed_rule",
        project_name=rule.project_name,
        subject=rule.trigger,
        predicate="confirmed_rule",
        object=rule.pattern,
        confidence=None,
        valid_from=_normalize_datetime(rule.valid_from),
        valid_to=_normalize_datetime(rule.valid_to),
        recorded_at=_normalize_datetime(rule.recorded_at),
        source_ids=tuple(
            _source_ids(
                rule.source_candidate_id,
                rule.provenance,
                rule.id,
                rule.source_session_id,
            )
        ),
        supersedes=tuple(rule.supersedes),
        superseded_by=tuple(rule.superseded_by),
        provenance=rule.provenance,
        tags=tuple(rule.tags),
        payload={
            "pattern": rule.pattern,
            "trigger": rule.trigger,
            "examples": list(rule.examples),
            "source_candidate_id": rule.source_candidate_id,
            "source_session_id": rule.source_session_id,
        },
    )


def _record_from_relation_fact(fact: RelationFact) -> TemporalRecord:
    return TemporalRecord(
        id=fact.id,
        truth_type="relation_fact",
        project_name=fact.project_name,
        subject=fact.source_entity,
        predicate=fact.relation_type,
        object=fact.target_entity,
        confidence=fact.confidence,
        valid_from=_normalize_datetime(fact.valid_from),
        valid_to=_normalize_datetime(fact.valid_to),
        recorded_at=_normalize_datetime(fact.recorded_at),
        source_ids=tuple(_source_ids(fact.source, fact.provenance, fact.id)),
        supersedes=tuple(fact.supersedes),
        superseded_by=tuple(fact.superseded_by),
        provenance=fact.provenance,
        tags=tuple(fact.tags),
        payload={
            "source_entity": fact.source_entity,
            "target_entity": fact.target_entity,
            "relation_type": fact.relation_type,
            "evidence": fact.evidence,
            "status": fact.status,
        },
    )


def _source_ids(*values: object) -> list[str]:
    deduped: list[str] = []
    for value in values:
        if isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, list):
                    for item in nested:
                        _append_source_id(deduped, item)
                else:
                    _append_source_id(deduped, nested)
        else:
            _append_source_id(deduped, value)
    return deduped


def _append_source_id(target: list[str], value: object) -> None:
    cleaned = str(value).strip() if value is not None else ""
    if cleaned and cleaned not in target:
        target.append(cleaned)


def _record_matches_temporal_filters(
    record: TemporalRecord,
    *,
    query: str | None,
    subject: str | None,
    predicate: str | None,
    truth_type: str | None,
    mode: str,
    as_of: datetime | None,
    valid_range: tuple[datetime | None, datetime | None] | None,
    recorded_range: tuple[datetime | None, datetime | None] | None,
) -> bool:
    if truth_type and record.truth_type != truth_type:
        return False
    if subject and subject.lower() not in record.subject.lower():
        return False
    if predicate and predicate.lower() not in record.predicate.lower():
        return False
    if query:
        haystack = " ".join((record.subject, record.predicate, record.object)).lower()
        if query.lower() not in haystack:
            return False
    if as_of is not None and not record.valid_at(as_of):
        return False
    if mode == "current" and not record.is_current:
        return False
    if mode == "history" and record.is_current:
        return False
    if valid_range and not _time_range_overlaps(record.valid_from, record.valid_to, valid_range):
        return False
    if recorded_range and not _point_in_range(record.recorded_at, recorded_range):
        return False
    return True


def _normalize_optional_range(
    value: tuple[datetime | None, datetime | None] | None,
) -> tuple[datetime | None, datetime | None] | None:
    if value is None:
        return None
    return _normalize_datetime(value[0]), _normalize_datetime(value[1])


def _time_range_overlaps(
    valid_from: datetime | None,
    valid_to: datetime | None,
    requested: tuple[datetime | None, datetime | None],
) -> bool:
    start, end = requested
    current_start = _normalize_datetime(valid_from) or datetime.min.replace(tzinfo=timezone.utc)
    current_end = _normalize_datetime(valid_to) or datetime.max.replace(tzinfo=timezone.utc)
    requested_start = start or datetime.min.replace(tzinfo=timezone.utc)
    requested_end = end or datetime.max.replace(tzinfo=timezone.utc)
    return current_start < requested_end and requested_start < current_end


def _point_in_range(
    point: datetime | None,
    requested: tuple[datetime | None, datetime | None],
) -> bool:
    normalized = _normalize_datetime(point)
    if normalized is None:
        return False
    start, end = requested
    if start is not None and normalized < start:
        return False
    return end is None or normalized < end


def _temporal_sort_key(record: TemporalRecord) -> tuple[datetime, datetime, str]:
    valid_from = record.valid_from or datetime.min.replace(tzinfo=timezone.utc)
    recorded_at = record.recorded_at or datetime.min.replace(tzinfo=timezone.utc)
    return valid_from, recorded_at, record.id


def _timeline_key(
    records: Sequence[TemporalRecord],
    subject: str | None,
    predicate: str | None,
) -> tuple[str | None, str | None]:
    if subject and predicate:
        return subject, predicate
    if records:
        return records[0].subject, records[0].predicate
    return subject, predicate


def _same_optional(value: str, requested: str | None) -> bool:
    return requested is None or value.lower() == requested.lower()


def _supersede_chain(
    all_records: Sequence[TemporalRecord],
    selected: Sequence[TemporalRecord],
) -> list[TemporalRecord]:
    by_id = {record.id: record for record in all_records}
    selected_ids = {record.id for record in selected}
    chain: list[TemporalRecord] = []
    seen: set[str] = set()
    queue = [
        linked_id
        for record in selected
        for linked_id in (*record.supersedes, *record.superseded_by)
    ]
    while queue:
        next_id = queue.pop(0)
        if next_id in seen:
            continue
        seen.add(next_id)
        if next_id in selected_ids:
            continue
        linked = by_id.get(next_id)
        if linked is None:
            continue
        chain.append(linked)
        queue.extend([
            linked_id
            for linked_id in (*linked.supersedes, *linked.superseded_by)
            if linked_id not in seen
        ])
    chain.sort(key=_temporal_sort_key, reverse=True)
    return chain


def _temporal_explanation(
    record: TemporalRecord,
    all_records: Sequence[TemporalRecord],
) -> dict[str, Any]:
    by_id = {item.id: item for item in all_records}
    old_records = [by_id[item_id] for item_id in record.supersedes if item_id in by_id]
    new_records = [by_id[item_id] for item_id in record.superseded_by if item_id in by_id]
    return {
        "record_id": record.id,
        "truth_type": record.truth_type,
        "current": record.is_current,
        "old": [serialize_temporal_record(item) for item in old_records],
        "newer": [serialize_temporal_record(item) for item in new_records],
        "evidence": list(record.source_ids),
        "policy_reason": (
            "confirmed truth is current until valid_to is set; supersede links explain replacements"
        ),
    }


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
