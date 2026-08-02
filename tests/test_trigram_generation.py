from __future__ import annotations

import asyncio
from pathlib import Path
import threading
from typing import cast

import pytest

from harness_mem.commands.doctor_probes import _check_verbatim_exact_index_health
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.sqlite_index import SQLiteIndex


@pytest.mark.parametrize(
    "failure_point",
    ["after_staging_validation", "after_active_clear", "before_publish_commit"],
)
def test_trigram_generation_failure_preserves_previous_active_index(
    tmp_path: Path,
    failure_point: str,
) -> None:
    index = SQLiteIndex(tmp_path / "verbatim.sqlite")
    index.init_db()
    index.replace_observation_trigrams("old-observation", "old private evidence")

    def failpoint(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(point)

    with pytest.raises(RuntimeError, match=failure_point):
        index.rebuild_observation_trigrams(
            [("new-observation", "new canonical evidence")],
            source_generation="observations:new",
            source_id_hash=index.stable_id_hash(["new-observation"]),
            failpoint=failpoint,
        )

    assert index.observation_ids_with_trigrams() == {"old-observation"}
    assert index.get_active_index_generation("trigram:observations") is None
    index.close()

    reopened = SQLiteIndex(tmp_path / "verbatim.sqlite")
    reopened.init_db()
    try:
        assert reopened.observation_ids_with_trigrams() == {"old-observation"}
    finally:
        reopened.close()


def test_trigram_generation_source_change_fails_closed(tmp_path: Path) -> None:
    index = SQLiteIndex(tmp_path / "verbatim.sqlite")
    index.init_db()
    index.replace_observation_trigrams("old-observation", "old private evidence")

    with pytest.raises(Exception, match="source changed"):
        index.rebuild_observation_trigrams(
            [("new-observation", "new canonical evidence")],
            source_generation="observations:new",
            source_id_hash=index.stable_id_hash(["new-observation"]),
            verify_source=lambda: False,
        )

    assert index.observation_ids_with_trigrams() == {"old-observation"}
    assert index.get_active_index_generation("trigram:observations") is None


def test_project_scoped_rebuild_preserves_every_projects_physical_index(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        store = LocalVerbatimStore(tmp_path / "data")
        try:
            await store.save(
                Observation(
                    id="project-a-observation",
                    session_id="session-a",
                    client="codex",
                    raw_content="alpha evidence marker",
                    content_type="transcript",
                    metadata={"project_name": "project-a"},
                )
            )
            await store.save(
                Observation(
                    id="project-b-observation",
                    session_id="session-b",
                    client="claude-code",
                    raw_content="bravo evidence marker",
                    content_type="transcript",
                    metadata={"project_name": "project-b"},
                )
            )
            index = cast(SQLiteIndex, store.index)
            index.delete_observation_trigrams("project-b-observation")

            indexed, postings = await store.rebuild_exact_index("project-a")

            assert indexed == 1
            assert postings > 0
            assert index.observation_ids_with_trigrams() == {
                "project-a-observation",
                "project-b-observation",
            }
            assert store.exact_index_generation_report()["has_issue"] is False
        finally:
            store.close()

    asyncio.run(exercise())


def test_doctor_reports_canonical_content_drift_after_generation_publish(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            store = cast(LocalVerbatimStore, backend.verbatim_store)
            await store.save(
                Observation(
                    id="drift-observation",
                    session_id="session-drift",
                    client="codex",
                    raw_content="first canonical content",
                    content_type="transcript",
                    metadata={"project_name": "doctor-project"},
                )
            )
            await store.rebuild_exact_index("doctor-project")
            healthy = await _check_verbatim_exact_index_health(
                backend, "doctor-project"
            )
            assert healthy["has_issue"] is False

            await store.save(
                Observation(
                    id="drift-observation",
                    session_id="session-drift",
                    client="codex",
                    raw_content="updated canonical content",
                    content_type="transcript",
                    metadata={"project_name": "doctor-project"},
                )
            )
            drifted = await _check_verbatim_exact_index_health(
                backend, "doctor-project"
            )
            assert drifted["has_issue"] is True
            assert "HM-302" in drifted["message"]
            assert drifted["assessment"] == "expected_growth"
            assert "manifest_refresh_required" in drifted["message"]
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_fails_closed_when_exact_index_probe_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    session_id="session-probe",
                    client="codex",
                    raw_content="probe evidence",
                    content_type="transcript",
                    metadata={"project_name": "doctor-project"},
                )
            )
            monkeypatch.setattr(
                backend.verbatim_store,
                "exact_index_stats",
                lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
            )
            report = await _check_verbatim_exact_index_health(
                backend, "doctor-project"
            )
            assert report["has_issue"] is True
            assert "HM-303" in report["message"]
            assert report["verification_status"] == "unknown"
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_doctor_exact_repair_command_uses_safe_project_placeholder(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data-command")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    session_id="session-command",
                    client="codex",
                    raw_content="probe evidence",
                    content_type="transcript",
                    metadata={
                        "project_name": "unsafe; Remove-Item -Recurse project"
                    },
                )
            )
            monkeypatch.setattr(
                backend.verbatim_store,
                "exact_index_stats",
                lambda: (_ for _ in ()).throw(RuntimeError("probe failed")),
            )
            report = await _check_verbatim_exact_index_health(
                backend,
                "unsafe; Remove-Item -Recurse project",
            )

            assert report["fix_command"].endswith("--project <PROJECT_NAME>")
            assert "Remove-Item" not in report["fix_command"]
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_parallel_trigram_rebuilds_use_isolated_staging_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "parallel-trigram.sqlite"
    first = SQLiteIndex(db_path)
    second = SQLiteIndex(db_path)
    first.init_db()
    second.init_db()
    barrier = threading.Barrier(2)
    errors: list[BaseException] = []
    results: list[dict] = []
    records = [("one", "shared canonical evidence")]
    source_hash = first.stable_id_hash(["one"])

    def worker(index: SQLiteIndex) -> None:
        try:
            results.append(
                index.rebuild_observation_trigrams(
                    records,
                    source_generation="observations:same",
                    source_id_hash=source_hash,
                    failpoint=lambda point: (
                        barrier.wait(timeout=5)
                        if point == "after_staging_validation"
                        else None
                    ),
                )
            )
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=worker, args=(first,)),
        threading.Thread(target=worker, args=(second,)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 2
    with first.locked_connection() as conn:
        staging = conn.execute(
            "SELECT name FROM sqlite_master "
            "WHERE name LIKE 'observation_trigrams_staging_%'"
        ).fetchall()
    assert staging == []
    assert first.observation_ids_with_trigrams() == {"one"}
    first.close()
    second.close()


def test_partial_trigram_posting_corruption_is_detected(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "corruption")
        await backend.init()
        try:
            store = cast(LocalVerbatimStore, backend.verbatim_store)
            await store.save(
                Observation(
                    id="corrupt-observation",
                    session_id="session-corrupt",
                    client="codex",
                    raw_content="private canonical evidence marker",
                    content_type="transcript",
                    metadata={"project_name": "doctor-project"},
                )
            )
            await store.rebuild_exact_index("doctor-project")
            index = cast(SQLiteIndex, store.index)
            with index.locked_connection() as conn:
                conn.execute(
                    "DELETE FROM observation_trigrams WHERE rowid IN "
                    "(SELECT rowid FROM observation_trigrams LIMIT 1)"
                )
                conn.commit()

            report = store.exact_index_generation_report()
            assert report["has_issue"] is True
            assert report["assessment"] == "corruption"
            health = await _check_verbatim_exact_index_health(
                backend, "doctor-project"
            )
            assert health["has_issue"] is True
            assert health["assessment"] == "corruption"
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_soft_deleted_observation_never_returns_to_rebuilt_trigrams(
    tmp_path: Path,
) -> None:
    async def exercise() -> None:
        store = LocalVerbatimStore(tmp_path / "soft-delete")
        try:
            await store.save(
                Observation(
                    id="private-observation",
                    session_id="private-session",
                    client="codex",
                    raw_content="private deleted evidence",
                    content_type="transcript",
                    metadata={"project_name": "private-project"},
                )
            )
            assert await store.soft_delete("private-observation") is True
            await store.rebuild_exact_index("private-project")
            index = cast(SQLiteIndex, store.index)
            assert "private-observation" not in index.observation_ids_with_trigrams()
            assert store.exact_index_generation_report()["has_issue"] is False
        finally:
            store.close()

        reopened = LocalVerbatimStore(tmp_path / "soft-delete")
        try:
            await reopened.init_runtime()
            index = cast(SQLiteIndex, reopened.index)
            assert "private-observation" not in index.observation_ids_with_trigrams()
        finally:
            reopened.close()

    asyncio.run(exercise())
