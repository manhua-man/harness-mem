from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

import pytest

from harness_mem.core.schemas.observation import Observation
from harness_mem.storage import canonical_store
from harness_mem.storage.canonical_store import (
    build_canonical_store,
    canonical_checksum_relation,
    canonical_store_path,
    migrate_canonical_store_atomically,
    read_runtime_state,
    runtime_state_path,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_migration_preserves_canonical_only_and_newer_rows(tmp_path: Path) -> None:
    async def exercise() -> None:
        data_dir = tmp_path / "data"
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    id="shared-observation",
                    session_id="current-session",
                    client="codex",
                    raw_content="canonical current content",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
            await backend.verbatim_store.save(
                Observation(
                    id="canonical-only",
                    session_id="canonical-session",
                    client="codex",
                    raw_content="canonical-only content",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
        finally:
            await backend.close()

        legacy_dir = data_dir / "verbatim"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        legacy_rows = [
            Observation(
                id="shared-observation",
                session_id="stale-session",
                client="codex",
                raw_content="stale legacy content",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "demo"},
            ),
            Observation(
                id="legacy-only",
                session_id="legacy-session",
                client="cursor",
                raw_content="legacy-only content",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "demo"},
            ),
        ]
        for observation in legacy_rows:
            (legacy_dir / f"{observation.id}.json").write_text(
                json.dumps(observation.to_dict(), default=str),
                encoding="utf-8",
            )

        result = build_canonical_store(data_dir, project_name="demo")
        assert result["checksum_match"] is True
        assert result["imported_row_count"] == 1
        assert result["preserved_canonical_row_count"] == 1
        assert result["canonical_row_count"] == 3
        relation = canonical_checksum_relation(data_dir, project_name="demo")
        assert relation["relation"] == "canonical_superset_expected"
        assert relation["canonical_only_count"] == 1
        assert relation["changed_in_canonical_count"] == 1

        reopened = LocalMemoryBackend(data_dir)
        await reopened.init()
        try:
            shared = await reopened.verbatim_store.get("shared-observation")
            canonical_only = await reopened.verbatim_store.get("canonical-only")
            legacy_only = await reopened.verbatim_store.get("legacy-only")
            assert shared is not None
            assert shared.raw_content == "canonical current content"
            assert canonical_only is not None
            assert legacy_only is not None
            assert legacy_only.raw_content == "legacy-only content"
        finally:
            await reopened.close()

    asyncio.run(exercise())


def test_atomic_migration_uses_backup_staging_and_runtime_state_last(
    tmp_path: Path,
) -> None:
    async def seed() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    id="seed",
                    session_id="seed-session",
                    client="codex",
                    raw_content="canonical seed",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
        finally:
            await backend.close()

    asyncio.run(seed())
    data_dir = tmp_path / "data"
    result = migrate_canonical_store_atomically(data_dir, project_name="demo")
    runtime = read_runtime_state(data_dir)

    assert result["backup_created"] is True
    backup_path = Path(result["backup_db_path"])
    assert backup_path.is_file()
    backup = sqlite3.connect(backup_path)
    try:
        integrity = backup.execute("PRAGMA integrity_check").fetchone()
        row = backup.execute(
            "SELECT payload_json FROM observations WHERE entity_id = ?",
            ("seed",),
        ).fetchone()
    finally:
        backup.close()
    assert integrity == ("ok",)
    assert row is not None
    assert json.loads(row[0])["raw_content"] == "canonical seed"
    assert not Path(result["staging_db_path"]).exists()
    assert result["activated_atomically"] is True
    assert result["runtime_state_updated_last"] is True
    assert result["sqlite_integrity"] == "ok"
    assert result["checksum_relation"]["relation"] in {
        "exact_match",
        "canonical_superset_expected",
    }
    assert runtime is not None and runtime.mode == "canonical"


def test_atomic_migration_failure_before_activation_keeps_active_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def seed() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    id="active-row",
                    session_id="active-session",
                    client="codex",
                    raw_content="active canonical content",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
        finally:
            await backend.close()

    asyncio.run(seed())
    data_dir = tmp_path / "data"
    runtime_path = runtime_state_path(data_dir)
    runtime_before = runtime_path.read_bytes()

    def fail_after_staging_payload_commit(*_args, **_kwargs):
        raise RuntimeError("injected canonical-build failure")

    monkeypatch.setattr(
        canonical_store,
        "build_canonical_store",
        fail_after_staging_payload_commit,
    )
    with pytest.raises(RuntimeError, match="injected canonical-build failure"):
        migrate_canonical_store_atomically(data_dir, project_name="demo")

    assert runtime_path.read_bytes() == runtime_before
    assert not list((data_dir / "store_v2").glob("*.staging"))

    async def verify_active_store() -> None:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            observation = await backend.verbatim_store.get("active-row")
            assert observation is not None
            assert observation.raw_content == "active canonical content"
        finally:
            await backend.close()

    asyncio.run(verify_active_store())


def test_build_canonical_store_rolls_back_mid_import_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    legacy_dir = data_dir / "verbatim"
    legacy_dir.mkdir(parents=True)
    for index in range(2):
        observation = Observation(
            id=f"rollback-{index}",
            session_id=f"rollback-session-{index}",
            client="codex",
            raw_content=f"rollback content {index}",
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": "demo"},
        )
        (legacy_dir / f"{observation.id}.json").write_text(
            json.dumps(observation.to_dict(), default=str),
            encoding="utf-8",
        )

    target = data_dir / "store_v2" / "rollback.sqlite"
    target.parent.mkdir(parents=True)
    conn = sqlite3.connect(target)
    try:
        canonical_store.initialize_canonical_schema(conn)
        conn.commit()
    finally:
        conn.close()

    original_upsert = canonical_store._upsert_canonical_row
    calls = 0

    def fail_after_first_write(conn, row):
        nonlocal calls
        original_upsert(conn, row)
        calls += 1
        if calls == 1:
            raise RuntimeError("injected mid-import failure")

    monkeypatch.setattr(
        canonical_store,
        "_upsert_canonical_row",
        fail_after_first_write,
    )
    with pytest.raises(RuntimeError, match="injected mid-import failure"):
        build_canonical_store(data_dir, canonical_path=target)

    conn = sqlite3.connect(target)
    try:
        count = conn.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    finally:
        conn.close()
    assert calls == 1
    assert count == 0


def test_atomic_migration_fails_closed_when_live_store_changes_after_staging(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def seed() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    id="original-row",
                    session_id="original-session",
                    client="codex",
                    raw_content="original canonical content",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
        finally:
            await backend.close()

    asyncio.run(seed())
    data_dir = tmp_path / "data"
    runtime_path = runtime_state_path(data_dir)
    runtime_before = runtime_path.read_bytes()
    original_relation = canonical_store.canonical_checksum_relation
    injected = False

    def add_concurrent_row_after_staging(*args, **kwargs):
        nonlocal injected
        result = original_relation(*args, **kwargs)
        if not injected:
            injected = True
            runtime = canonical_store.CanonicalStoreRuntime(data_dir)
            try:
                runtime.upsert_payload(
                    "observations",
                    "concurrent-row",
                    Observation(
                        id="concurrent-row",
                        session_id="concurrent-session",
                        client="cursor",
                        raw_content="committed while migration validated staging",
                        content_type="transcript",
                        timestamp=datetime.now(timezone.utc),
                        metadata={"project_name": "demo"},
                    ).to_dict(),
                )
            finally:
                runtime.close()
        return result

    monkeypatch.setattr(
        canonical_store,
        "canonical_checksum_relation",
        add_concurrent_row_after_staging,
    )

    with pytest.raises(
        canonical_store.StorageV2MigrationError,
        match="changed while migration staging was built",
    ):
        migrate_canonical_store_atomically(data_dir, project_name="demo")

    assert runtime_path.read_bytes() == runtime_before
    assert not list((data_dir / "store_v2").glob("*.staging"))
    conn = sqlite3.connect(canonical_store_path(data_dir))
    try:
        row = conn.execute(
            "SELECT payload_json FROM observations WHERE entity_id = ?",
            ("concurrent-row",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert "committed while migration validated staging" in row[0]


def test_project_filtered_apply_migrates_all_projects_before_global_activation(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    legacy_dir = data_dir / "verbatim"
    legacy_dir.mkdir(parents=True)
    for project_name in ("alpha", "beta"):
        observation = Observation(
            id=f"{project_name}-observation",
            session_id=f"{project_name}-session",
            client="codex",
            raw_content=f"{project_name} content",
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": project_name},
        )
        (legacy_dir / f"{observation.id}.json").write_text(
            json.dumps(observation.to_dict(), default=str),
            encoding="utf-8",
        )

    result = migrate_canonical_store_atomically(data_dir, project_name="alpha")

    assert result["requested_project_name"] == "alpha"
    assert result["activation_scope"] == "all_projects"
    assert result["payload_migration"]["project_name"] is None
    assert result["payload_migration"]["migrated_row_count"] == 2
    assert result["canonical_store"]["project_name"] is None
    conn = sqlite3.connect(canonical_store_path(data_dir))
    try:
        rows = conn.execute(
            "SELECT entity_id, project_id FROM observations ORDER BY entity_id"
        ).fetchall()
    finally:
        conn.close()
    assert rows == [
        ("alpha-observation", "alpha"),
        ("beta-observation", "beta"),
    ]
    runtime = read_runtime_state(data_dir)
    assert runtime is not None
    assert runtime.mode == "canonical"
    assert runtime.legacy_payload_count == 2


def test_atomic_migration_restores_original_when_runtime_activation_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def seed() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.verbatim_store.save(
                Observation(
                    id="original",
                    session_id="original-session",
                    client="codex",
                    raw_content="must survive rollback",
                    content_type="transcript",
                    timestamp=datetime.now(timezone.utc),
                    metadata={"project_name": "demo"},
                )
            )
        finally:
            await backend.close()

    asyncio.run(seed())
    data_dir = tmp_path / "data"
    runtime_path = runtime_state_path(data_dir)
    runtime_before = runtime_path.read_bytes()

    def fail_runtime_state(*_args, **_kwargs):
        raise RuntimeError("injected runtime-state failure")

    monkeypatch.setattr(canonical_store, "write_runtime_state", fail_runtime_state)
    with pytest.raises(RuntimeError, match="injected runtime-state failure"):
        migrate_canonical_store_atomically(data_dir, project_name="demo")

    assert canonical_store_path(data_dir).is_file()
    assert runtime_path.read_bytes() == runtime_before
    assert list((data_dir / "store_v2" / "backups").glob("canonical-*.sqlite"))
    monkeypatch.undo()

    async def verify() -> None:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            observation = await backend.verbatim_store.get("original")
            assert observation is not None
            assert observation.raw_content == "must survive rollback"
        finally:
            await backend.close()

    asyncio.run(verify())

    # A later process can retry the migration from the restored state without
    # manual file surgery, which is the restart-recovery contract.
    retry = migrate_canonical_store_atomically(data_dir, project_name="demo")
    recovered_runtime = read_runtime_state(data_dir)
    assert retry["activated_atomically"] is True
    assert recovered_runtime is not None
    assert recovered_runtime.mode == "canonical"
