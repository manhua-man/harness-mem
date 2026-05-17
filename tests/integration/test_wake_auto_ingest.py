import asyncio
import json
import os
from unittest.mock import MagicMock, patch
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.commands.wake import cmd_wake_up
from harness_mem.commands.support import (
    project_ingest_lock_path,
    project_ingest_scan_stamp_path,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

@pytest.mark.anyio
async def test_wake_up_auto_ingest_success(tmp_path, monkeypatch):
    """Test that wake-up successfully syncs new sessions."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    # Mock Project Profile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
    from harness_mem.core.schemas import ProjectProfile
    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    # Setup Backend
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    
    # Mock Adapter to return 1 new session that is NOT in the DB
    from harness_mem.core.schemas import Observation
    mock_adapter = MagicMock()
    mock_adapter.list_sessions.return_value = [
        {"session_id": "really-new-session", "path": Path("fake.jsonl"), "mtime": None}
    ]
    real_obs = Observation(
        id="test-id",
        session_id="really-new-session",
        client="test",
        raw_content="content",
        content_type="transcript",
        timestamp=datetime.now(timezone.utc),
        metadata={"project_name": "test-project"}
    )
    mock_adapter.session_to_observation.return_value = real_obs
    
    with patch("harness_mem.adapters.AdapterRegistry.build", return_value=mock_adapter):
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")
        
        output = f.getvalue()
        assert result == 0
        assert "🔄 Auto-synced: 1 new sessions ingested" in output

    lock_path = project_ingest_lock_path("test-project")
    assert lock_path.exists()
    record = json.loads(lock_path.read_text(encoding="utf-8"))
    assert record["state"] == "idle"
    assert record["last_session_id"] == "really-new-session"
    lock_mtime = datetime.fromtimestamp(lock_path.stat().st_mtime, tz=timezone.utc)
    assert (datetime.now(timezone.utc) - lock_mtime).total_seconds() < 5


@pytest.mark.anyio
async def test_wake_up_auto_ingest_skips_existing_session(tmp_path, monkeypatch):
    """Test that wake-up does not duplicate an already ingested session."""
    data_dir = tmp_path / "data_existing"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    from datetime import datetime, timezone

    from harness_mem.core.schemas import Observation, ProjectProfile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    await backend.verbatim_store.save(
        Observation(
            id="existing-obs",
            session_id="existing-session",
            client="test",
            raw_content="existing content",
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": "test-project"},
        )
    )
    await backend.close()

    mock_adapter = MagicMock()
    mock_adapter.list_sessions.return_value = [
        {"session_id": "existing-session", "path": Path("fake.jsonl"), "mtime": None}
    ]

    with patch("harness_mem.adapters.AdapterRegistry.build", return_value=mock_adapter):
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")

        output = f.getvalue()
        assert result == 0
        assert "🔄 Auto-sync: up to date" in output
        mock_adapter.session_to_observation.assert_not_called()

    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    try:
        observations = await backend.verbatim_store.list(session_id="existing-session", limit=10)
        assert len(observations) == 1
    finally:
        await backend.close()

@pytest.mark.anyio
async def test_wake_up_auto_ingest_timeout(tmp_path, monkeypatch):
    """Test that wake-up skips auto-ingest on timeout."""
    data_dir = tmp_path / "data_timeout"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    # Mock Project Profile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
    from harness_mem.core.schemas import ProjectProfile
    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    async def slow_sync(*args, **kwargs):
        await asyncio.sleep(0.5) # Over 300ms

    with patch("harness_mem.commands.wake._perform_sync", side_effect=slow_sync):
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")
        
        output = f.getvalue()
        assert "🔄 Auto-sync: timeout" in output
        assert result == 0


@pytest.mark.anyio
async def test_wake_up_auto_ingest_error_is_logged(tmp_path, monkeypatch):
    """Auto-sync errors must surface a hint and be persisted to events.log."""
    data_dir = tmp_path / "data_error"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.event_log._event_logger", None)

    from harness_mem.core.schemas import ProjectProfile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    async def boom(*args, **kwargs):
        raise RuntimeError("synthetic-ingest-failure")

    with patch("harness_mem.commands.wake._perform_sync", side_effect=boom):
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")

        output = f.getvalue()
        assert result == 0
        assert "🔄 Auto-sync: error (skipped, see events.log)" in output

    events_log = data_dir / "events.log"
    assert events_log.exists()
    lines = [
        json.loads(line)
        for line in events_log.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    auto_sync_events = [e for e in lines if e.get("command") == "wake-up.auto-sync"]
    assert auto_sync_events, "expected an events.log entry for the auto-sync failure"
    last = auto_sync_events[-1]
    assert last["extra"]["error_kind"] == "RuntimeError"
    assert "synthetic-ingest-failure" in last["extra"]["error"]


@pytest.mark.anyio
async def test_wake_up_auto_ingest_disabled_by_toml_config(tmp_path, monkeypatch):
    """Test that config.toml can disable auto-ingest."""
    data_dir = tmp_path / "data_config"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    config_toml = tmp_path / "config.toml"
    config_toml.write_text("[wake]\nauto_ingest = false\n", encoding="utf-8")
    monkeypatch.setattr("harness_mem.commands.support.CONFIG_TOML_PATH", config_toml)
    monkeypatch.setattr("harness_mem.commands.support.LEGACY_CONFIG_JSON_PATH", tmp_path / "config.json")

    from harness_mem.core.schemas import ProjectProfile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    with patch("harness_mem.commands.wake._auto_sync_sessions") as mock_sync:
        await cmd_wake_up("test-project")
        mock_sync.assert_not_called()

@pytest.mark.anyio
async def test_wake_up_auto_ingest_disabled(tmp_path, monkeypatch):
    """Test that --no-auto-ingest flag works."""
    data_dir = tmp_path / "data_disabled"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    # Mock Project Profile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
    from harness_mem.core.schemas import ProjectProfile
    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(ProjectProfile(project_name="test-project"))

    with patch("harness_mem.commands.wake._auto_sync_sessions") as mock_sync:
        await cmd_wake_up("test-project", no_auto_ingest=True)
        mock_sync.assert_not_called()


@pytest.mark.anyio
async def test_wake_up_auto_ingest_time_gate_skips_scan(tmp_path, monkeypatch):
    """A fresh lock mtime should skip the expensive session scan."""
    data_dir = tmp_path / "data_time_gate"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    from harness_mem.commands import wake as wake_module

    lock_path = project_ingest_lock_path("test-project")
    wake_module._write_lock_record(
        lock_path,
        pid=os.getpid(),
        state="idle",
        last_session_id="cursor-session",
        cursor_time=datetime.now(timezone.utc),
    )

    with patch("harness_mem.adapters.AdapterRegistry.build") as mock_build:
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")

        output = f.getvalue()
        assert result == 0
        assert "🔄 Auto-sync skipped: time gate" in output
        mock_build.assert_not_called()


@pytest.mark.anyio
async def test_wake_up_auto_ingest_persistent_scan_throttle(tmp_path, monkeypatch):
    """A recent no-op scan should leave a persistent throttle stamp for the next wake."""
    data_dir = tmp_path / "data_scan_throttle"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    config_toml = tmp_path / "config.toml"
    config_toml.write_text(
        "[wake]\nauto_ingest_min_interval_seconds = 0\nauto_ingest_scan_throttle_seconds = 300\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("harness_mem.commands.support.CONFIG_TOML_PATH", config_toml)
    monkeypatch.setattr("harness_mem.commands.support.LEGACY_CONFIG_JSON_PATH", tmp_path / "config.json")

    from harness_mem.core.schemas import ProjectProfile
    from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

    profile_store = LocalProjectProfileStore(data_dir)
    await profile_store.save(
        ProjectProfile(
            project_name="test-project",
            last_ingest_session_id="cursor-session",
        )
    )

    mock_adapter = MagicMock()
    mock_adapter.list_sessions.return_value = [
        {"session_id": "cursor-session", "path": Path("fake.jsonl"), "mtime": None}
    ]

    with patch("harness_mem.adapters.AdapterRegistry.build", return_value=mock_adapter):
        import io
        from contextlib import redirect_stdout

        first = io.StringIO()
        with redirect_stdout(first):
            first_result = await cmd_wake_up("test-project")

        second = io.StringIO()
        with redirect_stdout(second):
            second_result = await cmd_wake_up("test-project")

        assert first_result == 0
        assert second_result == 0
        assert "🔄 Auto-sync: up to date" in first.getvalue()
        assert "🔄 Auto-sync skipped: scan throttle" in second.getvalue()
        assert mock_adapter.list_sessions.call_count == 1

    scan_stamp = project_ingest_scan_stamp_path("test-project")
    assert scan_stamp.exists()


@pytest.mark.anyio
async def test_wake_up_auto_ingest_lock_gate_skips_when_other_pid_running(tmp_path, monkeypatch):
    """A held lock should stop ingest after the session gate but before writing."""
    data_dir = tmp_path / "data_lock_gate"
    data_dir.mkdir()
    monkeypatch.setattr("harness_mem.commands.wake.DEFAULT_DATA_DIR", data_dir)
    monkeypatch.setattr("harness_mem.commands.support.DEFAULT_DATA_DIR", data_dir)

    from harness_mem.commands import wake as wake_module

    old_cursor = datetime.now(timezone.utc) - timedelta(minutes=10)
    lock_path = project_ingest_lock_path("test-project")
    wake_module._write_lock_record(
        lock_path,
        pid=424242,
        state="running",
        last_session_id="cursor-session",
        cursor_time=old_cursor,
    )

    mock_adapter = MagicMock()
    mock_adapter.list_sessions.return_value = [
        {"session_id": "really-new-session", "path": Path("fake.jsonl"), "mtime": None}
    ]

    with (
        patch("harness_mem.adapters.AdapterRegistry.build", return_value=mock_adapter),
        patch("harness_mem.commands.wake._is_pid_running", return_value=True),
    ):
        import io
        from contextlib import redirect_stdout

        f = io.StringIO()
        with redirect_stdout(f):
            result = await cmd_wake_up("test-project")

        output = f.getvalue()
        assert result == 0
        assert "🔄 Auto-sync skipped: lock held by pid 424242" in output
        mock_adapter.session_to_observation.assert_not_called()
