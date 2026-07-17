from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

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
    assert Path(result["backup_db_path"]).is_file()
    assert not Path(result["staging_db_path"]).exists()
    assert result["activated_atomically"] is True
    assert result["runtime_state_updated_last"] is True
    assert result["sqlite_integrity"] == "ok"
    assert result["checksum_relation"]["relation"] in {
        "exact_match",
        "canonical_superset_expected",
    }
    assert runtime is not None and runtime.mode == "canonical"


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
