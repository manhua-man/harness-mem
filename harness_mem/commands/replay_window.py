"""Replay window selector for v2.3.0 memory metabolism.

This module is the pure, read-only selector that chooses which
observations / pending candidates / historical truths / low-success
skills / repeat search hits a future metabolism pass would inspect. It
is intentionally **internal** — only ``mcp/server.py`` calls it (in
task 4.2). It is not exported from ``harness_mem.commands`` and has no
CLI surface.

See ``openspec/changes/v230-signals-and-replay-windows/design.md``,
section "Replay window selector", for the full contract:

* ``ReplayBudget`` carries hard caps per dimension plus a soft total
  token cap and the lookback window in days.
* ``ReplayDimension`` describes one selected slice (ids picked,
  whether it was truncated, total seen).
* ``ReplayWindow`` is the assembled artifact handed back to the
  caller; it can be replayed and audited via ``signal_ids`` and
  ``notes``.
* ``select_replay_window`` is async + pure; it does not write anything.
  Persistence as a ``MetabolismRun`` is the caller's job (task 4.2).

Task 3.3 adds budget-enforcement notes and the heuristic soft token cap.

v2.3.1 task 3.2 swaps the per-id heuristic for a content-based token
count via :mod:`harness_mem.commands.token_estimator`. The selector
now fetches each selected id's underlying text and sums actual token
counts; ``_DIM_TOKEN_WEIGHT`` survives as the third-tier fallback for
ids whose content can't be resolved (deleted blob, mid-flight schema
change, etc.). When the tokenizer falls back to its char-heuristic
path, an audit note records that fact ahead of the soft-budget line.
"""

from __future__ import annotations

import itertools
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from dataclasses import replace as dc_replace
from datetime import datetime, timedelta, timezone
from typing import cast

from harness_mem.commands import token_estimator
from harness_mem.commands.token_estimator import count_tokens
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore

# Pending candidates older than this are considered "stale" and eligible
# for the pending_candidates replay dimension. The threshold is matched
# to the v2.3 design's "stale pending" definition.
_STALE_PENDING_DAYS = 7

# Soft token-budget heuristic weights (per selected id). v2.3.0 stays a
# pure read-id selector — content-based token counting is deferred to
# v2.3.1+. See design.md "Replay window selector" for rationale.
_TOKENS_PER_OBSERVATION = 400
_TOKENS_PER_PENDING = 350
_TOKENS_PER_HISTORICAL = 300
_TOKENS_PER_LOW_SUCCESS_SKILL = 120
_TOKENS_PER_REPEAT_HIT = 40

# Cross-dimension trim order: when the soft cap is exceeded, drop tails
# from these dimensions in order (cheapest signals lost first).
_TRIM_ORDER: tuple[str, ...] = (
    "repeat_search_hits",
    "low_success_skills",
    "historical_truths",
    "pending_candidates",
    "observations",
)

_DIM_TOKEN_WEIGHT: dict[str, int] = {
    "observations": _TOKENS_PER_OBSERVATION,
    "pending_candidates": _TOKENS_PER_PENDING,
    "historical_truths": _TOKENS_PER_HISTORICAL,
    "low_success_skills": _TOKENS_PER_LOW_SUCCESS_SKILL,
    "repeat_search_hits": _TOKENS_PER_REPEAT_HIT,
}


async def _fetch_content_for_id(
    backend: LocalMemoryBackend,
    dim_name: str,
    entry_id: str,
) -> str | None:
    """Resolve the text behind one selected id, per dimension.

    Mapping (matches what each ``_select_*`` populates ``selected_ids``
    with):

    - ``observations``: ``Observation.raw_content`` from the verbatim
      blob.
    - ``pending_candidates``: rule / supersede / procedural candidates
      live in the same dim; try each get path in order, first hit wins.
    - ``historical_truths``: memory entry / confirmed rule / relation
      fact; try each in order.
    - ``low_success_skills``: skill activation_condition + steps.
    - ``repeat_search_hits``: target ids resolve to memory entries
      (mirrors v2.3.0 search_hit signal target_kind).

    Returns ``None`` when the id can't be resolved, which signals to
    the caller that it should fall back to ``_DIM_TOKEN_WEIGHT`` for
    this id.
    """
    structured = cast(LocalStructuredStore, backend.structured_store)

    if dim_name == "observations":
        verbatim = cast(LocalVerbatimStore, backend.verbatim_store)
        observation = await verbatim.get(entry_id)
        return observation.raw_content if observation else None

    if dim_name == "pending_candidates":
        rule = await structured.get_rule_candidate(entry_id)
        if rule is not None:
            return rule.pattern
        supersede = await structured.get_supersede_candidate(entry_id)
        if supersede is not None:
            return supersede.evidence
        procedural = await structured.get_procedural_candidate(entry_id)
        if procedural is not None:
            return procedural.activation_condition
        return None

    if dim_name == "historical_truths":
        entry = await structured.get_memory_entry(entry_id)
        if entry is not None:
            return entry.content
        confirmed_rule = await structured.get_confirmed_rule(entry_id)
        if confirmed_rule is not None:
            return confirmed_rule.pattern
        fact = await structured.get_relation_fact(entry_id)
        if fact is not None:
            return fact.evidence
        return None

    if dim_name == "low_success_skills":
        skill = await structured.get_skill(entry_id)
        if skill is None:
            return None
        return "\n".join((skill.activation_condition, *skill.steps))

    if dim_name == "repeat_search_hits":
        entry = await structured.get_memory_entry(entry_id)
        return entry.content if entry else None

    return None


async def _estimate_tokens_with_breakdown(
    backend: LocalMemoryBackend,
    dim_name: str,
    selected_ids: list[str],
) -> tuple[int, dict[str, int], int]:
    """Sum content-based token counts and return a per-id breakdown.

    The breakdown lets the soft-cap trim loop subtract the exact token
    contribution of each popped id, instead of falling back to the dim
    weight constant which would now be wrong (estimate is variable).

    Per-id pipeline:
      1. Fetch the underlying content via ``_fetch_content_for_id``.
      2. ``count_tokens(content)`` (tiktoken cl100k_base, with internal
         char-heuristic fallback baked into ``token_estimator``).
      3. If content fetch returns ``None`` or ``count_tokens`` returns
         ``0``, fall back to ``_DIM_TOKEN_WEIGHT[dim_name]`` for that
         id. This is the design's third-tier fallback.

    Returns ``(total, per_id, count_tokens_calls)``. The third value is
    how many ``count_tokens`` calls actually ran (i.e. how many ids
    resolved to non-empty content). The selector uses it to decide
    whether a ``tokenizer_fallback`` audit note is meaningful for this
    run — if zero calls happened, the module-level ``tokenizer_kind``
    is stale state from a prior run and shouldn't leak into notes.
    """
    if not selected_ids:
        return 0, {}, 0

    fallback = _DIM_TOKEN_WEIGHT[dim_name]
    per_id: dict[str, int] = {}
    total = 0
    count_tokens_calls = 0
    for entry_id in selected_ids:
        text = await _fetch_content_for_id(backend, dim_name, entry_id)
        if not text:
            tokens = fallback
        else:
            counted = count_tokens(text)
            count_tokens_calls += 1
            tokens = counted if counted > 0 else fallback
        per_id[entry_id] = tokens
        total += tokens
    return total, per_id, count_tokens_calls


@dataclass(frozen=True)
class ReplayBudget:
    """Hard caps on what the selector may return per dimension.

    ``signal_lookback_days`` defines the time horizon for both the
    ``time_range`` of the window and any signal-driven dimensions
    (e.g. repeat search hits). Older signals are out of scope.
    """

    max_observations: int = 200
    max_pending_candidates: int = 100
    max_historical_truths: int = 50
    max_low_success_skills: int = 20
    max_repeat_search_hits: int = 50
    max_total_tokens: int = 16000
    signal_lookback_days: int = 30


@dataclass(frozen=True)
class ReplayDimension:
    """A single dimension's slice of the replay window.

    ``selected_ids`` are the primary keys (memory entry / candidate /
    skill / signal target ids) chosen for replay. ``truncated`` is
    ``True`` when ``total_seen`` exceeded the dimension cap.
    """

    selected_ids: list[str]
    truncated: bool
    total_seen: int


@dataclass(frozen=True)
class ReplayWindow:
    """Audit-friendly description of one selector run's output.

    ``dimensions`` keys are stable: ``observations``,
    ``pending_candidates``, ``historical_truths``,
    ``low_success_skills``, ``repeat_search_hits``. Callers should
    rely on those literals.
    """

    time_range: tuple[datetime, datetime]
    dimensions: dict[str, ReplayDimension]
    signal_ids: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


async def select_replay_window(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: ReplayBudget,
) -> ReplayWindow:
    """Select the replay window for the next metabolism pass.

    Pure read-only: this function never mutates the backend and does
    not persist a ``MetabolismRun``. The caller wraps the result.
    """
    now = datetime.now(timezone.utc)
    time_range = (now - timedelta(days=budget.signal_lookback_days), now)

    observations, observations_signals = await _select_observations(
        backend, project_name, budget, time_range
    )
    pending_candidates, pending_signals = await _select_pending_candidates(
        backend, project_name, budget, time_range
    )
    historical_truths, historical_signals = await _select_historical_truths(
        backend, project_name, budget, time_range
    )
    low_success_skills, skill_signals = await _select_low_success_skills(
        backend, project_name, budget, time_range
    )
    (
        repeat_search_hits,
        _search_hit_signals,
        signal_ids_by_target,
    ) = await _select_repeat_search_hits(
        backend, project_name, budget, time_range
    )

    signals_query_capped = signal_ids_by_target.pop(
        "__signals_query_capped__", None
    ) is not None

    # Resolve true pool size for the observations dimension when the
    # cap+1 probe reported truncation. Other four dimensions already
    # aggregate the full pool in 3.2, so total_seen is already truthful.
    if observations.truncated:
        verbatim = cast(LocalVerbatimStore, backend.verbatim_store)
        true_pool = await verbatim.count_recent_observations(
            project_name=project_name,
            since=time_range[0],
        )
        observations = dc_replace(observations, total_seen=true_pool)

    dimensions: dict[str, ReplayDimension] = {
        "observations": observations,
        "pending_candidates": pending_candidates,
        "historical_truths": historical_truths,
        "low_success_skills": low_success_skills,
        "repeat_search_hits": repeat_search_hits,
    }

    notes: list[str] = []
    # Hard-cap notes in the dimension's iteration order.
    for name, dim in dimensions.items():
        if dim.truncated:
            notes.append(
                f"truncated_within_{name}: {len(dim.selected_ids)}/{dim.total_seen}"
            )
    if signals_query_capped:
        notes.append("retrieval_signals_query_capped")

    # Soft total-token cap. Always emit `soft_token_budget` (audit data),
    # then trim tails in fixed cross-dimension order if over budget.
    # v2.3.1 task 3.2: estimate is content-based via ``count_tokens``,
    # with a per-id breakdown so the trim loop can subtract the exact
    # contribution of each popped id (estimate is no longer per-id
    # constant). ``_DIM_TOKEN_WEIGHT`` survives as the third-tier
    # fallback when content fetch returns nothing.
    dim_token_breakdown: dict[str, dict[str, int]] = {}
    estimate = 0
    total_count_tokens_calls = 0
    for name, dim in dimensions.items():
        dim_total, per_id, calls = await _estimate_tokens_with_breakdown(
            backend, name, dim.selected_ids
        )
        dim_token_breakdown[name] = per_id
        estimate += dim_total
        total_count_tokens_calls += calls

    trimmed_dims: list[str] = []
    if estimate > budget.max_total_tokens:
        for trim_name in _TRIM_ORDER:
            if estimate <= budget.max_total_tokens:
                break
            dim = dimensions[trim_name]
            new_ids = list(dim.selected_ids)
            per_id_tokens = dim_token_breakdown[trim_name]
            fallback_weight = _DIM_TOKEN_WEIGHT[trim_name]
            popped = 0
            while estimate > budget.max_total_tokens and new_ids:
                dropped = new_ids.pop()
                # ``per_id_tokens`` always contains every id we estimated
                # for; ``.get`` with the dim weight is a defensive guard
                # that keeps the trim loop honest even if the maps ever
                # disagree.
                estimate -= per_id_tokens.get(dropped, fallback_weight)
                popped += 1
            if popped > 0:
                # Soft trim counts as truncation; total_seen stays at the
                # pre-trim true pool — soft trim doesn't change "how many
                # existed", it changes "how many we kept".
                dimensions[trim_name] = dc_replace(
                    dim, selected_ids=new_ids, truncated=True
                )
                trimmed_dims.append(trim_name)

    # Surface tokenizer fallback BEFORE the soft-budget line so the
    # audit trail explains the estimate's accuracy first. We only emit
    # the note when this run actually called ``count_tokens`` at least
    # once — otherwise ``tokenizer_kind`` could be stale state from a
    # prior run and the note would mislead.
    if (
        total_count_tokens_calls > 0
        and token_estimator.tokenizer_kind == "char-heuristic"
    ):
        notes.append("tokenizer_fallback: char-heuristic")
    notes.append(f"soft_token_budget: {estimate}/{budget.max_total_tokens}")
    if trimmed_dims:
        notes.append(f"trimmed_for_token_budget: {','.join(trimmed_dims)}")

    # Rebuild signal_ids after trimming. Only the repeat_search_hits
    # dimension contributes signal ids in 3.2/3.3; if its tail was
    # trimmed we must drop the supporting signal ids for dropped
    # targets. The other four dims contribute empty signal lists.
    repeats_dim = dimensions["repeat_search_hits"]
    rebuilt_repeat_signals = list(
        itertools.chain.from_iterable(
            signal_ids_by_target.get(target_id, [])
            for target_id in repeats_dim.selected_ids
        )
    )
    signal_ids = list(
        itertools.chain.from_iterable(
            (
                observations_signals,
                pending_signals,
                historical_signals,
                skill_signals,
                rebuilt_repeat_signals,
            )
        )
    )

    return ReplayWindow(
        time_range=time_range,
        dimensions=dimensions,
        signal_ids=signal_ids,
        notes=notes,
    )


async def _select_observations(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: ReplayBudget,
    time_range: tuple[datetime, datetime],
) -> tuple[ReplayDimension, list[str]]:
    """Recent observations dimension.

    Pulls observations whose ``timestamp`` falls inside ``time_range``,
    newest first. We fetch ``max_observations + 1`` so that a single
    extra row reveals truncation without a separate ``COUNT`` query.
    Note: when truncated, ``total_seen`` reflects only what we fetched
    (``cap + 1``), not the true tail. Exact counts are deferred to
    task 3.3, which will decide the note format.
    """
    cap = budget.max_observations
    verbatim = cast(LocalVerbatimStore, backend.verbatim_store)
    fetched = await verbatim.recent_observations(
        project_name=project_name,
        since=time_range[0],
        limit=cap + 1,
    )
    truncated = len(fetched) > cap
    selected_ids = [obs.id for obs in fetched[:cap]]
    total_seen = len(fetched)
    return (
        ReplayDimension(
            selected_ids=selected_ids,
            truncated=truncated,
            total_seen=total_seen,
        ),
        [],
    )


async def _select_pending_candidates(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: ReplayBudget,
    time_range: tuple[datetime, datetime],
) -> tuple[ReplayDimension, list[str]]:
    """Stale pending candidates across all three candidate types.

    Stale = ``created_at`` older than :data:`_STALE_PENDING_DAYS`. We
    union rule / supersede / procedural pending candidates, sort by
    ``created_at ASC`` (oldest first), then cap.
    """
    store = backend.structured_store
    rule_pending = await store.list_rule_candidates(project_name, status="pending")
    supersede_pending = await store.list_supersede_candidates(
        project_name, status="pending"
    )
    procedural_pending = await store.list_procedural_candidates(
        project_name, status="pending"
    )

    cutoff = datetime.now(timezone.utc) - timedelta(days=_STALE_PENDING_DAYS)
    merged: list[tuple[datetime, str]] = []
    for rule in rule_pending:
        created = _normalize_dt(rule.created_at)
        if created is None or created >= cutoff:
            continue
        merged.append((created, rule.id))
    for supersede in supersede_pending:
        created = _normalize_dt(supersede.created_at)
        if created is None or created >= cutoff:
            continue
        merged.append((created, supersede.id))
    for procedural in procedural_pending:
        created = _normalize_dt(procedural.created_at)
        if created is None or created >= cutoff:
            continue
        merged.append((created, procedural.id))

    merged.sort(key=lambda pair: pair[0])
    cap = budget.max_pending_candidates
    total_seen = len(merged)
    truncated = total_seen > cap
    selected_ids = [candidate_id for _, candidate_id in merged[:cap]]
    return (
        ReplayDimension(
            selected_ids=selected_ids,
            truncated=truncated,
            total_seen=total_seen,
        ),
        [],
    )


async def _select_historical_truths(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: ReplayBudget,
    time_range: tuple[datetime, datetime],
) -> tuple[ReplayDimension, list[str]]:
    """Historical truths dimension.

    A truth is "historical" once ``valid_to`` is set. We surface those
    that became historical inside ``time_range`` so the metabolism
    pass focuses on recent supersedes rather than ancient history.
    """
    store = backend.structured_store
    entries = await store.list_memory_entries(project_name, include_history=True)
    rules = await store.list_confirmed_rules(project_name, include_history=True)
    facts = await store.list_relation_facts(project_name, include_history=True)

    window_start = time_range[0]
    historical: list[tuple[datetime, str]] = []
    for entry in entries:
        valid_to = _normalize_dt(entry.valid_to)
        if valid_to is None or valid_to < window_start:
            continue
        historical.append((valid_to, entry.id))
    for rule in rules:
        valid_to = _normalize_dt(rule.valid_to)
        if valid_to is None or valid_to < window_start:
            continue
        historical.append((valid_to, rule.id))
    for fact in facts:
        valid_to = _normalize_dt(fact.valid_to)
        if valid_to is None or valid_to < window_start:
            continue
        historical.append((valid_to, fact.id))

    # Most-recent supersedes first.
    historical.sort(key=lambda pair: pair[0], reverse=True)
    cap = budget.max_historical_truths
    total_seen = len(historical)
    truncated = total_seen > cap
    selected_ids = [item_id for _, item_id in historical[:cap]]
    return (
        ReplayDimension(
            selected_ids=selected_ids,
            truncated=truncated,
            total_seen=total_seen,
        ),
        [],
    )


async def _select_low_success_skills(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: ReplayBudget,
    time_range: tuple[datetime, datetime],
) -> tuple[ReplayDimension, list[str]]:
    """Low-success-rate skills dimension.

    Predicate (boolean OR):
    - ``success_rate`` is set and below 0.5, or
    - ``usage_count`` >= 5 with zero successes.

    Sorted worst-first: lowest known ``success_rate`` first (None goes
    last), then most-used (highest ``usage_count``) on ties.
    """
    store = backend.structured_store
    skills = await store.list_skills(project_name, status="active")

    matched = [
        skill
        for skill in skills
        if (skill.success_rate is not None and skill.success_rate < 0.5)
        or (skill.usage_count >= 5 and skill.success_count == 0)
    ]
    matched.sort(
        key=lambda s: (
            s.success_rate is None,
            s.success_rate if s.success_rate is not None else 0.0,
            -s.usage_count,
        )
    )

    cap = budget.max_low_success_skills
    total_seen = len(matched)
    truncated = total_seen > cap
    selected_ids = [skill.id for skill in matched[:cap]]
    return (
        ReplayDimension(
            selected_ids=selected_ids,
            truncated=truncated,
            total_seen=total_seen,
        ),
        [],
    )


async def _select_repeat_search_hits(
    backend: LocalMemoryBackend,
    project_name: str,
    budget: ReplayBudget,
    time_range: tuple[datetime, datetime],
) -> tuple[ReplayDimension, list[str], dict[str, list[str]]]:
    """Repeat search-hit aggregation dimension.

    Aggregates ``search_hit`` retrieval signals by ``target_id`` over
    the lookback window. Only targets with count >= 2 ("repeat") are
    surfaced. Returns the supporting signal ids for the *selected*
    targets so they can be persisted on the run record.

    The third return value (``signal_ids_by_target``) is a map of every
    repeated ``target_id`` -> the signal ids that supported it. This
    asymmetric extra payload exists so the orchestrator can rebuild
    ``window.signal_ids`` after the soft-token cap drops some targets.
    The asymmetry is intentional and isolated to the orchestrator.
    """
    store = backend.structured_store
    signals = await store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=time_range[0],
        limit=10000,
    )

    counts: Counter[str] = Counter()
    signal_ids_by_target: dict[str, list[str]] = defaultdict(list)
    for signal in signals:
        counts[signal.target_id] += 1
        signal_ids_by_target[signal.target_id].append(signal.id)

    repeats = [(target_id, count) for target_id, count in counts.items() if count >= 2]
    repeats.sort(key=lambda pair: pair[1], reverse=True)

    cap = budget.max_repeat_search_hits
    total_seen = len(repeats)
    truncated = total_seen > cap
    selected = repeats[:cap]
    selected_ids = [target_id for target_id, _ in selected]

    contributing_signal_ids: list[str] = []
    for target_id, _ in selected:
        contributing_signal_ids.extend(signal_ids_by_target[target_id])

    # Trim the per-target map down to the selected targets so the
    # orchestrator can use it as authoritative truth for what signal ids
    # remain after any later trim step.
    pruned_map: dict[str, list[str]] = {
        target_id: signal_ids_by_target[target_id] for target_id in selected_ids
    }
    # Track whether the underlying signal query hit its own cap (10000);
    # the orchestrator emits a `retrieval_signals_query_capped` note in
    # that case. We piggy-back on the standard return tuple by leaving a
    # sentinel key in the map. Pre-existing target ids never collide
    # with this one because they are UUIDs.
    if len(signals) == 10000:
        pruned_map["__signals_query_capped__"] = []

    return (
        ReplayDimension(
            selected_ids=selected_ids,
            truncated=truncated,
            total_seen=total_seen,
        ),
        contributing_signal_ids,
        pruned_map,
    )


def _normalize_dt(value: object) -> datetime | None:
    """Coerce a datetime-or-iso-string to a tz-aware UTC datetime.

    Mirrors the helper that ``read_api`` and ``local_verbatim_store``
    each carry privately. A small inline copy keeps the selector free
    of cross-module reach-in.
    """
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
