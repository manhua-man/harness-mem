"""Integration test — v2.5.1 wake render preserves existing side effects.

Task 9.1 (Req 7.1, 5.3): the plan-backed Wake_Renderer must keep wake's
*existing* per-record side effects and add no others. For a cold-start
``cmd_wake_up`` over a seeded project this means:

- exactly one ``wake_surfaced`` :class:`RetrievalSignal` per distinct surfaced
  confirmed-rule id (``target_kind="rule"``) and per distinct surfaced accepted
  current-truth memory-entry id (``target_kind="memory_entry"``);
- exactly one usage-counter touch per the same ids (``usage_count`` incremented
  by 1, ``last_surfaced_at`` / ``last_accessed_at`` set); and
- **no** signal or touch for task handoffs (L2) or the project profile (L0).

What surfaces (verified against ``context_assembly.assemble_context_plan`` +
``wake._apply_surface_side_effects``):
  * L0 carries the ``ProjectProfile`` (``identity:active_project``) — no side effect.
  * L1 carries confirmed rules (``essential:confirmed_rule``) and accepted
    current-truth entries (``essential:high_confidence_truth``) — each signaled
    + touched once.
  * L2 carries the recent handoff (``active:recent_handoff``) — no side effect —
    plus *recently-surfaced* accepted entries derived from prior
    ``wake_surfaced`` / ``search_hit`` signals; on a first cold-start wake no
    such signals exist yet, so that L2 source is empty and the accepted entries
    surface only once (in L1). De-dup per distinct record id is therefore exact
    here.

The default per-layer budgets are L0=3 / L1=7 / L2=7, so the small seeded set
(2 rules + 2 entries in L1, 1 handoff in L2) surfaces in full and the counts
are deterministic.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections import Counter
from pathlib import Path
from uuid import uuid4

import pytest

from harness_mem.commands.wake import cmd_wake_up
from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas import (
    ConfirmedRule,
    MemoryEntry,
    ProceduralCandidate,
    ProjectProfile,
    Skill,
    TaskHandoff,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


def _seed_confirmed_rule(
    backend: LocalMemoryBackend, project_name: str, *, pattern: str
) -> str:
    rule = ConfirmedRule(
        id=str(uuid4()),
        project_name=project_name,
        trigger="When changing IPC code",
        pattern=pattern,
        source_candidate_id="seed-candidate-id",
    )
    return run(backend.structured_store.save_confirmed_rule(rule))


def _seed_accepted_entry(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    content: str,
    confidence: float,
) -> str:
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content,
        confidence=confidence,
        source="obs-seed",
        status="accepted",
        tags=["architecture"],
    )
    return run(backend.structured_store.save_memory_entry(entry))


def test_wake_render_preserves_existing_side_effects(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_name = "v251-side-effects"

    # --- seed: profile (L0), 2 rules + 2 accepted entries (L1), 1 handoff (L2) ---
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        profile_store = LocalProjectProfileStore(data_dir)
        run(
            profile_store.save(
                ProjectProfile(
                    project_name=project_name,
                    description="local-first AI memory runtime",
                    stacks=["python", "sqlite"],
                )
            )
        )
        profile = run(profile_store.get(project_name))
        assert profile is not None
        profile_id = profile.id

        rule_ids = [
            _seed_confirmed_rule(
                backend,
                project_name,
                pattern="Prefer Tauri invoke over emit for IPC payloads over ~1MB.",
            ),
            _seed_confirmed_rule(
                backend,
                project_name,
                pattern="Redirect MCP server stdout to stderr to keep JSON-RPC clean.",
            ),
        ]

        entry_ids = [
            _seed_accepted_entry(
                backend,
                project_name,
                content="SQLite FTS5 with the porter tokenizer backs full-text search.",
                confidence=0.95,
            ),
            _seed_accepted_entry(
                backend,
                project_name,
                content="Structured memory is persisted as JSON blobs plus a sqlite index.",
                confidence=0.85,
            ),
        ]

        handoff = TaskHandoff(
            project_name=project_name,
            task_id="resume-task-1",
            summary="Wire cmd_wake_up to the plan-backed renderer.",
            status="in_progress",
        )
        run(backend.structured_store.save_task_handoff(handoff))
        handoff_id = handoff.id
    finally:
        run(backend.close())

    # --- act: cold-start wake (its own backend), auto-ingest off for determinism ---
    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    capsys.readouterr()  # drain rendered wake output

    # --- read back signals + touched records via a fresh backend ---
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        rule_signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="wake_surfaced", target_kind="rule"
            )
        )
        entry_signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="wake_surfaced", target_kind="memory_entry"
            )
        )
        all_wake_signals = run(
            backend.structured_store.query_retrieval_signals(
                project_name, signal_type="wake_surfaced"
            )
        )
        rules = {
            rid: run(backend.structured_store.get_confirmed_rule(rid))
            for rid in rule_ids
        }
        entries = {
            eid: run(backend.structured_store.get_memory_entry(eid))
            for eid in entry_ids
        }
    finally:
        run(backend.close())

    # Exactly one wake_surfaced signal per distinct confirmed-rule id.
    assert Counter(s.target_id for s in rule_signals) == Counter(rule_ids)
    assert all(s.context == {"source": "wake"} for s in rule_signals)

    # Exactly one wake_surfaced signal per distinct accepted-entry id.
    assert Counter(s.target_id for s in entry_signals) == Counter(entry_ids)
    assert all(s.context == {"source": "wake"} for s in entry_signals)

    # No signal for the handoff (L2) or the profile (L0); and nothing else
    # emitted a wake_surfaced signal — only the 2 rules + 2 entries did.
    surfaced_target_ids = {s.target_id for s in all_wake_signals}
    assert handoff_id not in surfaced_target_ids
    assert profile_id not in surfaced_target_ids
    assert len(all_wake_signals) == len(rule_ids) + len(entry_ids)

    # Exactly one usage-counter touch per surfaced rule id.
    for rule_id in rule_ids:
        rule = rules[rule_id]
        assert rule is not None
        assert rule.usage_count == 1
        assert rule.last_surfaced_at is not None

    # Exactly one usage-counter touch per surfaced accepted-entry id.
    for entry_id in entry_ids:
        entry = entries[entry_id]
        assert entry is not None
        assert entry.usage_count == 1
        assert entry.last_accessed_at is not None


# --------------------------------------------------------------------------- #
# Task 9.2 (Req 7.2, 7.3, 7.4) — no-new-writes / assembler-purity.
#
# Content-hash helpers mirror tests/test_context_assembly_readonly.py: a SQLite
# DB is hashed by its *logical row set* (each table ``SELECT *`` sorted in
# Python) rather than raw bytes, because WAL checkpointing and ``-wal`` /
# ``-shm`` housekeeping can change a SQLite file's bytes with no logical
# insert/update/delete (a naive byte hash would be flaky). Every other file
# under ``data_dir`` (JSON blobs, profiles, event log) is hashed by raw bytes;
# the transient ``-wal`` / ``-shm`` sidecars are skipped. Together this
# captures all persistent logical state and still catches any real write.
# --------------------------------------------------------------------------- #
def _sqlite_logical_rows(db_path: Path) -> str:
    """Serialize every table's full row set (sorted) from a SQLite DB.

    Opens its own short-lived read-only connection and, for each table in
    ``sqlite_master``, dumps ``SELECT *`` rows sorted by ``repr`` so ordering
    never affects the digest. Sorting in Python keeps this robust across
    regular tables, FTS5 virtual tables, and their shadow tables alike.
    """
    conn = sqlite3.connect(str(db_path))
    try:
        table_names = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            ).fetchall()
        ]
        parts: list[str] = []
        for table in table_names:
            try:
                rows = conn.execute(f'SELECT * FROM "{table}"').fetchall()
            except sqlite3.DatabaseError:
                # A virtual/shadow table we cannot plainly scan — skip it; its
                # backing content is captured via the tables we can read.
                continue
            serialized = sorted(repr(row) for row in rows)
            parts.append(f"TABLE {table}\n" + "\n".join(serialized))
        return "\n".join(parts)
    finally:
        conn.close()


def _state_digest(data_dir: Path) -> str:
    """Stable content hash over all persistent state under ``data_dir``.

    SQLite DBs (``*.sqlite``) are hashed by logical row set; their transient
    ``-wal`` / ``-shm`` sidecars are skipped; every other file is hashed by raw
    bytes. Mirrors ``tests/test_context_assembly_readonly.py``.
    """
    hasher = hashlib.sha256()
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = str(path.relative_to(data_dir)).replace("\\", "/")
        suffix = path.suffix
        if suffix == ".sqlite":
            hasher.update(f"SQLITE:{rel}\n".encode())
            hasher.update(_sqlite_logical_rows(path).encode())
        elif suffix in (".sqlite-wal", ".sqlite-shm"):
            continue
        else:
            hasher.update(f"FILE:{rel}\n".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


def _sqlite_table_names(db_path: Path) -> set[str]:
    """The set of table names declared in a SQLite DB's ``sqlite_master``."""
    conn = sqlite3.connect(str(db_path))
    try:
        return {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    finally:
        conn.close()


def _all_table_names(data_dir: Path) -> dict[str, set[str]]:
    """Map each ``*.sqlite`` file (relative path) to its set of table names."""
    return {
        str(path.relative_to(data_dir)).replace("\\", "/"): _sqlite_table_names(path)
        for path in sorted(data_dir.rglob("*.sqlite"))
        if path.is_file()
    }


def test_assemble_context_plan_is_byte_for_byte_identical(data_dir: Path) -> None:
    """Plan_Assembler stays side-effect free (Req 7.3).

    Content-hash *every* store table (and JSON blob / profile / event-log file)
    before and after calling ``assemble_context_plan`` directly — not via
    ``cmd_wake_up`` — and assert the full persistent state is byte-for-byte
    identical, with no retrieval signal added. Mirrors v2.5.0 Property 6
    (``test_context_assembly_readonly``), scoped here to the wake cold-start
    surfaces (L0 profile, L1 rules + accepted entries, L2 handoff).
    """
    project_name = "v251-assembler-purity"

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        profile_store = LocalProjectProfileStore(data_dir)
        run(
            profile_store.save(
                ProjectProfile(
                    project_name=project_name,
                    description="local-first AI memory runtime",
                    stacks=["python", "sqlite"],
                )
            )
        )
        _seed_confirmed_rule(
            backend,
            project_name,
            pattern="Prefer Tauri invoke over emit for IPC payloads over ~1MB.",
        )
        _seed_accepted_entry(
            backend,
            project_name,
            content="SQLite FTS5 with the porter tokenizer backs full-text search.",
            confidence=0.95,
        )
        run(
            backend.structured_store.save_task_handoff(
                TaskHandoff(
                    project_name=project_name,
                    task_id="resume-task-1",
                    summary="Wire cmd_wake_up to the plan-backed renderer.",
                    status="in_progress",
                )
            )
        )

        # --- Capture state BEFORE assembly ---
        digest_before = _state_digest(data_dir)
        signals_before = run(
            backend.structured_store.query_retrieval_signals(project_name)
        )

        # --- Run the assembler directly (cold start — no query) ---
        plan = run(assemble_context_plan(backend, project_name=project_name))

        # --- Capture state AFTER assembly ---
        digest_after = _state_digest(data_dir)
        signals_after = run(
            backend.structured_store.query_retrieval_signals(project_name)
        )
    finally:
        run(backend.close())

    # Sanity: the assembler actually produced the surfaced cold-start layers
    # (proves the read paths ran rather than short-circuiting before any work).
    assert [layer.layer for layer in plan.layers][:3] == ["L0", "L1", "L2"]

    # Req 7.3 — full persistent state is byte-for-byte identical: the assembler
    # performed no insert/update/delete on any store table.
    assert digest_after == digest_before

    # Req 7.3 — and added no RetrievalSignal during assembly.
    assert len(signals_after) == len(signals_before)


def test_wake_adds_no_new_writes_only_wake_surfaced_signals(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A full ``cmd_wake_up`` run adds only ``wake_surfaced`` signals + touches
    (Req 7.2, 7.4).

    After a cold-start wake over a seeded project:

    * **No new table / store** — the set of SQLite table names is identical
      before any wake and after (the schema is fixed at ``init`` via
      ``CREATE TABLE IF NOT EXISTS``; wake introduces no new table or store).
    * **Only ``wake_surfaced`` signals** — *every* ``RetrievalSignal`` emitted
      for the project is of type ``wake_surfaced`` (Req 7.4); wake emits no
      other signal kind.
    * **Only expected records mutated** — the only persistent-state changes are
      the new ``wake_surfaced`` signal rows plus the usage-counter touches on
      the surfaced confirmed rules / accepted entries; the project profile and
      the handoff are unchanged.
    """
    project_name = "v251-no-new-writes"

    # --- seed: profile (L0), 1 rule + 1 accepted entry (L1), 1 handoff (L2) ---
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        profile_store = LocalProjectProfileStore(data_dir)
        run(
            profile_store.save(
                ProjectProfile(
                    project_name=project_name,
                    description="local-first AI memory runtime",
                    stacks=["python", "sqlite"],
                )
            )
        )
        rule_id = _seed_confirmed_rule(
            backend,
            project_name,
            pattern="Redirect MCP server stdout to stderr to keep JSON-RPC clean.",
        )
        entry_id = _seed_accepted_entry(
            backend,
            project_name,
            content="Structured memory is persisted as JSON blobs plus a sqlite index.",
            confidence=0.9,
        )
        handoff = TaskHandoff(
            project_name=project_name,
            task_id="resume-task-2",
            summary="Wire cmd_wake_up to the plan-backed renderer.",
            status="in_progress",
        )
        run(backend.structured_store.save_task_handoff(handoff))
        handoff_id = handoff.id

        # Capture the table-name set + a digest of the non-signal records BEFORE
        # wake (the schema is already fully created at init()).
        tables_before = _all_table_names(data_dir)
        profile_before = run(profile_store.get(project_name))
        handoff_before = run(backend.structured_store.get_task_handoff(handoff_id))
    finally:
        run(backend.close())

    # --- act: cold-start wake (own backend), auto-ingest off for determinism ---
    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    capsys.readouterr()  # drain rendered wake output

    # --- read back signals + records via a fresh backend ---
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        all_signals = run(
            backend.structured_store.query_retrieval_signals(project_name)
        )
        tables_after = _all_table_names(data_dir)
        profile_after = run(LocalProjectProfileStore(data_dir).get(project_name))
        handoff_after = run(backend.structured_store.get_task_handoff(handoff_id))
        rule_after = run(backend.structured_store.get_confirmed_rule(rule_id))
        entry_after = run(backend.structured_store.get_memory_entry(entry_id))
    finally:
        run(backend.close())

    # Req 7.2 — no new table / store appeared (schema is fixed at init).
    assert tables_after == tables_before

    # Req 7.4 — every emitted RetrievalSignal is of type wake_surfaced.
    assert all_signals, "wake must emit at least one wake_surfaced signal"
    assert {s.signal_type for s in all_signals} == {"wake_surfaced"}

    # Req 7.2 — the only mutated records are the touched rule/entry; the
    # wake_surfaced signals point only at those surfaced ids.
    assert Counter(s.target_id for s in all_signals) == Counter([rule_id, entry_id])
    assert rule_after is not None and rule_after.usage_count == 1
    assert entry_after is not None and entry_after.usage_count == 1

    # The profile (L0) and handoff (L2) carry no signal/touch — unchanged.
    assert profile_after is not None and profile_before is not None
    assert profile_after.last_updated == profile_before.last_updated
    assert handoff_after is not None and handoff_before is not None
    assert handoff_after.updated_at == handoff_before.updated_at


# --------------------------------------------------------------------------- #
# Task 9.3 (Req 9.3) — scope-content guard.
#
# v2.5.1 is a *rendering-only* slice. Two negative-scope guarantees must hold
# for a cold-start ``cmd_wake_up`` over a seeded project:
#
# 1. **No full procedural skill step content in the wake output.** Procedural
#    memory is a distinct, seedable concept here: a confirmed :class:`Skill`
#    (``harness_mem.core.schemas.skill``) and its pending form
#    :class:`ProceduralCandidate` both carry an ordered ``steps: list[str]`` of
#    full step bodies. ``assemble_context_plan`` only ever reads skills on the
#    *query-driven* L3 layer (``_build_l3`` → ``search_skills``), and even there
#    emits a compact id/name/activation hint (``_skill_hint_summary``), never
#    the step bodies. ``wake`` is a *cold start* — it calls the assembler with
#    no ``query``, so L3 short-circuits empty and skills are not read at all,
#    while the renderer only ever surfaces L0/L1/L2. So a skill's full step text
#    must never reach the Rendered_Wake_Output. We seed a ``Skill`` *and* a
#    ``ProceduralCandidate`` whose steps carry distinctive sentinels and assert
#    those sentinels are absent from the captured wake output.
#
# 2. **No contradiction / stale-truth suggestion records written.** v2.5.1 only
#    *renders* the truth-status the plan already carries; it authors no new
#    supersession or stale-truth proposals. Those proposals are stored as
#    :class:`SupersedeCandidate` (``supersede_candidates`` — the mark-historical
#    "contradiction/replacement" record) and
#    :class:`StaleTruthSuggestionCandidate` (``stale_truth_suggestion_candidates``).
#    We capture the count of both record kinds before wake (zero — none seeded)
#    and assert each is unchanged after wake, proving the wake run writes no such
#    record. (These mirror the no-new-writes guarantee verified for the signal
#    stores in task 9.2, focused here on the suggestion stores.)
# --------------------------------------------------------------------------- #
_SKILL_STEP_SENTINEL = "FULL_PROC_STEP_BODY_SENTINEL_run_pytest_then_ruff_then_mypy"
_CANDIDATE_STEP_SENTINEL = "FULL_PROC_CANDIDATE_STEP_SENTINEL_draft_then_review_diff"


def test_wake_render_emits_no_skill_content_and_writes_no_suggestion_records(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_name = "v251-scope-guard"

    # --- seed: profile (L0), 1 rule + 1 accepted entry (L1), 1 handoff (L2),
    #     plus a confirmed Skill and a pending ProceduralCandidate whose full
    #     step bodies carry distinctive sentinels (must NOT surface in wake) ---
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        profile_store = LocalProjectProfileStore(data_dir)
        run(
            profile_store.save(
                ProjectProfile(
                    project_name=project_name,
                    description="local-first AI memory runtime",
                    stacks=["python", "sqlite"],
                )
            )
        )

        rule_pattern = "Redirect MCP server stdout to stderr to keep JSON-RPC clean."
        _seed_confirmed_rule(backend, project_name, pattern=rule_pattern)
        _seed_accepted_entry(
            backend,
            project_name,
            content="SQLite FTS5 with the porter tokenizer backs full-text search.",
            confidence=0.95,
        )
        run(
            backend.structured_store.save_task_handoff(
                TaskHandoff(
                    project_name=project_name,
                    task_id="resume-task-1",
                    summary="Wire cmd_wake_up to the plan-backed renderer.",
                    status="in_progress",
                )
            )
        )

        # A confirmed procedural skill with full multi-step bodies.
        run(
            backend.structured_store.save_skill(
                Skill(
                    project_name=project_name,
                    name="Release verification workflow",
                    activation_condition="When preparing to ship a code change",
                    steps=[
                        f"First {_SKILL_STEP_SENTINEL} across the whole suite",
                        "Then resolve every failure before continuing",
                        "Finally confirm the working tree is clean",
                    ],
                    termination_condition="All gates are green",
                    confidence=0.8,
                )
            )
        )

        # A pending procedural candidate with full multi-step bodies.
        run(
            backend.structured_store.save_procedural_candidate(
                ProceduralCandidate(
                    project_name=project_name,
                    activation_condition="When reviewing an incoming change",
                    steps=[
                        f"Open the diff and {_CANDIDATE_STEP_SENTINEL} line by line",
                        "Annotate risky hunks with review notes",
                    ],
                    termination_condition="Review is submitted",
                )
            )
        )

        # No suggestion / contradiction records are seeded — capture the
        # baseline counts (expected zero) BEFORE wake.
        supersede_before = run(
            backend.structured_store.list_supersede_candidates(project_name)
        )
        stale_before = run(
            backend.structured_store.list_stale_truth_suggestion_candidates(
                project_name
            )
        )
        assert supersede_before == []
        assert stale_before == []
    finally:
        run(backend.close())

    # --- act: cold-start wake (own backend), auto-ingest off for determinism ---
    assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
    wake_output = capsys.readouterr().out

    # Sanity: wake actually rendered plan-backed content (so the negative
    # assertions below are not vacuously true over empty output).
    assert rule_pattern in wake_output

    # 1. No full procedural skill step content leaked into the wake output —
    #    neither the confirmed Skill's steps nor the ProceduralCandidate's.
    assert _SKILL_STEP_SENTINEL not in wake_output
    assert _CANDIDATE_STEP_SENTINEL not in wake_output

    # 2. The wake run wrote no contradiction (supersede) or stale-truth
    #    suggestion records — both stores are unchanged from the empty baseline.
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        supersede_after = run(
            backend.structured_store.list_supersede_candidates(project_name)
        )
        stale_after = run(
            backend.structured_store.list_stale_truth_suggestion_candidates(
                project_name
            )
        )
    finally:
        run(backend.close())

    assert supersede_after == supersede_before
    assert stale_after == stale_before
    assert supersede_after == []
    assert stale_after == []
