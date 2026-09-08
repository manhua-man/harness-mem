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

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from harness_mem.commands import token_estimator
from harness_mem.commands.support import resolve_project_name
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.core.schemas.context_assembly_plan import (
    LAYER_ORDER,
    Budget,
    ContextAssemblyPlan,
    ContextProjectionReceipt,
    Layer,
    LayerId,
    PlanEntry,
    ProjectionOutcome,
    TokenCountBasis,
    TruncationAccounting,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.temporal_conflicts import (
    current_project_version,
    version_conflict_reason,
)

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


@dataclass(slots=True)
class _BudgetTrace:
    """Internal, content-bearing trace discarded after receipt construction."""

    before_text: str = ""
    after_text: str = ""
    evicted_source_ids: list[str] = field(default_factory=list)
    truncated_source_ids: list[str] = field(default_factory=list)


def _coerce_budget(
    value: int | Budget | dict[str, int | None],
    *,
    default_max_entries: int,
) -> Budget:
    if isinstance(value, Budget):
        return value.model_copy(deep=True)
    if isinstance(value, int):
        return Budget(max_entries=value)
    payload = dict(value)
    payload.setdefault("max_entries", default_max_entries)
    return Budget.from_dict(payload)


def _truncate_to_char_budget(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars == 1:
        return "\u2026"
    return value[: max_chars - 1].rstrip() + "\u2026"


def _projection_text(entries: list[PlanEntry]) -> str:
    return "\n".join(entry.summary for entry in entries if entry.summary)


def _source_ids(entries: list[PlanEntry]) -> list[str]:
    return _dedupe(
        source_id
        for entry in entries
        for source_id in entry.source_ids
        if source_id
    )


def _dedupe(values: Iterable[object]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, str) and value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _estimated_tokens(value: str) -> tuple[int, str]:
    if not value:
        return 0, "tokenizer_estimate"
    count = token_estimator.count_tokens(value)
    basis = (
        "character_estimate"
        if token_estimator.tokenizer_kind == "char-heuristic"
        else "tokenizer_estimate"
    )
    return count, basis


def _observed_usage_total(value: int | Mapping[str, Any] | None) -> int | None:
    """Resolve Pi/OpenAI-style usage without tying the plan to one host."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if not isinstance(value, Mapping):
        return None

    nested = value.get("usage")
    if isinstance(nested, Mapping):
        resolved = _observed_usage_total(nested)
        if resolved is not None:
            return resolved

    for key in ("total_tokens", "totalTokens"):
        total = value.get(key)
        if isinstance(total, int) and not isinstance(total, bool) and total >= 0:
            return total

    component_groups = (
        ("input_tokens", "inputTokens"),
        ("output_tokens", "outputTokens"),
        ("cache_read_tokens", "cacheReadTokens"),
        ("cache_write_tokens", "cacheWriteTokens"),
    )
    components: list[int] = []
    found = False
    for aliases in component_groups:
        component = next(
            (
                value[key]
                for key in aliases
                if isinstance(value.get(key), int)
                and not isinstance(value.get(key), bool)
                and value[key] >= 0
            ),
            0,
        )
        if any(key in value for key in aliases):
            found = True
        components.append(component)
    return sum(components) if found else None


def _receipt_source_revision(
    layers: list[Layer],
    explicit_revision: str | None,
) -> str | None:
    if explicit_revision:
        return explicit_revision
    revisions = {
        str(entry.drilldown.locator["source_revision"])
        for layer in layers
        for entry in layer.entries
        if entry.drilldown is not None
        and entry.drilldown.locator.get("source_revision")
    }
    return next(iter(revisions)) if len(revisions) == 1 else None


def _projection_receipt(
    layers: list[Layer],
    traces: list[_BudgetTrace],
    *,
    observed_usage: int | Mapping[str, Any] | None,
    source_revision: str | None,
) -> ContextProjectionReceipt:
    before_text = "\n".join(trace.before_text for trace in traces if trace.before_text)
    after_text = "\n".join(trace.after_text for trace in traces if trace.after_text)
    before_tokens, before_basis = _estimated_tokens(before_text)
    after_tokens, after_basis = _estimated_tokens(after_text)

    observed_total = _observed_usage_total(observed_usage)
    if observed_total is not None:
        after_tokens = observed_total
        if any(trace.evicted_source_ids or trace.truncated_source_ids for trace in traces):
            before_tokens = max(before_tokens, observed_total)
        else:
            before_tokens = observed_total
        token_basis: TokenCountBasis = "observed_usage"
    elif "character_estimate" in {before_basis, after_basis}:
        token_basis = "character_estimate"
    else:
        token_basis = "tokenizer_estimate"

    kept_source_ids = _source_ids(
        [entry for layer in layers for entry in layer.entries]
    )
    kept_id_set = set(kept_source_ids)
    evicted_source_ids = [
        source_id
        for source_id in _dedupe(
            source_id
            for trace in traces
            for source_id in trace.evicted_source_ids
        )
        if source_id not in kept_id_set
    ]
    truncated_source_ids = _dedupe(
        source_id
        for trace in traces
        for source_id in trace.truncated_source_ids
    )
    outcome: ProjectionOutcome = (
        "truncated"
        if truncated_source_ids
        else "evicted"
        if evicted_source_ids
        else "none"
    )
    drilldown = [
        entry.drilldown.model_copy(deep=True)
        for layer in layers
        for entry in layer.entries
        if entry.drilldown is not None
    ]
    return ContextProjectionReceipt(
        source_revision=_receipt_source_revision(layers, source_revision),
        before_tokens=before_tokens,
        after_tokens=after_tokens,
        kept_source_ids=kept_source_ids,
        evicted_source_ids=evicted_source_ids,
        token_basis=token_basis,
        outcome=outcome,
        summary_generated=False,
        drilldown=drilldown,
    )


async def assemble_context_plan(
    backend: LocalMemoryBackend,
    *,
    project_name: str | None,
    query: str | None = None,
    budgets: dict[str, int | Budget | dict[str, int | None]] | None = None,
    observed_usage: int | Mapping[str, Any] | None = None,
    source_revision: str | None = None,
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
    effective_budgets: dict[str, int | Budget | dict[str, int | None]] = {
        **DEFAULT_BUDGETS,
        **(budgets or {}),
    }
    budget_by_layer: dict[LayerId, Budget] = {
        layer_id: _coerce_budget(
            effective_budgets[layer_id],
            default_max_entries=DEFAULT_BUDGETS[layer_id],
        )
        for layer_id in LAYER_ORDER
    }

    budget_trace: list[_BudgetTrace] = []
    l0 = await _build_l0(
        backend, resolved, budget_by_layer["L0"], budget_trace=budget_trace
    )
    l1 = await _build_l1(
        backend, resolved, budget_by_layer["L1"], budget_trace=budget_trace
    )
    l2 = await _build_l2(
        backend, resolved, budget_by_layer["L2"], budget_trace=budget_trace
    )
    topic_entries = (
        await search_current_knowledge(
            backend,
            project_name=resolved,
            query=query,
            limit=max(1, budget_by_layer["L3"].max_entries),
        )
        if query and query.strip()
        else []
    )
    l3 = _apply_budget(
        "L3",
        [
            PlanEntry(
                layer="L3",
                source_ids=[entry.id],
                why_included="topic_recall:current_knowledge",
                summary=_truncate_summary(entry.statement),
            )
            for entry in topic_entries
        ],
        budget_by_layer["L3"],
        budget_trace=budget_trace,
    )
    l4 = _apply_budget(
        "L4",
        [],
        budget_by_layer["L4"],
        budget_trace=budget_trace,
    )

    layers = [l0, l1, l2, l3, l4]
    receipt = _projection_receipt(
        layers,
        budget_trace,
        observed_usage=observed_usage,
        source_revision=source_revision,
    )
    context_budget = {
        "raw_tokens": 0,
        "summary_tokens": receipt.after_tokens,
        "retrieved_tokens": receipt.after_tokens,
        "total_tokens": receipt.after_tokens,
        "budget_tokens": sum(
            layer.budget.max_chars
            if layer.budget.max_chars is not None
            else layer.budget.max_entries * 200
            for layer in layers
        )
        // 4,
    }
    return ContextAssemblyPlan(
        project_name=resolved,
        query=query,
        layers=layers,
        context_budget=context_budget,
        compaction_outcome=receipt.outcome,
        projection_receipt=receipt,
    )


def _apply_budget(
    layer_id: LayerId,
    candidates: list[PlanEntry],
    budget: Budget,
    *,
    budget_trace: list["_BudgetTrace"] | None = None,
) -> Layer:
    """Apply entry and character caps without inventing a compaction summary.

    Character limits apply to inline summaries. Drilldown-only entries carry
    no source text and therefore consume no character budget. A summary that
    crosses the remaining boundary is visibly truncated; whole entries lost
    to either cap are recorded as evicted, never as compacted.
    """
    available = len(candidates)
    selected: list[PlanEntry] = []
    evicted: list[PlanEntry] = []
    truncated_source_ids: list[str] = []
    remaining_chars = budget.max_chars

    for candidate in candidates:
        if len(selected) >= budget.max_entries:
            evicted.append(candidate)
            continue

        summary = candidate.summary
        if remaining_chars is None or not summary:
            selected.append(candidate)
            continue

        separator_chars = 1 if any(entry.summary for entry in selected) else 0
        required_chars = separator_chars + len(summary)
        if remaining_chars <= separator_chars:
            evicted.append(candidate)
            continue
        if required_chars <= remaining_chars:
            selected.append(candidate)
            remaining_chars -= required_chars
            continue

        available_summary_chars = remaining_chars - separator_chars
        selected.append(
            candidate.model_copy(
                update={
                    "summary": _truncate_to_char_budget(
                        summary, available_summary_chars
                    )
                }
            )
        )
        truncated_source_ids.extend(candidate.source_ids)
        remaining_chars = 0

    if budget_trace is not None:
        budget_trace.append(
            _BudgetTrace(
                before_text=_projection_text(candidates),
                after_text=_projection_text(selected),
                evicted_source_ids=_source_ids(evicted),
                truncated_source_ids=truncated_source_ids,
            )
        )

    included = len(selected)
    return Layer(
        layer=layer_id,
        entries=selected,
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
    *,
    budget_trace: list[_BudgetTrace] | None = None,
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
    return _apply_budget("L0", candidates, budget, budget_trace=budget_trace)


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
    *,
    budget_trace: list[_BudgetTrace] | None = None,
) -> Layer:
    """Build L1 exclusively from the current knowledge authority."""
    candidates: list[PlanEntry] = []
    repo_version = current_project_version(backend, project_name)
    entries: list[KnowledgeEntry] = (
        await backend.structured_store.knowledge_store.list_entries(project_name)
    )
    for entry in entries:
        if not entry.id or version_conflict_reason(
            entry.statement,
            current_version=repo_version,
        ):
            continue
        candidates.append(
            PlanEntry(
                layer="L1",
                source_ids=[entry.id],
                why_included="essential:current_knowledge",
                summary=_truncate_summary(entry.statement),
            )
        )

    return _apply_budget("L1", candidates, budget, budget_trace=budget_trace)


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
    *,
    budget_trace: list[_BudgetTrace] | None = None,
) -> Layer:
    """L2 active task (Req 4.1-4.6, 10.1).

    Two sources, in fixed order:

    1. **Recent task handoffs** via ``get_latest_handoffs`` — emitted as
       ``active:recent_handoff`` entries whose ``source_ids`` reference the
       handoff id and whose ``summary`` is the handoff summary.
    2. **Recently-surfaced current knowledge**, derived read-only from
       ``RetrievalSignal`` records targeting ``knowledge_entry`` rows within
       :data:`RECENTLY_SURFACED_WINDOW_DAYS`. Emitted as
       ``active:recently_surfaced``.

    Every step is a pure read: ``get_latest_handoffs``,
    ``query_retrieval_signals`` and ``knowledge_store.get_entry`` perform no
    writes, so the layer emits no new ``RetrievalSignal`` (Req 4.5, 9). The
    budget cap (max 7) is applied last via
    :func:`_apply_budget` (Req 4.4); an empty source yields a well-formed empty
    layer with no error (Req 4.6).
    """
    candidates: list[PlanEntry] = []
    repo_version = current_project_version(backend, project_name)

    # Part A — recent handoffs (most recent first). ``get_latest_handoffs``
    # orders by ``last_activity`` descending and is a pure read.
    handoffs: list[TaskHandoff] = await backend.structured_store.get_latest_handoffs(
        project_name,
        limit=budget.max_entries,
    )
    for handoff in handoffs:
        # Drop any handoff without a resolvable id rather than emit an entry
        # with empty source_ids (Req 8.3).
        if (
            not handoff.id
            or handoff.status not in {"in_progress", "pending", "blocked"}
            or version_conflict_reason(handoff.summary, current_version=repo_version)
        ):
            continue
        candidates.append(
            PlanEntry(
                layer="L2",
                source_ids=[handoff.id],
                why_included="active:recent_handoff",
                summary=_truncate_summary(handoff.summary),
            )
        )

    # Part B — recently-surfaced readable current-truth entries, derived
    # read-only from retrieval signals (Req 4.1, 4.5, 10.1).
    for entry in await _recently_surfaced_entries(backend, project_name):
        if version_conflict_reason(entry.statement, current_version=repo_version):
            continue
        candidates.append(
            PlanEntry(
                layer="L2",
                source_ids=[entry.id],
                why_included="active:recently_surfaced",
                summary=_truncate_summary(entry.statement),
            )
        )

    return _apply_budget("L2", candidates, budget, budget_trace=budget_trace)


async def _recently_surfaced_entries(
    backend: LocalMemoryBackend,
    project_name: str,
) -> list[KnowledgeEntry]:
    """Resolve current knowledge recently returned by search or wake."""
    since = datetime.now(timezone.utc) - timedelta(days=RECENTLY_SURFACED_WINDOW_DAYS)

    wake_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        target_kind="knowledge_entry",
        since=since,
    )
    search_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        target_kind="knowledge_entry",
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

    entries: list[KnowledgeEntry] = []
    for target_id in ordered_ids:
        entry = await backend.structured_store.knowledge_store.get_entry(
            target_id,
            project_name=project_name,
        )
        if entry is None or not entry.id:
            continue
        entries.append(entry)

    return entries
