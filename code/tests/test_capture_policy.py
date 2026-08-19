from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.capture_policy import PRIVATE_REDACTION
from harness_mem.config.errors import ConfigValidationError
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _observation(content: str, *, session_id: str = "session-1") -> Observation:
    return Observation(
        session_id=session_id,
        client="codex",
        raw_content=content,
        content_type="transcript",
        timestamp=datetime.now(timezone.utc),
        metadata={"project_name": "demo"},
    )


def test_project_capture_config_overrides_user_policy(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".harness-mem").mkdir(parents=True)
    project.mkdir()
    (home / ".harness-mem" / "config.toml").write_text(
        '[capture]\nignore_clients = ["cursor"]\n\n[transcript]\nretention_days = 30\n',
        encoding="utf-8",
    )
    (project / ".harness-mem.toml").write_text(
        '[capture]\nignore_clients = ["codex"]\nignore_source_globs = ["*secret*.jsonl"]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))

    config = load_merged_config(project)

    assert config.capture_ignore_clients == ("codex",)
    assert config.capture_ignore_source_globs == ("*secret*.jsonl",)
    assert config.transcript_retention_days == 30
    assert config.distill_auto_max_jobs_per_wake == 2


def test_distill_auto_batch_config_accepts_three_and_rejects_larger_values(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home = tmp_path / "home"
    project = tmp_path / "project"
    (home / ".harness-mem").mkdir(parents=True)
    project.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: home))
    config_path = project / ".harness-mem.toml"
    config_path.write_text(
        "[distill.auto]\nmax_jobs_per_wake = 3\n",
        encoding="utf-8",
    )

    assert load_merged_config(project).distill_auto_max_jobs_per_wake == 3

    config_path.write_text(
        "[distill.auto]\nmax_jobs_per_wake = 4\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigValidationError):
        load_merged_config(project)


def test_private_spans_never_reach_raw_revision_chunks_or_observation(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    secret = "do-not-store-this-value"
    native = f"before <private>{secret}</private> after"

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            result = await persist_session_snapshot(
                backend,
                _observation(native),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="session-1",
                source_kind="jsonl",
                source_uri="file:///session.jsonl",
                source_text=native,
                raw_bytes=native.encode(),
            )
            assert result.source is not None
            raw = backend.transcript_store.reconstruct_raw(result.source.id).decode()
            reconstructed = backend.transcript_store.reconstruct(result.source.id)
            observation = await backend.verbatim_store.get(str(result.observation_id))
            assert observation is not None
            for stored in (raw, reconstructed, observation.raw_content):
                assert secret not in stored
                assert PRIVATE_REDACTION in stored
            assert result.source.metadata["capture_private_spans_removed"] == 1
        finally:
            await backend.close()

    asyncio.run(run())


def test_capture_ignore_creates_no_ledger_or_observation(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".harness-mem.toml").write_text(
        '[capture]\nignore_session_ids = ["private-session"]\n',
        encoding="utf-8",
    )

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            result = await persist_session_snapshot(
                backend,
                _observation("secret", session_id="private-session"),
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="private-session",
                source_kind="jsonl",
                source_uri="file:///private.jsonl",
                source_text="secret",
            )
            assert result.action == "ignored"
            assert result.reason == "session_ignored"
            assert backend.transcript_store.list_sources(project_name="demo") == []
            assert await backend.verbatim_store.list(project_name="demo") == []
        finally:
            await backend.close()

    asyncio.run(run())
