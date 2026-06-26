"""Metabolism pass selector for v2.3.1.

This module produces three classes of suggestion candidates from the
v2.3.0 signals + replay window foundation: merge suggestions,
stale-truth suggestions, and supersede suggestions. It is intentionally
internal — only ``mcp/server.py`` calls it (task 5.2). It has no CLI
surface and is not exported from ``harness_mem.commands``.

Algorithm contract:

* ``_propose_merges`` is window-seeded (entry-entry only in v2.3.1).
* ``_propose_stale`` is project-scoped, NOT window-scoped — silent
  truth is by definition missing from the window.
* ``_propose_supersedes`` is window-bound over historical_truths, but
  intentionally deferred in v2.3.1 until a stronger supersede signal is
  specified.

The pass is fully read-only: it selects suggestions but leaves
``MetabolismRun`` and candidate persistence to the MCP tool layer.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import TYPE_CHECKING, Literal, cast

from harness_mem.commands.replay_window import (
    ReplayBudget,
    ReplayWindow,
    select_replay_window,
)
from harness_mem.core.schemas.merge_suggestion_candidate import MergeSuggestionCandidate
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.core.schemas.stale_truth_suggestion_candidate import (
    StaleTruthSuggestionCandidate,
)
from harness_mem.core.schemas.supersede_candidate import SupersedeCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore

if TYPE_CHECKING:  # pragma: no cover - import-time only
    import numpy as np

# Per-candidate cap on supporting signal ids. Each persisted blob carries
# its evidence list; capping keeps the JSON small and bounded — the
# similarity score itself is the primary trigger, signals are corroboration.
_MAX_EVIDENCE_SIGNALS_PER_CANDIDATE = 20

# Project-wide entry scan cap for stale detection. The structured store
# has no native time filter on (created_at, last_accessed_at), so we read
# up to this many current entries per project. When the cap fires the
# pass appends ``stale_entry_scan_capped: <limit>`` to its run notes for
# audit visibility — callers can correlate the truncation against the
# selected pool size.
STALE_SCAN_ENTRY_LIMIT = 10000

# Stale-proposer scope. The candidate schema's ``target_kind`` Literal
# also accepts ``"relation_fact"`` for forward-compat, but v2.3.1
# excludes facts (RelationFact has no v2.2 surface field). Narrowing
# here lets the kind value flow from the proposer's working tuple into
# ``StaleTruthSuggestionCandidate`` without ``cast``.
_StaleKind = Literal["memory_entry", "confirmed_rule"]

# Sentinel used while the metabolism pass remains run-id-less. Phase 5.2
# (mcp tool wiring) overwrites this with the real ``MetabolismRun.id``
# before persistence. The schema's ``metabolism_run_id: str`` only requires
# a non-empty string, so this round-trips cleanly through to/from_dict.
_PENDING_RUN_ID_SENTINEL = "pending"


@dataclass(frozen=True)
class MetabolismPass:
    """Result of one metabolism pass.

    ``window`` is preserved for audit (replay) — same ReplayWindow the
    selector returned, persisted into ``MetabolismRun.input_window`` in
    the MCP tool layer (task 5.2).

    ``notes`` is a mutable audit channel proposers may append to (e.g.
    ``stale_scan_truncated: 50/137`` or ``stale_entry_scan_capped: 10000``).
    Phase 5.2 surfaces these into ``MetabolismRun.notes`` when persisting
    the run record. The list itself is mutable even though the dataclass
    is frozen; callers should treat it as a one-pass write log.
    """

    window: ReplayWindow
    merge: list[MergeSuggestionCandidate]
    stale: list[StaleTruthSuggestionCandidate]
    supersede: list[SupersedeCandidate]
    notes: list[str] = field(default_factory=list)


async def select_metabolism_pass(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: ReplayBudget,
    similarity_threshold: float = 0.85,
    stale_silence_days: int = 60,
    max_merge_pairs: int = 20,
    max_stale_suggestions: int = 50,
) -> MetabolismPass:
    """Run a metabolism pass over signals + replay window.

    Pure read-only: this function never mutates the backend and does
    not persist any candidate or ``MetabolismRun``. The MCP tool layer
    (task 5.2) is responsible for persisting candidates and the run
    record. This keeps the pass a pure local algorithm with stable
    test boundaries.

    v2.3.1 implements merge and stale suggestion selection. Supersede
    remains intentionally deferred: similarity over historical truths is
    not strong enough by itself to rewrite truth lineage safely.
    """
    window = await select_replay_window(
        backend, project_name=project_name, budget=budget
    )
    notes: list[str] = []
    merge = await _propose_merges(
        backend,
        window,
        project_name=project_name,
        threshold=similarity_threshold,
        max_pairs=max_merge_pairs,
        max_pool_entries=budget.max_observations,
        notes=notes,
    )
    stale = await _propose_stale(
        backend,
        project_name=project_name,
        silence_days=stale_silence_days,
        max_suggestions=max_stale_suggestions,
        notes=notes,
    )
    supersede = await _propose_supersedes(backend, window, notes=notes)
    return MetabolismPass(
        window=window,
        merge=merge,
        stale=stale,
        supersede=supersede,
        notes=notes,
    )


async def _propose_merges(
    backend: LocalMemoryBackend,
    window: ReplayWindow,
    *,
    project_name: str,
    threshold: float,
    max_pairs: int,
    max_pool_entries: int,
    notes: list[str],
) -> list[MergeSuggestionCandidate]:
    """Window-seeded merge proposal (entry-entry only in v2.3.1).

    Pool = ``window.repeat_search_hits`` targets that resolve to
    ``memory_entry`` ∪ current ``MemoryEntry`` rows (``valid_to is null``)
    whose ``created_at`` / ``last_accessed_at`` falls inside
    ``window.time_range``. Historical truths and confirmed rules stay
    out of the pool — rule merges are deferred to v2.3.2+ per
    design.md "Suggestion 选择算法".

    Similarity reuses the shared embedding loader in a model-consistent
    way: read ``vec_embeddings`` only when ``model_id`` matches the
    active embedding model; otherwise encode ``entry.content`` in
    memory. The pass never writes to ``vec_embeddings``.

    Each candidate is persisted with ``metabolism_run_id="pending"``;
    phase 5.2 (mcp tool wiring) overwrites this with the real run id
    before saving. The pass itself has no run lifecycle.
    """
    if max_pool_entries <= 0 or max_pairs <= 0:
        return []

    store = cast(LocalStructuredStore, backend.structured_store)
    window_start, window_end = window.time_range

    # Leg 1: search-hit signals are the bridge from window.repeat_search_hits
    # (which only carries target_ids, no kind) to "this id is a memory_entry".
    # Pulling them once also gives us the evidence_signal_ids to attach to
    # candidates further down without a second query.
    repeat_dim = window.dimensions.get("repeat_search_hits")
    repeat_target_set: set[str] = set(repeat_dim.selected_ids) if repeat_dim else set()

    hit_signals: list[RetrievalSignal] = []
    if repeat_target_set:
        hit_signals = await store.query_retrieval_signals(
            project_name,
            signal_type="search_hit",
            since=window_start,
            limit=10000,
        )

    repeat_entry_ids: set[str] = {
        signal.target_id
        for signal in hit_signals
        if signal.target_kind == "memory_entry"
        and signal.target_id in repeat_target_set
    }

    # Leg 2: current memory entries co-active in the same time band.
    # Pull a generous slice from the structured store and filter in
    # Python — the structured store has no native time_range filter on
    # the (created_at, last_accessed_at) pair, and the cap below keeps
    # the resulting pool bounded regardless.
    current_entries = await store.list_memory_entries(
        project_name,
        limit=10000,
        status="accepted",
        include_history=False,
    )
    co_active_ids: list[str] = []
    for entry in current_entries:
        created = entry.created_at
        last = entry.last_accessed_at
        in_window = False
        if created is not None and window_start <= created <= window_end:
            in_window = True
        elif last is not None and window_start <= last <= window_end:
            in_window = True
        if in_window:
            co_active_ids.append(entry.id)
    co_active_ids = sorted(co_active_ids)[:max_pool_entries]

    pool_ids = sorted(set(co_active_ids) | repeat_entry_ids)
    if len(pool_ids) < 2:
        return []

    # Embedding lookup — model-consistent: only read vec_embeddings rows
    # whose model_id matches the active model. On miss or mismatch, encode
    # entry.content in memory. The pass MUST NOT write to vec_embeddings;
    # backfills belong in commands/maintenance.py.
    embeddings = await _load_pool_embeddings(backend, store, pool_ids)
    if len(embeddings) < 2:
        return []

    # Score every distinct pair (lex-sorted so a < b naturally) and keep
    # those at or above the similarity threshold.
    scored_pairs: list[tuple[float, str, str]] = []
    embedded_ids = sorted(embeddings.keys())
    for a, b in itertools.combinations(embedded_ids, 2):
        sim = _cosine_similarity(embeddings[a], embeddings[b])
        if sim >= threshold:
            scored_pairs.append((sim, a, b))

    # Highest-similarity first, capped to keep the candidate pool bounded.
    scored_pairs.sort(key=lambda triple: triple[0], reverse=True)
    scored_pairs = scored_pairs[:max_pairs]
    if not scored_pairs:
        return []

    # Pre-bucket signal ids by target so candidate construction is O(pairs)
    # rather than O(pairs × signals).
    signals_by_target: dict[str, list[str]] = {}
    for signal in hit_signals:
        signals_by_target.setdefault(signal.target_id, []).append(signal.id)

    candidates: list[MergeSuggestionCandidate] = []
    for sim, a, b in scored_pairs:
        evidence: list[str] = []
        evidence.extend(signals_by_target.get(a, []))
        evidence.extend(signals_by_target.get(b, []))
        evidence = evidence[:_MAX_EVIDENCE_SIGNALS_PER_CANDIDATE]
        candidates.append(
            MergeSuggestionCandidate(
                project_name=project_name,
                target_a_id=a,
                target_a_kind="memory_entry",
                target_b_id=b,
                target_b_kind="memory_entry",
                similarity_score=sim,
                evidence_signal_ids=evidence,
                metabolism_run_id=_PENDING_RUN_ID_SENTINEL,
            )
        )
    return candidates


async def _load_pool_embeddings(
    backend: LocalMemoryBackend,
    store: LocalStructuredStore,
    pool_ids: list[str],
) -> dict[str, list[float]]:
    """Resolve embeddings for the merge pool, model-consistently.

    Reads from ``vec_embeddings`` filtered to the active ``model_id`` and
    falls back to in-memory encoding for misses or mismatches. Returns
    a map from entry id to a unit-normalized vector (so dot product
    equals cosine similarity downstream).

    All vectors in the returned map share one ``model_id`` by construction.
    The function never writes to ``vec_embeddings`` — vector backfills are
    out of scope for the metabolism pass per design.md.
    """
    if not pool_ids:
        return {}

    # Local imports keep the module cheap to import for callers that
    # don't trigger a metabolism pass (e.g. ``commands.replay_window``
    # importers). They mirror the lazy-load pattern in ``HybridSearchLayer``.
    import numpy as np

    from harness_mem.commands.support import get_embedding_model_id
    from harness_mem.embedding import get_model_loader

    model_id = get_embedding_model_id()
    loader = get_model_loader(model_id)
    expected_dim = loader.dimensions

    persisted: dict[str, np.ndarray] = {}
    try:
        with store.index.locked_connection() as conn:
            placeholders = ",".join("?" * len(pool_ids))
            rows = conn.execute(
                f"SELECT entry_id, embedding FROM vec_embeddings "
                f"WHERE entry_id IN ({placeholders}) AND model_id = ?",
                (*pool_ids, model_id),
            ).fetchall()
        for entry_id, blob in rows:
            arr = np.frombuffer(blob, dtype=np.float32)
            if arr.size != expected_dim:
                # Dimension mismatch — treat as miss; the consistency check
                # already filtered on model_id so this is rare.
                continue
            persisted[entry_id] = _normalize(arr)
    except Exception:
        # Missing table, locked db, or any read-side failure: degrade to
        # full in-memory encode. The pass is best-effort, never fatal.
        persisted = {}

    embeddings: dict[str, list[float]] = {
        entry_id: vec.tolist() for entry_id, vec in persisted.items()
    }

    missing = [entry_id for entry_id in pool_ids if entry_id not in embeddings]
    for entry_id in missing:
        entry = await store.get_memory_entry(entry_id)
        if entry is None or not entry.content:
            continue
        try:
            raw = loader.encode(entry.content)
        except Exception:
            # Encoding failure on one entry shouldn't kill the whole pass.
            continue
        vec = np.asarray(raw, dtype=np.float32).ravel()
        if vec.size != expected_dim or not np.any(vec):
            continue
        embeddings[entry_id] = _normalize(vec).tolist()

    return embeddings


def _normalize(vec: np.ndarray) -> np.ndarray:
    """L2-normalize a 1-D vector so cosine similarity reduces to dot product.

    Returning the input untouched on a zero vector is the conservative
    choice; downstream cosine then evaluates to 0 against any other vector.
    """
    import numpy as np

    norm = float(np.linalg.norm(vec))
    if norm == 0.0:
        return vec
    return vec / norm


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity for unit-normalized vectors (== dot product).

    Vectors are normalized in :func:`_load_pool_embeddings`, so this is a
    plain dot product. Kept tolerant: an empty or mismatched pair scores 0.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def _ensure_utc(value: datetime | None) -> datetime | None:
    """Coerce a datetime to a tz-aware UTC value, preserving ``None``.

    Mirrors :func:`replay_window._normalize_dt` minus the iso-string
    branch — by the time values reach this proposer they're already
    ``datetime`` instances pulled from Pydantic models, so we only need
    the tz-naive guard. Every datetime that flows into a subtract or
    comparison in :func:`_propose_stale` passes through this helper.
    """
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def _propose_stale(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    silence_days: int,
    max_suggestions: int,
    notes: list[str],
) -> list[StaleTruthSuggestionCandidate]:
    """Project-scoped stale proposal (task 2.3).

    Scans current truth (``valid_to is null``) for ``memory_entry`` and
    ``confirmed_rule``. ``last_surfaced_at`` is the newer of the v2.2
    field (``last_accessed_at`` / ``last_surfaced_at``) and the most
    recent ``RetrievalSignal`` of type ``wake_surfaced`` /
    ``search_hit``. Filter ``days_since_last_surface >= silence_days``,
    sort by ``days_since`` descending, cap at ``max_suggestions``.

    NOT bounded by the replay window — silent truth is by definition
    missing from the window. Two audit signals land in ``notes``:

    * ``stale_entry_scan_capped: <STALE_SCAN_ENTRY_LIMIT>`` when the
      entry scan saturated. The result pool may be incomplete.
    * ``stale_scan_truncated: <selected>/<pool>`` when the candidate
      result set was capped at ``max_suggestions``.

    ``relation_fact`` is deferred (RelationFact has no v2.2 surface
    field; revisit once v2.3.0 signals accumulate).
    """
    if max_suggestions <= 0 or silence_days < 0:
        return []

    store = cast(LocalStructuredStore, backend.structured_store)
    now = datetime.now(timezone.utc)

    # 1. Pull current truth. The structured store has no time filter on
    # this path; we read up to STALE_SCAN_ENTRY_LIMIT and emit an audit
    # note when the cap fires so callers can correlate truncation with
    # output size.
    entries = await store.list_memory_entries(
        project_name,
        limit=STALE_SCAN_ENTRY_LIMIT,
        status="accepted",
        include_history=False,
    )
    if len(entries) == STALE_SCAN_ENTRY_LIMIT:
        notes.append(f"stale_entry_scan_capped: {STALE_SCAN_ENTRY_LIMIT}")

    rules = await store.list_confirmed_rules(
        project_name,
        include_history=False,
    )

    # 2. Build the unified target list. Each row is
    # ``(target_id, target_kind, created_at, v2_field_surface_at)`` so
    # downstream computation has one shape. ``target_kind`` rides the
    # ``_StaleKind`` Literal so the value flows through to the
    # candidate constructor without a cast.
    targets: list[tuple[str, _StaleKind, datetime | None, datetime | None]] = []
    for entry in entries:
        targets.append(
            (
                entry.id,
                "memory_entry",
                _ensure_utc(entry.created_at),
                _ensure_utc(entry.last_accessed_at),
            )
        )
    for rule in rules:
        targets.append(
            (
                rule.id,
                "confirmed_rule",
                _ensure_utc(rule.confirmed_at),
                _ensure_utc(rule.last_surfaced_at),
            )
        )
    if not targets:
        return []

    # 3. Aggregate signal recorded_at per target_id across both surface
    # signal types. Two queries (wake_surfaced + search_hit) and a
    # single ``max`` per target keeps the algorithm O(signals + targets)
    # without per-target SQL.
    target_ids = {tid for tid, _, _, _ in targets}
    wake_signals = await store.query_retrieval_signals(
        project_name,
        signal_type="wake_surfaced",
        since=None,
        limit=10000,
    )
    search_signals = await store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=None,
        limit=10000,
    )
    signal_max_at: dict[str, datetime] = {}
    for signal in (*wake_signals, *search_signals):
        if signal.target_id not in target_ids:
            continue
        recorded = _ensure_utc(signal.recorded_at)
        if recorded is None:
            continue
        current = signal_max_at.get(signal.target_id)
        if current is None or recorded > current:
            signal_max_at[signal.target_id] = recorded

    # 4. For each target compute newer_of(v2_field, signal) → days_since.
    # When neither source has a value, fall back to created_at — that
    # gives us "how long has this truth been around without ever being
    # touched". Targets with no timestamps at all are skipped defensively
    # (should not happen for accepted truth).
    results: list[tuple[int, str, _StaleKind, datetime | None]] = []
    for target_id, target_kind, created_at, v2_field in targets:
        signal_at = signal_max_at.get(target_id)
        last_surfaced_at: datetime | None
        if v2_field is not None and signal_at is not None:
            last_surfaced_at = max(v2_field, signal_at)
        elif v2_field is not None:
            last_surfaced_at = v2_field
        else:
            last_surfaced_at = signal_at  # may still be None

        if last_surfaced_at is not None:
            delta = now - last_surfaced_at
        elif created_at is not None:
            delta = now - created_at
        else:
            continue
        days_since = max(0, delta.days)
        if days_since >= silence_days:
            results.append((days_since, target_id, target_kind, last_surfaced_at))

    # 5. Sort + cap. The truncation note lands only when a cap actually
    # fired so quiet runs stay quiet.
    results.sort(key=lambda triple: triple[0], reverse=True)
    pool_size = len(results)
    if pool_size > max_suggestions:
        notes.append(f"stale_scan_truncated: {max_suggestions}/{pool_size}")
        results = results[:max_suggestions]

    # 6. Build candidates. ``evidence_signal_ids`` stays empty — silence
    # is the trigger, not a positive signal. ``metabolism_run_id`` rides
    # the sentinel; phase 5.2 overwrites it before persistence.
    candidates: list[StaleTruthSuggestionCandidate] = []
    for days_since, target_id, target_kind, last_surfaced_at in results:
        candidates.append(
            StaleTruthSuggestionCandidate(
                project_name=project_name,
                target_id=target_id,
                target_kind=target_kind,
                last_surfaced_at=last_surfaced_at,
                days_since_last_surface=days_since,
                evidence_signal_ids=[],
                metabolism_run_id=_PENDING_RUN_ID_SENTINEL,
            )
        )
    return candidates


async def _propose_supersedes(
    backend: LocalMemoryBackend,
    window: ReplayWindow,
    *,
    notes: list[str],
) -> list[SupersedeCandidate]:
    """Propose candidate-only supersedes from recent historical truths.

    v2.6.2 activates the previously deferred supersede leg with a narrow,
    evidence-backed contract:

    - Only historical truths from ``window.historical_truths`` are considered
      as supersede targets.
    - A target must find a current truth of the same kind in the same project.
    - Similarity must clear a high threshold so this leg stays distinct from
      ordinary merge suggestions.
    - The proposer remains read-only and returns only ``SupersedeCandidate``.
    """
    historical_ids = window.dimensions.get("historical_truths")
    if historical_ids is None or not historical_ids.selected_ids:
        return []

    store = cast(LocalStructuredStore, backend.structured_store)
    candidates: list[tuple[float, SupersedeCandidate]] = []
    seen_pairs: set[tuple[str, str]] = set()

    for historical_id in historical_ids.selected_ids:
        historical = await _load_truth_for_supersede(store, historical_id)
        if historical is None:
            continue
        project_name = str(historical["project_name"])
        truth_kind = str(historical["truth_kind"])
        comparison_text = str(historical["comparison_text"])
        current_truths = await _current_truths_for_kind(
            store,
            project_name=project_name,
            truth_kind=truth_kind,
        )
        if not current_truths:
            continue

        best_score = 0.0
        best_replacement: dict[str, object] | None = None
        for current in current_truths:
            if current["id"] == historical["id"]:
                continue
            score = _content_similarity(
                comparison_text,
                str(current["comparison_text"]),
            )
            if score > best_score:
                best_score = score
                best_replacement = current

        if best_replacement is None or best_score < 0.78:
            continue
        pair = (str(historical["id"]), str(best_replacement["id"]))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)

        replacement_hint = _replacement_hint(
            comparison_text,
            str(best_replacement["comparison_text"]),
        )
        candidates.append(
            (
                best_score,
                SupersedeCandidate(
                    project_name=str(historical["project_name"]),
                    target_type=truth_kind,
                    target_id=str(historical["id"]),
                    replacement_type=str(best_replacement["truth_kind"]),
                    replacement_id=str(best_replacement["id"]),
                    reason=(
                        "Recent historical truth has a highly similar current replacement; "
                        "supersede review can relink the lineage explicitly."
                    ),
                    evidence=(
                        f"similarity={best_score:.3f}; historical='{replacement_hint[0]}'; "
                        f"current='{replacement_hint[1]}'"
                    ),
                    source=f"metabolism-run:{historical['id']}",
                    confidence=min(0.99, max(0.7, best_score)),
                ),
            )
        )

    candidates.sort(key=lambda item: item[0], reverse=True)
    return [candidate for _, candidate in candidates]


async def _load_truth_for_supersede(
    store: LocalStructuredStore,
    truth_id: str,
) -> dict[str, object] | None:
    entry = await store.get_memory_entry(truth_id)
    if entry is not None and entry.valid_to is not None:
        return {
            "id": entry.id,
            "project_name": entry.project_name,
            "truth_kind": "memory_entry",
            "comparison_text": entry.content,
        }
    rule = await store.get_confirmed_rule(truth_id)
    if rule is not None and rule.valid_to is not None:
        return {
            "id": rule.id,
            "project_name": rule.project_name,
            "truth_kind": "confirmed_rule",
            "comparison_text": f"{rule.trigger}\n{rule.pattern}",
        }
    fact = await store.get_relation_fact(truth_id)
    if fact is not None and fact.valid_to is not None:
        return {
            "id": fact.id,
            "project_name": fact.project_name,
            "truth_kind": "relation_fact",
            "comparison_text": (
                f"{fact.source_entity} {fact.relation_type} {fact.target_entity}\n{fact.evidence}"
            ),
        }
    return None


async def _current_truths_for_kind(
    store: LocalStructuredStore,
    *,
    project_name: str,
    truth_kind: str,
) -> list[dict[str, object]]:
    if truth_kind == "memory_entry":
        entries = await store.list_memory_entries(
            project_name,
            limit=100000,
            status="accepted",
            include_history=False,
        )
        return [
            {
                "id": entry.id,
                "truth_kind": "memory_entry",
                "comparison_text": entry.content,
            }
            for entry in entries
        ]
    if truth_kind == "confirmed_rule":
        rules = await store.list_confirmed_rules(project_name, include_history=False)
        return [
            {
                "id": rule.id,
                "truth_kind": "confirmed_rule",
                "comparison_text": f"{rule.trigger}\n{rule.pattern}",
            }
            for rule in rules
        ]
    if truth_kind == "relation_fact":
        facts = await store.list_relation_facts(
            project_name,
            limit=100000,
            status="accepted",
            include_history=False,
        )
        return [
            {
                "id": fact.id,
                "truth_kind": "relation_fact",
                "comparison_text": (
                    f"{fact.source_entity} {fact.relation_type} {fact.target_entity}\n{fact.evidence}"
                ),
            }
            for fact in facts
        ]
    return []


def _content_similarity(left: str, right: str) -> float:
    left_tokens = set(_tokenize_similarity_text(left))
    right_tokens = set(_tokenize_similarity_text(right))
    if not left_tokens or not right_tokens:
        return 0.0
    overlap = len(left_tokens & right_tokens)
    overlap_floor = overlap / min(len(left_tokens), len(right_tokens))
    sequence_ratio = SequenceMatcher(None, left.lower(), right.lower()).ratio()
    return max(overlap_floor, sequence_ratio)


def _tokenize_similarity_text(text: str) -> list[str]:
    return [
        token.lower()
        for token in text.replace("/", " ").replace("-", " ").split()
        if token.strip()
    ]


def _replacement_hint(left: str, right: str) -> tuple[str, str]:
    return (left[:120], right[:120])
