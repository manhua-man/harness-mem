"""Cross-cutting non-interference test for the v2.5.0 Plan_Assembler.

**Property 10: wake / search_memory Unchanged** (design.md) — for identical
inputs, the rendered ``wake`` output AND the default
``read_api.search_memory(...)`` result (entries, observations, and the
``search_hit`` signals that call emits) are identical whether or not
``assemble_context_plan`` was invoked first. Producing a plan is side-effect
free (Req 9.4), so it must not change, consume, suppress, or add to anything
``wake`` / ``search_memory`` observe (Req 11.1, 11.2).

Structure — **two-backend A/B** (recommended for wake / entries / observations
equality):

* **World A (control)**: seed → ``wake`` → default ``search_memory`` →
  read ``search_hit`` signals.
* **World B (treatment)**: seed the *same* fixed-id data → invoke
  ``assemble_context_plan`` FIRST → ``wake`` → default ``search_memory`` →
  read ``search_hit`` signals.

Both worlds are seeded with **fixed ids and fixed timestamps** so the two are
byte-identical at seed time; the only difference between them is whether the
assembler ran. Any side effect of assembly would surface as a divergence.

``wake`` itself mutates state (it touches surfaced records and writes
``wake_surfaced`` signals), which is exactly why the single-backend
before/after shape is unfit for wake-output equality — wake's second render
would differ from its first. The A/B shape sidesteps that: each world renders
wake exactly once, so the comparison isolates the assembler's effect.

Wake output is compared as the full rendered string with no normalization:
the seed is fully pinned (fixed timestamps, ``usage_count=0`` rules → a stable
``(never surfaced before)`` badge) and wake emits no inherently volatile
substring (no "generated at <now>"). Entries / observations are compared by
``(id, content)`` rather than full serialization because ``wake`` stamps a
wall-clock ``last_accessed_at`` on surfaced entries — that timestamp differs
between the two scenario runs and is not what this property is about.

A second, complementary test asserts directly that ``assemble_context_plan``
adds **zero** rows to the signal table (Req 9.4 / Property 6 corollary).

All backends are created against ``tmp_path``-isolated sub-dirs (never the real
``~/.harness-mem/``, rule P1 数据路径隔离) and closed in a ``finally`` block
(rule P1 异步资源清理). ``wake`` reads its own data dir from
``wake.DEFAULT_DATA_DIR``, so each world points it at the matching sub-dir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem.commands import wake as wake_module
from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas import Observation
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.read_api import search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


# Query term shared by ``assemble_context_plan`` (L3) and the default
# ``search_memory`` call. Matches the seeded observation + entry below.
_QUERY = "SQLite FTS5"


def _seed_world(backend: LocalMemoryBackend, *, project_name: str, now: datetime) -> None:
    """Seed one world with fixed ids + fixed timestamps across every surface.

    Both A/B worlds call this with the *same* ``project_name`` and ``now`` so
    the two stores are byte-identical at seed time. Fixed ids make the
    entries / observations / signals directly comparable across the two
    separate data dirs (default uuid4 ids would differ per world).

    The world deliberately spans the surfaces ``wake`` renders (profile,
    handoff, confirmed rule, accepted entries) and the surfaces
    ``assemble_context_plan`` reads (profile→L0, rule/entries→L1,
    handoff/signal→L2, search→L3) so the assembler does real work in every
    layer before wake/search run.
    """
    # L0 / wake profile.
    profile = ProjectProfile(
        id="prof-1",
        project_name=project_name,
        description="Local-first AI memory runtime",
        stacks=["python", "sqlite"],
        created_at=now - timedelta(days=10),
        last_updated=now - timedelta(days=10),
    )
    run(LocalProjectProfileStore(backend.data_dir).save(profile))

    # L1 / wake confirmed rule (usage_count=0 → stable "never surfaced" badge).
    rule = ConfirmedRule(
        id="rule-1",
        project_name=project_name,
        pattern="tests must use the tmp_path fixture",
        trigger="when writing tests",
        source_candidate_id="seed-candidate",
        confirmed_at=now - timedelta(hours=3),
    )
    run(backend.structured_store.save_confirmed_rule(rule))

    # L1 / L3 / wake — an accepted current-truth entry that also matches _QUERY.
    entry_search = MemoryEntry(
        id="entry-search",
        project_name=project_name,
        category="architecture",
        content="SQLite FTS5 is used for full-text search indexing in this project.",
        confidence=0.90,
        status="accepted",
        source="manual",
        created_at=now - timedelta(minutes=30),
        updated_at=now - timedelta(minutes=30),
    )
    run(backend.structured_store.save_memory_entry(entry_search))

    # L1 / L2 / wake — a second accepted current-truth entry (no query match).
    entry_other = MemoryEntry(
        id="entry-other",
        project_name=project_name,
        category="architecture",
        content="MCP stdout must stay clean to protect the JSON-RPC stream.",
        confidence=0.80,
        status="accepted",
        source="manual",
        created_at=now - timedelta(minutes=90),
        updated_at=now - timedelta(minutes=90),
    )
    run(backend.structured_store.save_memory_entry(entry_other))

    # L3 / search observation matching _QUERY.
    observation = Observation(
        id="obs-1",
        session_id="sess-noninterference",
        client="claude-code",
        raw_content=(
            "We use SQLite FTS5 with porter tokenizer for full-text search "
            "across structured memory entries."
        ),
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "claude-code"],
    )
    run(backend.verbatim_store.save(observation))

    # L2 / wake handoff.
    handoff = TaskHandoff(
        id="handoff-1",
        project_name=project_name,
        task_id="seed-task",
        summary="resume wiring the assembler",
        last_activity=now - timedelta(hours=1),
    )
    run(backend.structured_store.save_task_handoff(handoff))

    # L2 input — an in-window retrieval signal pointing at entry_other so the
    # assembler's recently-surfaced derivation has something to read.
    signal = RetrievalSignal(
        id="sig-1",
        project_name=project_name,
        signal_type="wake_surfaced",
        target_kind="memory_entry",
        target_id=entry_other.id,
        recorded_at=now - timedelta(days=1),
    )
    run(backend.structured_store.save_retrieval_signal(signal))


def _signal_fingerprint(signals: list[RetrievalSignal]) -> list[tuple[str, str, str, str]]:
    """Reduce signals to an order-independent, volatility-free fingerprint.

    Drops the inherently volatile ``id`` (uuid4) and ``recorded_at``
    (wall-clock) fields, keeping only what the property is about: which
    targets were signalled, of what kind, by what signal type, with what
    context. Sorted so the comparison is order-independent.
    """
    return sorted(
        (
            sig.signal_type,
            sig.target_kind,
            sig.target_id,
            json.dumps(sig.context, sort_keys=True),
        )
        for sig in signals
    )


def _run_world(
    *,
    data_dir: Path,
    project_name: str,
    now: datetime,
    invoke_assemble: bool,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict:
    """Drive one A/B scenario end-to-end against an isolated data dir.

    Sequence: seed → (optionally) ``assemble_context_plan`` → ``wake`` →
    default ``search_memory`` → read ``search_hit`` signals. When
    ``invoke_assemble`` is True the assembler runs *before* wake/search and we
    record how many signal rows it added (must be zero).
    """
    signals_added_by_assemble: int | None = None

    # Seed + (treatment) assemble. wake opens its own backend on this dir, so
    # close ours first to avoid holding the store open across the wake call
    # (mirrors the existing wake signal tests).
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        _seed_world(backend, project_name=project_name, now=now)
        if invoke_assemble:
            before = len(
                run(backend.structured_store.query_retrieval_signals(project_name))
            )
            run(
                assemble_context_plan(
                    backend, project_name=project_name, query=_QUERY
                )
            )
            after = len(
                run(backend.structured_store.query_retrieval_signals(project_name))
            )
            signals_added_by_assemble = after - before
    finally:
        run(backend.close())

    # Render wake against this world's data dir and capture the output string.
    monkeypatch.setattr(wake_module, "DEFAULT_DATA_DIR", data_dir)
    assert run(wake_module.cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    wake_output = capsys.readouterr().out

    # Default search_memory + the search_hit signals it emits.
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        entries, observations = run(
            search_memory(
                backend,
                project_name=project_name,
                query=_QUERY,
                memory_entry_limit=20,
                observation_limit=20,
            )
        )
        search_hit_signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="search_hit"
            )
        )
    finally:
        run(backend.close())

    return {
        "wake_output": wake_output,
        "entries": [(entry.id, entry.content) for entry in entries],
        "observations": [(obs.id, obs.raw_content) for obs in observations],
        "search_hit": _signal_fingerprint(search_hit_signals),
        "signals_added_by_assemble": signals_added_by_assemble,
    }


def test_wake_and_search_identical_with_and_without_assemble(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Property 10 — assembly leaves wake + default search_memory unchanged.

    World A never invokes the assembler; world B invokes it before wake/search
    over byte-identical seed data. The rendered wake output, the search_memory
    entries/observations, and the search_hit signals that call emits are all
    identical (Req 9.4, 11.1, 11.2).
    """
    project_name = "noninterference"
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    world_a = _run_world(
        data_dir=tmp_path / "world_a",
        project_name=project_name,
        now=now,
        invoke_assemble=False,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )
    world_b = _run_world(
        data_dir=tmp_path / "world_b",
        project_name=project_name,
        now=now,
        invoke_assemble=True,
        monkeypatch=monkeypatch,
        capsys=capsys,
    )

    # Rendered wake output is byte-for-byte identical (Req 11.1, 11.2).
    assert world_b["wake_output"] == world_a["wake_output"]
    # Sanity: wake actually produced content (the comparison isn't trivially
    # equal because both were empty).
    assert "# Project Profile" in world_a["wake_output"]

    # Default search_memory returns the same entries and observations (Req 9.4).
    assert world_b["entries"] == world_a["entries"]
    assert world_b["observations"] == world_a["observations"]
    # Sanity: the query actually matched the seeded entry + observation.
    assert ("entry-search", world_a["entries"][0][1]) in world_a["entries"]
    assert any(obs_id == "obs-1" for obs_id, _ in world_a["observations"])

    # The search_hit signals that the default call emits are equivalent — the
    # assembler neither consumed, suppressed, nor added to them (Req 9.4).
    assert world_b["search_hit"] == world_a["search_hit"]
    assert world_a["search_hit"], "default search_memory must emit search_hit signals"

    # Direct corollary: the assembler in world B added zero signal rows.
    assert world_b["signals_added_by_assemble"] == 0


def test_assemble_context_plan_emits_no_signals(
    tmp_path: Path,
) -> None:
    """Complementary assertion — assembly adds no rows to the signal table.

    A focused single-backend before/after count: ``assemble_context_plan``
    reads every surface (including the signal-writing ``search_memory`` via its
    ``record_signals=False`` opt-out) yet must leave the retrieval-signal table
    untouched (Req 9.4).
    """
    project_name = "noninterference-signals"
    now = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)

    backend = LocalMemoryBackend(tmp_path / "data_signals")
    run(backend.init())
    try:
        _seed_world(backend, project_name=project_name, now=now)

        before = run(backend.structured_store.query_retrieval_signals(project_name))
        run(
            assemble_context_plan(backend, project_name=project_name, query=_QUERY)
        )
        after = run(backend.structured_store.query_retrieval_signals(project_name))
    finally:
        run(backend.close())

    # The single seeded signal is still the only row; assembly added none.
    assert _signal_fingerprint(after) == _signal_fingerprint(before)
    assert len(after) == 1
