"""Tests for v2.3.1 weak-link signal application call sites (task 4.5).

Covers all four production sites exercised by the
``ProjectProfile.weak_link_signals`` flag:

- 4.1 ``pull_recent_signals`` helper aggregating two signal types per
  target into a single :class:`TargetSignalSummary`.
- 4.2 ``cmd_wake_up`` rendering: flag off ⇒ v2.2-identical output and
  no call into ``pull_recent_signals``; flag on ⇒ rules split into
  ``### Recent active`` / ``### Stable / quiet`` subheads, total ≤ 5.
- 4.3 ``read_api.search_memory`` ranker: flag off ⇒ no ``_repeat_boost``
  attribute on entries; flag on + 2 hits in last 7d ⇒
  ``_repeat_boost == REPEAT_BOOST_BASE`` on the qualifying entry.
- 4.4 ``_doctor_weak_link_block`` output: disabled / enabled / no-project
  shapes per design.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import cast

import pytest

from harness_mem.commands import wake as wake_module
from harness_mem.commands.doctor import _doctor_weak_link_block
from harness_mem.commands.signal_influence import (
    TargetSignalSummary,
    pull_recent_signals,
)
from harness_mem.commands.wake import cmd_wake_up
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    RetrievalSignal,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.read_api import REPEAT_BOOST_BASE, search_memory
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_structured_store import LocalStructuredStore


# ---------------------------------------------------------------------------
# Seeding helpers — kept tiny on purpose; each test owns its own fixture data
# ---------------------------------------------------------------------------


async def _save_signal(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    signal_type: str,
    target_kind: str,
    target_id: str,
    recorded_at: datetime,
) -> None:
    """Persist a :class:`RetrievalSignal` via the concrete store.

    ``save_retrieval_signal`` lives only on :class:`LocalStructuredStore`
    (the Protocol exposes the read path), so this helper does the
    cast in one place.
    """
    structured = cast(LocalStructuredStore, backend.structured_store)
    await structured.save_retrieval_signal(
        RetrievalSignal(
            project_name=project_name,
            signal_type=signal_type,
            target_kind=target_kind,
            target_id=target_id,
            recorded_at=recorded_at,
        )
    )


# ---------------------------------------------------------------------------
# 4.1 pull_recent_signals — per-target aggregation
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_pull_recent_signals_aggregates_two_types(
    backend: LocalMemoryBackend,
) -> None:
    """``pull_recent_signals`` merges wake_surfaced + search_hit per target.

    target_a: 2 wake_surfaced + 3 search_hit.
    target_b: 0 wake + 1 search_hit.
    target_c: nothing.
    Empty target_ids ⇒ ``{}`` short-circuit (no IO required).
    """
    project_name = "proj-pull-recent"
    now = datetime.now(timezone.utc)

    # target_a: 2 wake + 3 search hits, spread across the last day so we
    # can pin the most-recent timestamp.
    a_recorded_at = [now - timedelta(hours=h) for h in (1, 2, 3, 4, 5)]
    await _save_signal(
        backend,
        project_name=project_name,
        signal_type="wake_surfaced",
        target_kind="rule",
        target_id="target_a",
        recorded_at=a_recorded_at[0],  # newest
    )
    await _save_signal(
        backend,
        project_name=project_name,
        signal_type="wake_surfaced",
        target_kind="rule",
        target_id="target_a",
        recorded_at=a_recorded_at[3],
    )
    for ts in a_recorded_at[1:4]:  # 3 search hits
        await _save_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id="target_a",
            recorded_at=ts,
        )

    # target_b: 1 search hit, no wake.
    b_recorded_at = now - timedelta(hours=6)
    await _save_signal(
        backend,
        project_name=project_name,
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="target_b",
        recorded_at=b_recorded_at,
    )

    # target_c is intentionally not seeded.

    summaries = await pull_recent_signals(
        backend,
        project_name=project_name,
        target_ids=["target_a", "target_b", "target_c"],
        since=now - timedelta(days=1),
    )

    assert set(summaries.keys()) == {"target_a", "target_b", "target_c"}

    a = summaries["target_a"]
    assert a.wake_surfaced_count == 2
    assert a.search_hit_count == 3
    assert a.last_signal_at is not None
    # Most recent across both types ⇒ a_recorded_at[0] (1h ago).
    assert a.last_signal_at == a_recorded_at[0]

    b = summaries["target_b"]
    assert b.wake_surfaced_count == 0
    assert b.search_hit_count == 1
    assert b.last_signal_at == b_recorded_at

    assert summaries["target_c"] == TargetSignalSummary(0, 0, None)

    # Empty target_ids ⇒ empty dict, no IO. Documented short-circuit.
    assert (
        await pull_recent_signals(
            backend,
            project_name=project_name,
            target_ids=[],
            since=now - timedelta(days=1),
        )
        == {}
    )


# ---------------------------------------------------------------------------
# 4.2 wake — flag off (v2.2-identical) vs flag on (split groups)
# ---------------------------------------------------------------------------


def _seed_rule(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    pattern: str,
    trigger: str,
) -> ConfirmedRule:
    """Synchronous helper used inside ``@pytest.mark.anyio`` tests.

    Tests need to seed rules from inside an async body, so callers
    ``await`` the structured-store save directly. This factory just
    builds a plausibly-formed :class:`ConfirmedRule` so the test
    bodies stay short.
    """
    return ConfirmedRule(
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        source_candidate_id="seed-candidate-id",
    )


@pytest.mark.anyio
async def test_wake_off_path_does_not_call_pull_recent_signals(
    backend: LocalMemoryBackend,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Flag off ⇒ wake takes the v2.2 path (no signals call, no subheads).

    Monkeypatch ``harness_mem.commands.wake.pull_recent_signals`` to raise.
    If the v2.2 path is intact, the patched function is never called and
    wake completes with no error. This is stronger than asserting on the
    output alone — it also pins the "no extra IO when off" property.
    """
    project_name = "proj-wake-off"
    rule = _seed_rule(
        backend,
        project_name=project_name,
        pattern="Always pin Tauri invoke for IPC payloads larger than 1MB.",
        trigger="Before changing Windows IPC code",
    )
    await backend.structured_store.save_confirmed_rule(rule)

    # Profile saved with default-off flag. Saving an explicit profile
    # also sidesteps the "no profile" path; we want to assert the
    # "profile.weak_link_signals == False" branch specifically.
    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(project_name=project_name, weak_link_signals=False)
    )

    def _explode(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "pull_recent_signals must NOT be called when "
            "weak_link_signals is False"
        )

    # Patch at the import site inside the wake module. The wake
    # renderer imports ``pull_recent_signals`` from
    # ``harness_mem.commands.signal_influence`` into its own
    # namespace, so this is the binding that matters.
    monkeypatch.setattr(wake_module, "pull_recent_signals", _explode)

    # ``no_auto_ingest`` keeps the test off the real ~/.claude tree.
    assert await cmd_wake_up(project_name, no_auto_ingest=True) == 0
    captured = capsys.readouterr().out

    # The v2.2 contract: plain "# Confirmed Rules" block, no subheads.
    assert "# Confirmed Rules" in captured
    assert "### Recent active" not in captured
    assert "### Stable / quiet" not in captured
    # The rule itself still appears.
    assert "Tauri invoke" in captured


@pytest.mark.anyio
async def test_wake_on_path_splits_into_two_groups(
    backend: LocalMemoryBackend,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Flag on ⇒ rules render under both subheads, total ≤ 5.

    Three rules; one has a recent ``wake_surfaced`` signal, one has a
    recent ``search_hit`` signal, one is signal-less. The first two
    land in ``Recent active`` and the third in ``Stable / quiet``.
    """
    project_name = "proj-wake-on"
    now = datetime.now(timezone.utc)

    rule_a = _seed_rule(
        backend,
        project_name=project_name,
        pattern="Pattern A: parameterize SQL.",
        trigger="Trigger A: any data-access path",
    )
    rule_b = _seed_rule(
        backend,
        project_name=project_name,
        pattern="Pattern B: pin sentence-transformers version.",
        trigger="Trigger B: dependency upgrades",
    )
    rule_c = _seed_rule(
        backend,
        project_name=project_name,
        pattern="Pattern C: keep MCP stdout pristine.",
        trigger="Trigger C: stdio MCP server work",
    )
    for rule in (rule_a, rule_b, rule_c):
        await backend.structured_store.save_confirmed_rule(rule)

    # Recent surface signals: rule_a got a wake_surfaced, rule_b got a
    # search_hit; rule_c stays silent.
    await _save_signal(
        backend,
        project_name=project_name,
        signal_type="wake_surfaced",
        target_kind="rule",
        target_id=rule_a.id,
        recorded_at=now - timedelta(days=1),
    )
    await _save_signal(
        backend,
        project_name=project_name,
        signal_type="search_hit",
        target_kind="rule",
        target_id=rule_b.id,
        recorded_at=now - timedelta(days=2),
    )

    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(project_name=project_name, weak_link_signals=True)
    )

    assert await cmd_wake_up(project_name, no_auto_ingest=True) == 0
    out = capsys.readouterr().out

    # Both subheads present.
    assert "### Recent active" in out
    assert "### Stable / quiet" in out

    # Rule patterns appear; we don't pin which group each lands in via
    # text-position arithmetic (brittle), but we do pin overall presence.
    assert "Pattern A" in out
    assert "Pattern B" in out
    assert "Pattern C" in out

    # rule_a / rule_b sit above the "### Stable / quiet" subhead;
    # rule_c sits below it. This double-checks the grouping without
    # depending on render order across the whole stdout.
    stable_index = out.index("### Stable / quiet")
    assert out.index("Pattern A") < stable_index
    assert out.index("Pattern B") < stable_index
    assert out.index("Pattern C") > stable_index

    # Total budget stays at 5 — only 3 rules are seeded so all three
    # render. Counting markdown bullets is enough.
    rendered_rules = sum(1 for line in out.splitlines() if line.startswith("- **"))
    assert rendered_rules == 3
    assert rendered_rules <= 5


# ---------------------------------------------------------------------------
# 4.3 search ranker — flag off vs flag on
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_search_boost_off_no_score_change(
    backend: LocalMemoryBackend,
) -> None:
    """No profile / flag off ⇒ ``_repeat_boost`` not applied.

    Even when an entry has plenty of qualifying ``search_hit`` history,
    the boost path must stay dormant unless the project's profile
    flips ``weak_link_signals=True``.
    """
    project_name = "proj-search-off"
    now = datetime.now(timezone.utc)

    e1 = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="SQLite FTS5 powers structured search across memory entries.",
        confidence=0.9,
        source="manual",
    )
    e2 = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="SQLite FTS5 also indexes verbatim observations for raw lookup.",
        confidence=0.9,
        source="manual",
    )
    await backend.structured_store.save_memory_entry(e1)
    await backend.structured_store.save_memory_entry(e2)

    # 4 search_hit signals on e2 — would qualify if the flag were on.
    for offset in range(4):
        await _save_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=e2.id,
            recorded_at=now - timedelta(hours=offset + 1),
        )

    # No profile saved on purpose ⇒ ``LocalProjectProfileStore.get``
    # returns None, the repeat-boost helper short-circuits.
    entries, _observations = await search_memory(
        backend,
        project_name=project_name,
        query="SQLite FTS5",
        mode="fts",
    )

    assert {entry.id for entry in entries} >= {e1.id, e2.id}
    for entry in entries:
        # ``_repeat_boost`` is set only when the boost path runs;
        # absent or 0.0 are both acceptable "off" states.
        assert getattr(entry, "_repeat_boost", 0.0) in (None, 0.0)


@pytest.mark.anyio
async def test_search_boost_on_lifts_repeated_target(
    backend: LocalMemoryBackend,
) -> None:
    """Flag on + ≥2 hits in last 7d ⇒ ``_repeat_boost == REPEAT_BOOST_BASE``.

    The cross-entry "did the boost flip ranking?" assertion is hard to
    engineer without pinning FTS internals, so we follow the
    weaker-but-honest contract from the task spec: assert the boost
    attribute is set on the qualifying entry and not on the other.
    """
    project_name = "proj-search-on"
    now = datetime.now(timezone.utc)

    e1 = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="Hybrid search uses sentence-transformers for vector recall.",
        confidence=0.9,
        source="manual",
    )
    e2 = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="Hybrid search blends FTS5 BM25 with vector cosine similarity.",
        confidence=0.9,
        source="manual",
    )
    await backend.structured_store.save_memory_entry(e1)
    await backend.structured_store.save_memory_entry(e2)

    # 2 search_hits on e2 within the 7-day window ⇒ qualifies.
    for offset in range(2):
        await _save_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=e2.id,
            recorded_at=now - timedelta(hours=offset + 1),
        )

    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(project_name=project_name, weak_link_signals=True)
    )

    entries, _observations = await search_memory(
        backend,
        project_name=project_name,
        query="Hybrid search",
        mode="fts",
    )

    by_id = {entry.id: entry for entry in entries}
    assert e1.id in by_id and e2.id in by_id

    # e2 carries the constant boost; e1 carries either no attribute or 0.
    assert getattr(by_id[e2.id], "_repeat_boost", 0.0) == REPEAT_BOOST_BASE
    assert getattr(by_id[e1.id], "_repeat_boost", 0.0) in (None, 0.0)


# ---------------------------------------------------------------------------
# 4.4 doctor weak-link block — disabled / enabled / no project
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_doctor_weak_link_block_disabled(
    backend: LocalMemoryBackend,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Profile present with the flag off ⇒ single disabled-line output."""
    project_name = "proj-doctor-disabled"

    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(project_name=project_name, weak_link_signals=False)
    )

    await _doctor_weak_link_block(backend, project_name)
    out = capfd.readouterr().out

    assert "disabled" in out
    assert "set weak_link_signals=true" in out
    # Single-line variant — explicitly NOT the multi-line enabled block.
    assert "Weak-link signal influence (v2.3.1):" not in out


@pytest.mark.anyio
async def test_doctor_weak_link_block_enabled(
    backend: LocalMemoryBackend,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """Flag on with one stable rule + one boosted entry ⇒ 1/1 + 1 distinct."""
    project_name = "proj-doctor-enabled"
    now = datetime.now(timezone.utc)

    # 1 confirmed rule, no signals ⇒ stable_count == 1, total == 1.
    rule = _seed_rule(
        backend,
        project_name=project_name,
        pattern="Always emit structured JSON logs.",
        trigger="In every service",
    )
    await backend.structured_store.save_confirmed_rule(rule)

    # 1 memory entry with 2 search_hit signals in the last 7d ⇒
    # boosted_count == 1.
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content="Rate limiting uses leaky-bucket on the public API.",
        confidence=0.9,
        source="manual",
    )
    await backend.structured_store.save_memory_entry(entry)
    for offset in range(2):
        await _save_signal(
            backend,
            project_name=project_name,
            signal_type="search_hit",
            target_kind="memory_entry",
            target_id=entry.id,
            recorded_at=now - timedelta(hours=offset + 1),
        )

    profile_store = LocalProjectProfileStore(backend.data_dir)
    await profile_store.save(
        ProjectProfile(project_name=project_name, weak_link_signals=True)
    )

    await _doctor_weak_link_block(backend, project_name)
    out = capfd.readouterr().out

    assert "Weak-link signal influence (v2.3.1):" in out
    assert "1 / 1" in out
    assert "1 distinct targets" in out
    assert "deferred to v2.3.2" in out


@pytest.mark.anyio
async def test_doctor_weak_link_block_no_project(
    backend: LocalMemoryBackend,
    capfd: pytest.CaptureFixture[str],
) -> None:
    """No active project ⇒ ``skipped`` line, no profile lookup attempted."""
    await _doctor_weak_link_block(backend, None)
    out = capfd.readouterr().out

    assert "skipped (no active project)" in out
