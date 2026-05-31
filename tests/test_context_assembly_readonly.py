"""Read-only / no-side-effect invariant test for the v2.5.0 Plan_Assembler.

**Property 6: Read-Only / No Side Effect** (design.md) —
**Validates: Requirements 9.1, 9.2, 9.3, 9.5**

Producing a :class:`ContextAssemblyPlan` is side-effect free. This module
seeds a richly-populated, ``tmp_path``-isolated backend (every layer L0..L4 has
something to read, plus the most write-prone search paths), captures a digest
of *all* persistent state under the data dir, runs ``assemble_context_plan``
with a matching query, and asserts nothing changed:

1. The full-state content hash is byte-for-byte identical before vs after
   assembly (Req 9.1).
2. The ``RetrievalSignal`` row count is identical before vs after (Req 9.2).
3. A seeded accepted entry's ``usage_count`` / ``last_accessed_at`` are
   unchanged when re-fetched (Req 9.3).

Hashing approach (documented per the task brief). The backend persists state
two ways under ``data_dir``:

* **SQLite index DBs** — ``structured_index.sqlite`` and
  ``verbatim_index.sqlite`` (each a ``sqlite3`` file in WAL mode).
* **JSON blobs + files** — per-record blobs under ``structured/`` and
  ``verbatim/``, project profiles under ``profiles/``, and the event log.

We hash the **logical row set** of each SQLite DB rather than its raw bytes:
WAL checkpointing and ``-wal`` / ``-shm`` housekeeping can change a SQLite
file's bytes without any logical insert/update/delete, which would make a
naive byte hash flaky. So for every table named in ``sqlite_master`` we
``SELECT *``, sort the rows in Python (order-independent), and fold that into
the digest — this is exactly the "read each table's full row set (sorted)"
strategy the design calls for, and it still catches any real write (a new
signal row, a bumped ``usage_count``, a touched ``last_accessed_at``). Every
**other** file under ``data_dir`` (the JSON blobs, profiles, event log) is
hashed by raw bytes; the transient ``-wal`` / ``-shm`` sidecars are skipped.
Together this captures all persistent logical state.

All tests create the backend against the ``data_dir`` fixture (never the real
``~/.harness-mem/``, rule P1 数据路径隔离) and close it in a ``finally`` block
(rule P1 异步资源清理).
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.core.schemas.skill import Skill
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


# --------------------------------------------------------------------------- #
# Content-hash helpers (logical SQLite rows + raw bytes for everything else)
# --------------------------------------------------------------------------- #
def _sqlite_logical_rows(db_path: Path) -> str:
    """Serialize every table's full row set (sorted) from a SQLite DB.

    Opens its own short-lived connection (read-only SELECTs only — never a
    write) and, for each table in ``sqlite_master``, dumps ``SELECT *`` rows
    sorted by their ``repr`` so ordering never affects the digest. Sorting in
    Python (rather than ``ORDER BY``) keeps this robust across regular tables,
    FTS5 virtual tables, and their shadow tables alike.
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
    """Compute a stable content hash over all persistent state under ``data_dir``.

    SQLite DBs (``*.sqlite``) are hashed by logical row set; their transient
    ``-wal`` / ``-shm`` sidecars are skipped; every other file is hashed by raw
    bytes. See the module docstring for the rationale.
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
            # Transient WAL housekeeping — not logical state.
            continue
        else:
            hasher.update(f"FILE:{rel}\n".encode())
            hasher.update(path.read_bytes())
    return hasher.hexdigest()


# --------------------------------------------------------------------------- #
# Seed helpers — populate all five layers (mirrors test_context_assembly_layers)
# --------------------------------------------------------------------------- #
def _seed_profile(backend: LocalMemoryBackend, *, project_name: str) -> ProjectProfile:
    profile = ProjectProfile(
        project_name=project_name,
        description="Local-first AI memory runtime",
        stacks=["python", "sqlite"],
    )
    run(LocalProjectProfileStore(backend.data_dir).save(profile))
    return profile


def _seed_observation(
    backend: LocalMemoryBackend, *, project_name: str, raw_content: str
) -> Observation:
    observation = Observation(
        session_id="readonly-session-001",
        client="claude-code",
        raw_content=raw_content,
        content_type="transcript",
        metadata={"project_name": project_name},
        tags=["session", "claude-code"],
    )
    run(backend.verbatim_store.save(observation))
    return observation


def _seed_memory_entry(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    content: str,
    confidence: float,
    status: str = "accepted",
    valid_to: datetime | None = None,
    usage_count: int = 0,
    last_accessed_at: datetime | None = None,
    provenance: dict | None = None,
) -> MemoryEntry:
    entry = MemoryEntry(
        project_name=project_name,
        category="architecture",
        content=content,
        confidence=confidence,
        status=status,
        source="manual",
        valid_to=valid_to,
        usage_count=usage_count,
        last_accessed_at=last_accessed_at,
        provenance=provenance,
    )
    run(backend.structured_store.save_memory_entry(entry))
    return entry


def _seed_confirmed_rule(
    backend: LocalMemoryBackend, *, project_name: str, pattern: str, confirmed_at: datetime
) -> ConfirmedRule:
    rule = ConfirmedRule(
        project_name=project_name,
        pattern=pattern,
        trigger="when relevant",
        source_candidate_id="seed-candidate",
        confirmed_at=confirmed_at,
    )
    run(backend.structured_store.save_confirmed_rule(rule))
    return rule


def _seed_handoff(
    backend: LocalMemoryBackend, *, project_name: str, summary: str, last_activity: datetime
) -> TaskHandoff:
    handoff = TaskHandoff(
        project_name=project_name,
        task_id="seed-task",
        summary=summary,
        last_activity=last_activity,
    )
    run(backend.structured_store.save_task_handoff(handoff))
    return handoff


def _seed_retrieval_signal(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    target_id: str,
    signal_type: str,
    recorded_at: datetime,
) -> RetrievalSignal:
    signal = RetrievalSignal(
        project_name=project_name,
        signal_type=signal_type,
        target_kind="memory_entry",
        target_id=target_id,
        recorded_at=recorded_at,
    )
    run(backend.structured_store.save_retrieval_signal(signal))
    return signal


def _seed_skill(
    backend: LocalMemoryBackend, *, project_name: str, name: str, activation_condition: str
) -> Skill:
    skill = Skill(
        project_name=project_name,
        name=name,
        activation_condition=activation_condition,
        steps=["run the telemetry validation procedure"],
        termination_condition="done",
    )
    run(backend.structured_store.save_skill(skill))
    return skill


def _seed_relation_fact(
    backend: LocalMemoryBackend, *, project_name: str, evidence: str
) -> RelationFact:
    fact = RelationFact(
        project_name=project_name,
        source_entity="telemetry-service",
        target_entity="dashboard",
        relation_type="streams_to",
        evidence=evidence,
        source="manual",
    )
    run(backend.structured_store.save_relation_fact(fact))
    return fact


def _count_retrieval_signals(backend: LocalMemoryBackend, *, project_name: str) -> int:
    return len(run(backend.structured_store.query_retrieval_signals(project_name)))


# --------------------------------------------------------------------------- #
# Property 6 — Read-Only / No Side Effect (Req 9.1, 9.2, 9.3, 9.5)
# --------------------------------------------------------------------------- #
def test_assemble_context_plan_is_read_only(data_dir: Path) -> None:
    """``assemble_context_plan`` mutates no persistent state (Property 6).

    Seeds every layer's sources — profile (L0), a confirmed rule + accepted
    current-truth entry (L1), a handoff + recently-surfaced signal (L2), a
    query-matching entry / skill / relation fact (L3), and an observation +
    historical entry (L4) — then drives assembly with a matching query (so the
    write-prone L3 / L4 search paths run) and asserts the full-state content
    hash, the retrieval-signal count, and a known entry's usage stats are all
    unchanged (Req 9.1, 9.2, 9.3, 9.5).
    """
    project_name = "readonly-invariant"
    query = "telemetry"
    now = datetime.now(timezone.utc)

    # Known, non-default usage stats so a stray touch_* (reset OR increment) is
    # detectable on re-fetch (Req 9.3).
    known_usage_count = 7
    known_last_accessed = datetime(2025, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        # L0 — project profile.
        _seed_profile(backend, project_name=project_name)

        # L4 evidence source — a raw observation the accepted entry points at.
        observation = _seed_observation(
            backend,
            project_name=project_name,
            raw_content="We instrumented the telemetry pipeline end to end.",
        )

        # L1 / L2 / L3 — accepted current-truth entry that matches the query,
        # carries known usage stats, and is backed by the observation above.
        accepted_entry = _seed_memory_entry(
            backend,
            project_name=project_name,
            content="The telemetry pipeline streams events to the dashboard",
            confidence=0.95,
            usage_count=known_usage_count,
            last_accessed_at=known_last_accessed,
            provenance={"observation_ids": [observation.id]},
        )

        # L1 — a confirmed rule (highest tier).
        _seed_confirmed_rule(
            backend,
            project_name=project_name,
            pattern="always validate telemetry before shipping",
            confirmed_at=now - timedelta(hours=1),
        )

        # Boundary fixtures — a pending candidate and a historical (superseded)
        # entry. Present so the read paths that filter them still run read-only.
        _seed_memory_entry(
            backend,
            project_name=project_name,
            content="pending: maybe sample telemetry at 10%",
            confidence=0.99,
            status="pending",
        )
        _seed_memory_entry(
            backend,
            project_name=project_name,
            content="historical: telemetry used a flat log file",
            confidence=0.99,
            valid_to=now - timedelta(days=1),
        )

        # L2 — a recent handoff plus an in-window signal pointing at the
        # accepted entry (so the recently-surfaced derivation re-fetches it).
        _seed_handoff(
            backend,
            project_name=project_name,
            summary="resume wiring the telemetry dashboard",
            last_activity=now - timedelta(hours=2),
        )
        _seed_retrieval_signal(
            backend,
            project_name=project_name,
            target_id=accepted_entry.id,
            signal_type="search_hit",
            recorded_at=now - timedelta(days=1),
        )

        # L3 — a query-matching skill and relation fact.
        _seed_skill(
            backend,
            project_name=project_name,
            name="Telemetry validation loop",
            activation_condition="when telemetry needs validation",
        )
        _seed_relation_fact(
            backend,
            project_name=project_name,
            evidence="telemetry service streams metrics to the dashboard",
        )

        # --- Capture state BEFORE assembly ---
        digest_before = _state_digest(data_dir)
        signals_before = _count_retrieval_signals(backend, project_name=project_name)

        # --- Run the assembler (matching query exercises L3 + L4 search) ---
        plan = run(
            assemble_context_plan(backend, project_name=project_name, query=query)
        )

        # --- Capture state AFTER assembly ---
        digest_after = _state_digest(data_dir)
        signals_after = _count_retrieval_signals(backend, project_name=project_name)

        # Re-fetch the known entry to inspect its usage stats (Req 9.3).
        refetched = run(backend.structured_store.get_memory_entry(accepted_entry.id))
    finally:
        run(backend.close())

    # The assembler must have actually produced a plan (sanity — proves the
    # read paths ran rather than short-circuiting before any work).
    assert plan.project_name == project_name
    assert [layer.layer for layer in plan.layers] == ["L0", "L1", "L2", "L3", "L4"]

    # 1. Full persistent state is byte-for-byte identical (Req 9.1, 9.5).
    assert digest_after == digest_before

    # 2. No RetrievalSignal row was added (Req 9.2).
    assert signals_after == signals_before

    # 3. The known entry's usage stats are untouched (Req 9.3).
    assert refetched is not None
    assert refetched.usage_count == known_usage_count
    assert refetched.last_accessed_at == known_last_accessed
