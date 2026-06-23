"""Plan_Assembler — build a read-only ContextAssemblyPlan from existing reads.

v2.5.0 reframes context as an *explainable, budgeted, layered* assembly. This
module hosts :func:`assemble_context_plan`, the side-effect-free entry point
that composes the *same* read surfaces ``wake`` and search already use into a
five-layer (L0..L4) :class:`ContextAssemblyPlan`.

Producing a plan is side-effect free (Req 9): it performs no insert / update /
delete, emits no ``RetrievalSignal``, and never calls any ``touch_*``. It also
never alters the observable behavior of ``wake`` or ``search_memory``.

This module currently carries the *scaffold*: the public entry point, the
shared budget helper, and five empty-layer builder stubs. The real per-layer
selection logic lands in later slices (tasks 4.1-8.1); each stub returns a
well-formed empty :class:`Layer` so the function returns a complete plan
end-to-end with no orphaned code.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem.commands.support import resolve_project_name
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.context_assembly_plan import (
    LAYER_ORDER,
    Budget,
    ContextAssemblyPlan,
    DrilldownPointer,
    Layer,
    LayerId,
    PlanEntry,
    TruncationAccounting,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.search.backend import (
    SearchBackendResponse,
    SearchFilters,
    SQLiteSearchBackend,
    hydrate_backend_results,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

# Default per-layer budgets (Req 2.4, 3.4, 4.4, 5.4, 7.4).
DEFAULT_BUDGETS: dict[str, int] = {
    "L0": 3,
    "L1": 7,
    "L2": 7,
    "L3": 10,
    "L4": 20,
}

# Window for L2 "recently surfaced" truth derivation (used by task 6.1).
RECENTLY_SURFACED_WINDOW_DAYS = 7


async def assemble_context_plan(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str | None = None,
    budgets: dict[str, int] | None = None,
) -> ContextAssemblyPlan:
    """Build a read-only ContextAssemblyPlan from existing read surfaces.

    Side-effect free: performs no insert/update/delete, emits no
    ``RetrievalSignal``, never calls ``touch_*`` (Req 9). The five layers are
    assembled in fixed order L0..L4 (Req 1.2).

    ``project_name`` is resolved with the same resolution existing read
    surfaces apply (Req 2.1) — explicit value, then ``HARNESS_MEM_PROJECT``,
    then the active-project marker — using the read-only (``required=False``)
    path so resolution itself writes nothing.
    """
    resolved = resolve_project_name(
        project_name,
        required=False,
        action_label="assemble-context-plan",
    )
    if not resolved:
        raise ValueError(
            "project_name is required when no active project is set "
            "(pass project_name, set HARNESS_MEM_PROJECT, or set an active project)"
        )

    # When ``budgets`` is supplied, its values override the defaults per layer;
    # any layer it omits keeps the default (Req 6.1).
    effective_budgets = {**DEFAULT_BUDGETS, **(budgets or {})}
    budget_by_layer: dict[LayerId, Budget] = {
        layer_id: Budget(max_entries=effective_budgets[layer_id])
        for layer_id in LAYER_ORDER
    }

    l0 = await _build_l0(backend, resolved, budget_by_layer["L0"])
    l1 = await _build_l1(backend, resolved, budget_by_layer["L1"])
    l2 = await _build_l2(backend, resolved, budget_by_layer["L2"])
    query_response = await _query_driven_backend_response(
        backend,
        project_name=resolved,
        query=query,
        limit=max(budget_by_layer["L3"].max_entries + budget_by_layer["L4"].max_entries, 30),
    )
    hydrated_results = (
        await hydrate_backend_results(backend, query_response)
        if query_response is not None
        else None
    )
    l3 = await _build_l3(backend, resolved, query_response, budget_by_layer["L3"])
    l4 = await _build_l4(
        backend,
        resolved,
        query_response,
        hydrated_results,
        budget_by_layer["L4"],
        l1.entries,
    )

    return ContextAssemblyPlan(
        project_name=resolved,
        query=query,
        layers=[l0, l1, l2, l3, l4],
    )


async def _query_driven_backend_response(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    query: str | None,
    limit: int,
) -> SearchBackendResponse | None:
    if query is None or not query.strip():
        return None
    return await SQLiteSearchBackend(backend).search(
        query,
        filters=SearchFilters(project_name=project_name, scope="project"),
        limit=max(1, limit),
    )


def _apply_budget(
    layer_id: LayerId,
    candidates: list[PlanEntry],
    budget: Budget,
) -> Layer:
    """Cap candidates at ``budget.max_entries`` and compute the accounting.

    ``included = min(available, max_entries)``;
    ``dropped = available - included`` (Req 6.2, 6.3, 6.4, 6.5). Whenever
    ``available <= max_entries`` this yields ``dropped == 0`` (Req 6.5).
    """
    available = len(candidates)
    included = min(available, budget.max_entries)
    return Layer(
        layer=layer_id,
        entries=candidates[:included],
        budget=budget,
        truncation=TruncationAccounting(
            available=available,
            included=included,
            dropped=available - included,
        ),
    )


async def _build_l0(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: Budget,
) -> Layer:
    """L0 profile / identity (Req 2.1-2.5, 8.2-8.3).

    Reads the active project's :class:`ProjectProfile` via the same
    ``LocalProjectProfileStore(backend.data_dir)`` surface ``wake`` uses. When
    a profile exists, emits a single always-on identity entry whose
    ``source_ids`` reference the profile id (a resolvable store identifier,
    Req 8.2) and whose ``summary`` carries the identity fields. When no profile
    exists, returns a well-formed empty layer (Req 2.5).
    """
    profile_store = LocalProjectProfileStore(backend.data_dir)
    profile = await profile_store.get(project_name)

    candidates: list[PlanEntry] = []
    if profile is not None and profile.id:
        candidates.append(
            PlanEntry(
                layer="L0",
                source_ids=[profile.id],
                why_included="identity:active_project",
                summary=_profile_identity_summary(profile),
            )
        )
    return _apply_budget("L0", candidates, budget)


def _profile_identity_summary(profile: ProjectProfile) -> str:
    """Build a concise identity summary from a project profile (Req 2.2).

    Carries the project name (and the active-project marker), plus the
    description and stacks when present, without dumping large content.
    """
    parts = [f"active project: {profile.project_name}"]
    if profile.description:
        parts.append(profile.description)
    if profile.stacks:
        parts.append(f"stacks: {', '.join(profile.stacks)}")
    return " | ".join(parts)


async def _build_l1(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: Budget,
) -> Layer:
    """L1 essential truth (Req 3.1-3.6, 10.1, 10.2, 10.4).

    Populates L1 with confirmed, current, high-confidence truth only:
    confirmed rules first (highest tier — human-promoted), then accepted
    current-truth :class:`MemoryEntry` records. Both source surfaces are pure
    reads and already exclude historical (``valid_to`` set) records via their
    ``include_history=False`` default; the entry surface additionally filters
    to ``status == "accepted"`` (Req 3.1, 3.5).

    Ordering (per design — ``ConfirmedRule`` has no ``confidence`` field):
    rules by ``confirmed_at`` descending (most recently confirmed wins ties),
    then entries by ``confidence`` descending (Req 3.2). Pending candidates and
    historical truth never reach this layer (Req 3.5, 10.2). The budget cap
    (max 7) is applied last via :func:`_apply_budget` (Req 3.4).
    """
    candidates: list[PlanEntry] = []

    # Confirmed rules first — highest tier. ``list_confirmed_rules`` already
    # returns current-only rules ordered by ``confirmed_at`` descending and is
    # a pure read (Req 3.1, 3.2, 10.1, 10.4).
    rules: list[ConfirmedRule] = await backend.structured_store.list_confirmed_rules(
        project_name
    )
    for rule in rules:
        # Defensive: skip historical records and any rule without a resolvable
        # id rather than emit an entry with empty source_ids (Req 3.5, 8.3).
        if rule.valid_to is not None or not rule.id:
            continue
        candidates.append(
            PlanEntry(
                layer="L1",
                source_ids=[rule.id],
                why_included="essential:confirmed_rule",
                summary=_truncate_summary(rule.pattern),
            )
        )

    # Accepted current-truth entries next, ordered by confidence descending.
    # ``include_history=False`` + ``status="accepted"`` already exclude pending
    # and historical records; the explicit ``valid_to is None`` check is a
    # defensive reaffirmation of the accepted-only boundary (Req 3.1, 3.5, 10.1).
    entries: list[MemoryEntry] = await backend.structured_store.list_memory_entries(
        project_name,
        status="accepted",
        include_history=False,
    )
    current_entries = [
        entry for entry in entries if entry.valid_to is None and entry.id
    ]
    current_entries.sort(key=lambda entry: entry.confidence, reverse=True)
    for entry in current_entries:
        candidates.append(
            PlanEntry(
                layer="L1",
                source_ids=[entry.id],
                why_included="essential:high_confidence_truth",
                summary=_truncate_summary(entry.content),
            )
        )

    return _apply_budget("L1", candidates, budget)


def _truncate_summary(text: str, *, max_chars: int = 200) -> str:
    """Keep L1 summaries concise — truncate long rule/entry text (Req 3.x).

    The plan carries a compact preview, not the full record; consumers trace
    back to the source via ``source_ids``.
    """
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "\u2026"


async def _build_l2(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: Budget,
) -> Layer:
    """L2 active task (Req 4.1-4.6, 10.1).

    Two sources, in fixed order:

    1. **Recent task handoffs** via ``get_latest_handoffs`` — emitted as
       ``active:recent_handoff`` entries whose ``source_ids`` reference the
       handoff id and whose ``summary`` is the handoff summary.
    2. **Recently-surfaced accepted current-truth entries**, derived
       *read-only* from v2.3 ``RetrievalSignal`` records (Req 4.5): signals of
       type ``wake_surfaced`` / ``search_hit`` targeting memory entries within
       :data:`RECENTLY_SURFACED_WINDOW_DAYS`, re-fetched via
       ``get_memory_entry`` and filtered to ``status == "accepted"`` and
       ``valid_to is None`` (Req 4.1, 10.1). Emitted as
       ``active:recently_surfaced``.

    Every step is a pure read: ``get_latest_handoffs``,
    ``query_retrieval_signals``, and ``get_memory_entry`` perform no writes and
    touch no ``usage_count`` / ``last_accessed_at``, so the layer emits no new
    ``RetrievalSignal`` (Req 4.5, 9). The budget cap (max 7) is applied last via
    :func:`_apply_budget` (Req 4.4); an empty source yields a well-formed empty
    layer with no error (Req 4.6).
    """
    candidates: list[PlanEntry] = []

    # Part A — recent handoffs (most recent first). ``get_latest_handoffs``
    # orders by ``last_activity`` descending and is a pure read.
    handoffs: list[TaskHandoff] = await backend.structured_store.get_latest_handoffs(
        project_name,
        limit=budget.max_entries,
    )
    for handoff in handoffs:
        # Drop any handoff without a resolvable id rather than emit an entry
        # with empty source_ids (Req 8.3).
        if not handoff.id:
            continue
        candidates.append(
            PlanEntry(
                layer="L2",
                source_ids=[handoff.id],
                why_included="active:recent_handoff",
                summary=_truncate_summary(handoff.summary),
            )
        )

    # Part B — recently-surfaced accepted current-truth entries, derived
    # read-only from retrieval signals (Req 4.1, 4.5, 10.1).
    for entry in await _recently_surfaced_entries(backend, project_name):
        candidates.append(
            PlanEntry(
                layer="L2",
                source_ids=[entry.id],
                why_included="active:recently_surfaced",
                summary=_truncate_summary(entry.content),
            )
        )

    return _apply_budget("L2", candidates, budget)


async def _recently_surfaced_entries(
    backend: LocalMemoryBackend,
    project_name: str,
) -> list[MemoryEntry]:
    """Resolve recently-surfaced accepted current-truth entries (read-only).

    Mirrors the query shape ``signal_influence.pull_recent_signals`` uses: the
    signals layer filters by a single ``signal_type`` per query, so we issue
    two ``query_retrieval_signals`` calls (``wake_surfaced`` + ``search_hit``),
    both scoped to ``target_kind="memory_entry"`` and to the
    :data:`RECENTLY_SURFACED_WINDOW_DAYS` window, then merge in memory newest
    first. Distinct ``target_id`` values are collected preserving newest-first
    order, then re-fetched via ``get_memory_entry`` and filtered to accepted
    current truth (``status == "accepted"`` and ``valid_to is None``).

    All reads are side-effect free (Req 4.5, 9): ``query_retrieval_signals``
    and ``get_memory_entry`` perform no writes and emit no ``RetrievalSignal``.
    """
    since = datetime.now(timezone.utc) - timedelta(days=RECENTLY_SURFACED_WINDOW_DAYS)

    wake_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        target_kind="memory_entry",
        since=since,
    )
    search_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        target_kind="memory_entry",
        since=since,
    )

    # Merge both newest-first streams into one ordered newest first, then
    # collect distinct target ids preserving that newest-first order.
    merged = sorted(
        [*wake_signals, *search_signals],
        key=lambda signal: signal.recorded_at,
        reverse=True,
    )
    ordered_ids: list[str] = []
    seen: set[str] = set()
    for signal in merged:
        if signal.target_id and signal.target_id not in seen:
            seen.add(signal.target_id)
            ordered_ids.append(signal.target_id)

    entries: list[MemoryEntry] = []
    for target_id in ordered_ids:
        entry = await backend.structured_store.get_memory_entry(target_id)
        # Keep only accepted current truth; drop missing / pending / historical
        # records (Req 4.1, 8.3, 10.1).
        if entry is None or not entry.id:
            continue
        if entry.status != "accepted" or entry.valid_to is not None:
            continue
        entries.append(entry)

    return entries


async def _build_l3(
    backend: LocalMemoryBackend,
    project_name: str,
    query_response: SearchBackendResponse | None,
    budget: Budget,
) -> Layer:
    """L3 topic recall (Req 5.1-5.6).

    Query-driven, compact recall over the *existing* search read surfaces. The
    layer is populated only when a non-empty ``query`` is supplied; when
    ``query`` is ``None`` or blank, the layer short-circuits to a well-formed
    empty layer (``available=0``) **without invoking any search surface**
    (Req 5.5).

    Sources, in fixed deterministic order (per the design source-mapping
    table):

    1. ``read_api.search_memory(..., record_signals=False)`` — matched accepted
       current-truth entries; ``why_included = "topic_recall:search_memory"``,
       ``source_ids`` = the matched entry id, ``summary`` = a compact preview.
       ``record_signals=False`` is mandatory so no ``search_hit``
       ``RetrievalSignal`` is emitted (Req 5.6).
    2. ``read_api.search_relation_facts(...)`` — matched relation facts;
       ``why_included = "topic_recall:relation_fact"``, ``source_ids`` = the
       relation fact id.
    3. ``read_api.search_skills(...)`` — matched procedural skills surfaced as
       *compact hints only*: id / title / reason, never the step content
       (Req 5.3); ``why_included = "topic_recall:skill"``.

    Every read is side-effect free (Req 5.6): the underlying store searches
    perform no writes and emit no signals, and ``search_memory`` is called with
    ``record_signals=False`` so its only shadow-write is suppressed. None of
    these surfaces touch ``usage_count`` / ``last_accessed_at``. Candidates
    without a resolvable id are dropped rather than emitted with empty
    ``source_ids`` (Req 8.3). The budget cap (max 10) is applied last via
    :func:`_apply_budget` (Req 5.4).
    """
    # Short-circuit on absent / blank query — no search surface is touched
    # (Req 5.5).
    if query_response is None:
        return _apply_budget("L3", [], budget)

    candidates: list[PlanEntry] = []
    for result in query_response.results:
        if result.source_kind == "memory_entry":
            candidates.append(
                PlanEntry(
                    layer="L3",
                    source_ids=[result.source_id],
                    why_included="topic_recall:search_memory",
                    summary=_truncate_summary(result.preview),
                )
            )
        elif result.source_kind == "relation_fact":
            candidates.append(
                PlanEntry(
                    layer="L3",
                    source_ids=[result.source_id],
                    why_included="topic_recall:relation_fact",
                    summary=_truncate_summary(result.preview),
                )
            )
        elif result.source_kind == "skill":
            candidates.append(
                PlanEntry(
                    layer="L3",
                    source_ids=[result.source_id],
                    why_included="topic_recall:skill",
                    summary=_truncate_summary(result.preview),
                )
            )

    return _apply_budget("L3", candidates, budget)


def _skill_hint_summary(skill: Skill) -> str:
    """Build a compact skill hint carrying id / title / reason only (Req 5.3).

    The plan never embeds full procedural skill steps; consumers expand the
    skill through its id when they actually need the procedure. ``reason`` is
    the skill's activation condition (the "when to use this" hint), truncated
    to stay compact.
    """
    return _truncate_summary(
        f"skill {skill.id}: {skill.name} | when: {skill.activation_condition}"
    )


async def _build_l4(
    backend: LocalMemoryBackend,
    project_name: str,
    query_response: SearchBackendResponse | None,
    hydrated_results: dict[str, list[object]] | None,
    budget: Budget,
    l1_entries: list[PlanEntry],
) -> Layer:
    """L4 raw evidence drilldown (Req 7.1-7.6, 8.2-8.3, 10.1).

    Every L4 entry carries a :class:`DrilldownPointer` instead of inline raw
    text (Req 7.1): the pointer names the source record and the read surface a
    consumer would call to expand it on demand (Req 7.2, 7.6). The plan never
    embeds the full observation / entry content — ``summary`` stays empty so no
    raw evidence leaks into the layer.

    Three deterministic, side-effect-free sources, in fixed order:

    1. **``evidence:supports_L1``** — for each L1 entry resolving to an accepted
       :class:`MemoryEntry`, the raw observations recorded in its
       ``provenance.observation_ids`` that still exist in the verbatim store.
       Each becomes an observation drilldown (read surface
       ``read_api.get_observations``). This grounds confirmed truth in the raw
       evidence that backs it.
    2. **``evidence:topic_match``** — when a non-empty ``query`` is supplied, the
       observations returned by ``search_memory(..., record_signals=False)``
       (Req 7.3). ``record_signals=False`` keeps the read side-effect free.
    3. **Historical truth** — accepted memory entries whose ``valid_to`` is set
       (superseded). These appear *only* here, tagged
       ``truth_status="historical"``, never in L1 / L2 (Req 7.5, 10.1), each
       surfaced as a drilldown referencing the historical entry id.

    Observation drilldowns from sources 1 and 2 are de-duplicated by
    observation id (first reason wins). Any candidate whose underlying record
    cannot be resolved is dropped rather than emitted with an empty / fabricated
    ``source_id`` (Req 8.3). The budget cap (max 20) is applied last via
    :func:`_apply_budget` (Req 7.4); an empty source set yields a well-formed
    empty layer with no error.
    """
    candidates: list[PlanEntry] = []
    seen_observation_ids: set[str] = set()

    # 1. evidence:supports_L1 — observations backing accepted L1 truth.
    l1_entry_ids = [
        source_id
        for entry in l1_entries
        for source_id in entry.source_ids
    ]
    for memory_entry in await _resolve_l1_memory_entries(backend, l1_entry_ids):
        observation_ids = _provenance_observation_ids(memory_entry)
        for observation in await _resolve_observations(backend, observation_ids):
            if observation.id in seen_observation_ids:
                continue
            seen_observation_ids.add(observation.id)
            candidates.append(
                _observation_drilldown_entry(
                    observation,
                    project_name,
                    why_included="evidence:supports_L1",
                )
            )

    # 2. evidence:topic_match — observations matching the query (read-only).
    if query_response is not None and hydrated_results is not None:
        for observation_obj in hydrated_results["observation"]:
            if not isinstance(observation_obj, Observation):
                continue
            observation = observation_obj
            if not observation.id or observation.id in seen_observation_ids:
                continue
            seen_observation_ids.add(observation.id)
            candidates.append(
                _observation_drilldown_entry(
                    observation,
                    project_name,
                    why_included="evidence:topic_match",
                )
            )

    # 3. Historical truth — superseded entries, surfaced only as L4 drilldowns.
    historical_entries = await backend.structured_store.list_memory_entries(
        project_name,
        status="accepted",
        include_history=True,
    )
    for memory_entry in historical_entries:
        if memory_entry.valid_to is None or not memory_entry.id:
            continue
        candidates.append(
            PlanEntry(
                layer="L4",
                source_ids=[memory_entry.id],
                why_included="evidence:supports_L1",
                drilldown=DrilldownPointer(
                    source_id=memory_entry.id,
                    read_surface="read_api.get_memory_entry",
                    locator={"project_name": project_name},
                ),
                truth_status="historical",
            )
        )

    return _apply_budget("L4", candidates, budget)


async def _resolve_l1_memory_entries(
    backend: LocalMemoryBackend,
    source_ids: list[str],
) -> list[MemoryEntry]:
    """Resolve L1 source ids that are accepted memory entries (read-only).

    L1 ``source_ids`` mix confirmed-rule ids and memory-entry ids; only the
    latter resolve via ``get_memory_entry`` and carry the provenance we need to
    reach backing observations. Ids that don't resolve to a memory entry (e.g.
    confirmed rules) are skipped — they simply contribute no L1-backing
    observations. ``get_memory_entry`` is a pure read (Req 9).
    """
    entries: list[MemoryEntry] = []
    for source_id in source_ids:
        entry = await backend.structured_store.get_memory_entry(source_id)
        if entry is not None and entry.id:
            entries.append(entry)
    return entries


def _provenance_observation_ids(memory_entry: MemoryEntry) -> list[str]:
    """Extract observation ids from an entry's provenance (Req 7.6).

    Provenance shape is ``{session_id, observation_ids, agent_type,
    tool_name}``; ``observation_ids`` may be absent or non-list on legacy rows,
    so guard accordingly and keep only non-empty string ids.
    """
    provenance = memory_entry.provenance or {}
    raw_ids = provenance.get("observation_ids")
    if not isinstance(raw_ids, list):
        return []
    return [obs_id for obs_id in raw_ids if isinstance(obs_id, str) and obs_id]


async def _resolve_observations(
    backend: LocalMemoryBackend,
    observation_ids: list[str],
) -> list[Observation]:
    """Resolve observation ids to existing observations (read-only).

    Each id is fetched via ``verbatim_store.get``; missing observations are
    dropped so no L4 entry references a non-existent record (Req 8.2, 8.3).
    The store ``get`` is a pure read (Req 9).
    """
    observations: list[Observation] = []
    for observation_id in observation_ids:
        observation = await backend.verbatim_store.get(observation_id)
        if observation is not None and observation.id:
            observations.append(observation)
    return observations


def _observation_drilldown_entry(
    observation: Observation,
    project_name: str,
    *,
    why_included: str,
) -> PlanEntry:
    """Build an L4 observation drilldown entry — pointer only, no raw text.

    The ``DrilldownPointer`` carries the observation id plus the ``session_id``
    and ``project_name`` a consumer needs to expand the full content through
    ``read_api.get_observations`` without re-reading the plan (Req 7.1, 7.2,
    7.6). ``summary`` is left empty so no raw observation text leaks into L4.
    """
    return PlanEntry(
        layer="L4",
        source_ids=[observation.id],
        why_included=why_included,
        drilldown=DrilldownPointer(
            source_id=observation.id,
            read_surface="read_api.get_observations",
            locator={
                "session_id": observation.session_id,
                "project_name": project_name,
            },
        ),
    )
