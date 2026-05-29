"""Tests for :func:`harness_mem.commands.doctor.maintenance_hints` (Req 5).

The diagnostic is a read-only roll-up that aggregates three maintenance
checks into one ordered hint list:

1. v1.6.2 vector-index health (``_check_vector_index_health`` — sync).
2. v1.7.3 verbatim-exact-index health
   (``_check_verbatim_exact_index_health`` — async).
3. A SQLite WAL-size threshold check against the structured index's
   ``structured_index.sqlite-wal`` file.

Each hint carries ``{category, code, message, fix_command}``. The existing
v1.6.2 / v1.7.3 ``message`` and ``fix_command`` are preserved verbatim so the
roll-up only re-groups operator-visible text (Req 5.5).

Real-backend behavior worth documenting: a *fresh* backend creates the
``vec_embeddings`` table at init but leaves it empty, so
``_check_vector_index_health`` reports ``has_issue=True`` with
``"HM-201: Vector index is empty"``. A fresh backend therefore yields exactly
one ``vector_index`` hint (HM-201), NOT an empty hint list. To exercise a
genuine "no hints" / "WAL only" path we monkeypatch the two index checks to
healthy and drive the WAL branch in isolation.

WAL sizes are fabricated cheaply with ``os.truncate`` (a sparse file) rather
than writing 100 MB. The autouse ``data_dir`` fixture in :mod:`tests.conftest`
keeps writes scoped to ``tmp_path``.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any

import pytest

from harness_mem.commands import doctor
from harness_mem.commands.doctor import maintenance_hints
from harness_mem.commands.doctor_thresholds import WAL_SIZE_THRESHOLD_BYTES
from harness_mem.core.schemas import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

PROJECT = "demo"
_WAL_NAME = "structured_index.sqlite-wal"


# ---- helpers -------------------------------------------------------------


def _hint_by_category(report: dict[str, Any], category: str) -> dict[str, Any] | None:
    for hint in report["hints"]:
        if hint["category"] == category:
            return hint
    return None


def _stub_index_checks_healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Force both index checks to report healthy so only the WAL branch fires.

    Lets the WAL-focused tests use a lightweight ``SimpleNamespace`` backend
    that exposes just ``data_dir`` — ``maintenance_hints`` otherwise reaches
    into ``backend.structured_store`` for the vector check.
    """

    def _healthy_vector(backend: Any, project_name: str) -> dict[str, str]:
        return {"has_issue": False, "message": "", "fix_command": ""}

    async def _healthy_exact(backend: Any, project_name: str) -> dict[str, str]:
        return {"has_issue": False, "message": "", "fix_command": ""}

    monkeypatch.setattr(doctor, "_check_vector_index_health", _healthy_vector)
    monkeypatch.setattr(doctor, "_check_verbatim_exact_index_health", _healthy_exact)


def _seed_project_observation(backend: LocalMemoryBackend) -> Observation:
    """Save one observation tagged to PROJECT (populates the trigram index)."""
    observation = Observation(
        session_id="sess-1",
        client="claude-code",
        raw_content="We decided to pin sqlite-vec for the persistent vector store.",
        content_type="transcript",
        metadata={"project_name": PROJECT},
        tags=["session"],
    )
    run(backend.verbatim_store.save(observation))
    return observation


def _drop_structured_vec_table(backend: LocalMemoryBackend) -> None:
    """Drop ``vec_embeddings`` from the structured index (simulate not-built)."""
    index = backend.structured_store._index  # type: ignore[attr-defined]
    conn = index._conn_write()
    with index._lock:
        conn.execute("DROP TABLE IF EXISTS vec_embeddings")
        conn.commit()


def _snapshot_blobs(backend: LocalMemoryBackend) -> dict[str, str]:
    """Map of every JSON blob path -> content under the data dir."""
    snapshot: dict[str, str] = {}
    for path in sorted(backend.data_dir.rglob("*.json")):
        if path.is_file():
            snapshot[str(path.relative_to(backend.data_dir))] = path.read_text()
    return snapshot


# ---- test 1: fresh backend documents the real (one-hint) behavior --------


def test_fresh_backend_yields_single_vector_index_hint(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.1, 5.7 — fresh install surfaces the empty vector index.

    A fresh backend creates ``vec_embeddings`` but leaves it empty, so the
    v1.6.2 check reports HM-201. There are no observations (so no exact-index
    hint) and the WAL is well under 100 MB, so the roll-up returns exactly one
    hint: the vector-index one. This documents that "fresh data dir" does NOT
    mean "no hints".
    """
    report = run(maintenance_hints(backend, PROJECT))

    assert len(report["hints"]) == 1
    hint = report["hints"][0]
    assert hint["category"] == "vector_index"
    assert hint["code"] == "HM-201"
    assert hint["message"] == "HM-201: Vector index is empty"
    assert _hint_by_category(report, "sqlite_wal") is None


# ---- test 2: genuinely-healthy everything -> no hints --------------------


def test_healthy_everything_yields_no_hints(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 5.3 — nothing to report -> empty hint list."""
    _stub_index_checks_healthy(monkeypatch)
    # No WAL file in this bare dir, both index checks stubbed healthy.
    fake_backend = SimpleNamespace(data_dir=tmp_path)

    report = run(maintenance_hints(fake_backend, PROJECT))  # type: ignore[arg-type]

    assert report == {"hints": []}


# ---- test 3: vector index not built -> HM-201 ---------------------------


def test_vector_index_not_built_yields_hm201(backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 5.1, 5.7 — missing vec table surfaces HM-201 not-built."""
    _drop_structured_vec_table(backend)

    report = run(maintenance_hints(backend, PROJECT))

    hint = _hint_by_category(report, "vector_index")
    assert hint is not None
    assert hint["code"] == "HM-201"
    assert hint["message"] == "HM-201: Vector index not built"
    assert "rebuild-vector-index" in hint["fix_command"]


# ---- test 4: missing exact index with observations present -> HM-301 ----


def test_missing_exact_index_with_observations_yields_hm301(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.1, 5.5 — observations present but trigram index empty.

    ``verbatim_store.save`` normally populates the trigram index, so we delete
    the postings for the one seeded observation to drive the
    ``indexed_observation_count == 0`` branch that emits HM-301.
    """
    observation = _seed_project_observation(backend)
    verbatim_index = backend.verbatim_store._index  # type: ignore[attr-defined]
    verbatim_index.delete_observation_trigrams(observation.id)

    report = run(maintenance_hints(backend, PROJECT))

    hint = _hint_by_category(report, "verbatim_exact_index")
    assert hint is not None
    assert hint["code"] == "HM-301"
    assert hint["message"] == "HM-301: Verbatim exact index is empty"
    assert "rebuild-verbatim-index" in hint["fix_command"]


# ---- test 5: WAL just below threshold -> no sqlite_wal hint --------------


def test_wal_just_below_threshold_yields_no_hint(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 5.6 — size == threshold - 1 does not trip the hint."""
    _stub_index_checks_healthy(monkeypatch)
    wal_path = tmp_path / _WAL_NAME
    wal_path.write_bytes(b"")
    os.truncate(wal_path, WAL_SIZE_THRESHOLD_BYTES - 1)
    fake_backend = SimpleNamespace(data_dir=tmp_path)

    report = run(maintenance_hints(fake_backend, PROJECT))  # type: ignore[arg-type]

    assert _hint_by_category(report, "sqlite_wal") is None
    assert report["hints"] == []


# ---- test 6: WAL just above threshold -> sqlite_wal hint -----------------


def test_wal_just_above_threshold_yields_hint(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 5.6 — size == threshold + 1 trips the HM-402 hint."""
    _stub_index_checks_healthy(monkeypatch)
    wal_path = tmp_path / _WAL_NAME
    wal_path.write_bytes(b"")
    os.truncate(wal_path, WAL_SIZE_THRESHOLD_BYTES + 1)
    fake_backend = SimpleNamespace(data_dir=tmp_path)

    report = run(maintenance_hints(fake_backend, PROJECT))  # type: ignore[arg-type]

    hint = _hint_by_category(report, "sqlite_wal")
    assert hint is not None
    assert hint["code"] == "HM-402"
    assert hint["fix_command"] == "harness-mem maintenance checkpoint-wal"
    # size_mb = floor((threshold + 1) / 1MB) == 100 for a 100 MB threshold.
    assert "100 MB" in hint["message"]


# ---- test 7: missing WAL file -> no sqlite_wal hint ----------------------


def test_missing_wal_file_yields_no_hint(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 5.7 — absent WAL file is safe (no hint, no raise)."""
    _stub_index_checks_healthy(monkeypatch)
    # Deliberately do not create any WAL file in this dir.
    fake_backend = SimpleNamespace(data_dir=tmp_path)

    report = run(maintenance_hints(fake_backend, PROJECT))  # type: ignore[arg-type]

    assert _hint_by_category(report, "sqlite_wal") is None
    assert report["hints"] == []


# ---- test 8: backward compat — verbatim message/fix preserved -----------


def test_vector_hint_is_byte_identical_to_underlying_check(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.5 — roll-up preserves the v1.6.2 message + fix verbatim."""
    vector_health = doctor._check_vector_index_health(backend, PROJECT)
    assert vector_health["has_issue"] is True  # fresh backend => empty index

    report = run(maintenance_hints(backend, PROJECT))

    hint = _hint_by_category(report, "vector_index")
    assert hint is not None
    assert hint["message"] == vector_health["message"]
    assert hint["fix_command"] == vector_health["fix_command"]


def test_exact_hint_is_byte_identical_to_underlying_check(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 5.5 — roll-up preserves the v1.7.3 message + fix verbatim."""
    observation = _seed_project_observation(backend)
    verbatim_index = backend.verbatim_store._index  # type: ignore[attr-defined]
    verbatim_index.delete_observation_trigrams(observation.id)

    exact_health = run(doctor._check_verbatim_exact_index_health(backend, PROJECT))
    assert exact_health["has_issue"] is True

    report = run(maintenance_hints(backend, PROJECT))

    hint = _hint_by_category(report, "verbatim_exact_index")
    assert hint is not None
    assert hint["message"] == exact_health["message"]
    assert hint["fix_command"] == exact_health["fix_command"]


# ---- test 9: read-only invariant ----------------------------------------


def test_maintenance_hints_is_read_only(backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 5.4 — no rebuild/checkpoint runs; nothing mutates.

    We fabricate an over-threshold WAL and seed one observation, snapshot the
    JSON blobs and the WAL file size, run the roll-up, and assert nothing
    changed. A rebuild would rewrite the index (changing the WAL), and a
    checkpoint would shrink the WAL — neither must happen.
    """
    _seed_project_observation(backend)
    wal_path = backend.data_dir / _WAL_NAME
    assert wal_path.exists()  # WAL mode is on; the file is live after init
    os.truncate(wal_path, WAL_SIZE_THRESHOLD_BYTES + 1)

    blobs_before = _snapshot_blobs(backend)
    wal_size_before = wal_path.stat().st_size

    report = run(maintenance_hints(backend, PROJECT))

    blobs_after = _snapshot_blobs(backend)
    wal_size_after = wal_path.stat().st_size

    assert blobs_before == blobs_after
    assert wal_size_before == wal_size_after  # no checkpoint ran
    # And the roll-up still reported the fabricated large WAL.
    assert _hint_by_category(report, "sqlite_wal") is not None
