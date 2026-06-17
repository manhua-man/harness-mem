"""v2.4.2+ maintenance roll-up guard across legacy hints and canonical self-heal.

v2.4.2 moved the v1.6.2 vector-index and v1.7.3 verbatim-exact-index hints out
of their scattered inline ``cmd_doctor`` emissions and into a single
"Maintenance" block fed by ``health_summary`` -> ``maintenance_hints`` (Task
6.6). The roll-up MUST NOT have changed operator-visible message text — only
the grouping. If a future refactor accidentally drops one of these checks from
the roll-up, an operator who used to see the hint would silently stop seeing
it.

This file is a focused supplement to ``tests/cli/test_doctor_vector_health.py``
(which the Task 6 work confirmed still passes post-removal). It drives the full
``cmd_doctor`` command end-to-end against a backend whose vector / exact index
is broken and asserts that operator-visible maintenance behavior remains
correct under the canonical runtime:

- ``HM-201`` still reaches stdout when the vector index is truly broken.
- the verbatim exact-index hint remains byte-identical at the helper level.
- a reopened backend may self-heal trigram drift from canonical truth before
  ``cmd_doctor`` runs, so the full command should not emit a stale ``HM-301``
  false positive in that case.

``cmd_doctor`` opens its own backend over ``DEFAULT_DATA_DIR`` (monkeypatched to
``tmp_path`` by the autouse ``data_dir`` fixture), so each test seeds + breaks
the index through a first backend handle, closes it, then runs the command —
mirroring the established pattern in ``test_doctor_vector_health.py``. Async
functions are driven via :func:`tests.helpers.run` (``asyncio.run``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.commands import doctor
from harness_mem.commands.doctor import cmd_doctor, maintenance_hints
from harness_mem.commands.support import set_active_project
from harness_mem.core.schemas import MemoryEntry, Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

PROJECT = "demo"


# ---- seed / break helpers ------------------------------------------------


def _build_observation() -> Observation:
    """Build one observation tagged to PROJECT (no I/O)."""
    return Observation(
        session_id="sess-1",
        client="claude-code",
        raw_content="We decided to pin sqlite-vec for the persistent vector store.",
        content_type="transcript",
        metadata={"project_name": PROJECT},
        tags=["session"],
    )


def _seed_project_observation(backend: LocalMemoryBackend) -> Observation:
    """Save one observation tagged to PROJECT from a synchronous context."""
    observation = _build_observation()
    run(backend.verbatim_store.save(observation))
    return observation


def _drop_vec_embeddings(backend: LocalMemoryBackend) -> None:
    """Drop ``vec_embeddings`` so the v1.6.2 check reports HM-201 not-built."""
    conn = backend.structured_store._index._conn_write()  # type: ignore[attr-defined]
    conn.execute("DROP TABLE IF EXISTS vec_embeddings")
    conn.commit()


# ---- test 1: v1.6.2 HM-201 still reaches cmd_doctor stdout ---------------


def test_cmd_doctor_still_emits_hm201_vector_hint(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validates: Requirements 5.5 — v1.6.2 vector-index hint survives the roll-up.

    A broken (dropped) ``vec_embeddings`` table is the canonical v1.6.2
    condition. Pre-v2.4.2 doctor emitted ``HM-201`` + a ``rebuild-vector-index``
    fix inline; v2.4.2 emits it through the unified Maintenance block. The exact
    operator-visible strings must still appear.
    """

    async def _drive() -> None:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        await backend.structured_store.save_memory_entry(
            MemoryEntry(
                id="entry-1",
                project_name=PROJECT,
                category="architecture",
                content="uses sqlite fts5",
                source="manual",
            )
        )
        # Break the vector index after seeding so the check has something to
        # complain about (memory entry present, vec table gone).
        _drop_vec_embeddings(backend)
        await backend.close()

        set_active_project(PROJECT)
        await cmd_doctor(PROJECT)

    _ = capsys.readouterr()  # clear prior output
    run(_drive())
    out = capsys.readouterr().out

    # The unified Maintenance block renders...
    assert "Maintenance:" in out
    # ...and the verbatim v1.6.2 strings are intact.
    assert "HM-201" in out
    assert "rebuild-vector-index" in out


# ---- test 2: canonical startup self-heals HM-301 drift before cmd_doctor ---


def test_cmd_doctor_rebuilds_exact_index_before_rollup(
    data_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validates: canonical runtime rebuild keeps cmd_doctor from surfacing stale HM-301.

    Seeds one observation (so the project has verbatim content) then empties the
    trigram exact index, which is the v1.7.3 ``indexed_observation_count == 0``
    condition. Under the canonical runtime, reopening the backend rebuilds
    derived trigram postings from canonical truth during bootstrap, so the full
    ``cmd_doctor`` path should not emit a stale HM-301 false positive even
    though the helper-level hint still exists for a live broken backend.
    """

    async def _drive() -> None:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        observation = _build_observation()
        await backend.verbatim_store.save(observation)
        # Empty the trigram index for the seeded observation → exact index has
        # observations on record but zero indexed postings (the HM-301 case).
        verbatim_index = backend.verbatim_store._index  # type: ignore[attr-defined]
        verbatim_index.delete_observation_trigrams(observation.id)
        await backend.close()

        set_active_project(PROJECT)
        await cmd_doctor(PROJECT)

    _ = capsys.readouterr()
    run(_drive())
    out = capsys.readouterr().out

    assert "HM-301" not in out
    assert "rebuild-verbatim-index" not in out


# ---- test 3: verbatim message/fix equality through the roll-up ----------


def test_maintenance_hints_vector_message_is_byte_identical(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.5 — vector hint preserves the v1.6.2 message + fix verbatim.

    The roll-up must reproduce the underlying check's ``message`` and
    ``fix_command`` byte-for-byte (only the grouping changed). A fresh backend
    has an empty ``vec_embeddings`` table, so the v1.6.2 check reports an issue.
    """
    vector_health = doctor._check_vector_index_health(backend, PROJECT)
    assert vector_health["has_issue"] is True

    report = run(maintenance_hints(backend, PROJECT))

    vector_hint = next(
        (h for h in report["hints"] if h["category"] == "vector_index"), None
    )
    assert vector_hint is not None
    assert vector_hint["message"] == vector_health["message"]
    assert vector_hint["fix_command"] == vector_health["fix_command"]


def test_maintenance_hints_exact_message_is_byte_identical(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.5 — exact-index hint preserves the v1.7.3 message + fix verbatim."""
    observation = _seed_project_observation(backend)
    verbatim_index = backend.verbatim_store._index  # type: ignore[attr-defined]
    verbatim_index.delete_observation_trigrams(observation.id)

    exact_health = run(doctor._check_verbatim_exact_index_health(backend, PROJECT))
    assert exact_health["has_issue"] is True

    report = run(maintenance_hints(backend, PROJECT))

    exact_hint = next(
        (h for h in report["hints"] if h["category"] == "verbatim_exact_index"), None
    )
    assert exact_hint is not None
    assert exact_hint["message"] == exact_health["message"]
    assert exact_hint["fix_command"] == exact_health["fix_command"]
