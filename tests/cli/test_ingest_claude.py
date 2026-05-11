from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import patch_cli_adapters, run, write_claude_session

pytestmark = pytest.mark.cli


def test_incremental_ingest_does_not_reimport_old_sessions(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    write_claude_session(claude_sessions_root, "demo", "sess-1", "u1", ["a1"])
    write_claude_session(claude_sessions_root, "demo", "sess-2", "u2", ["a2"])
    write_claude_session(claude_sessions_root, "demo", "sess-3", "u3", ["a3"])

    now = datetime.now().timestamp()
    for offset, session_id in enumerate(["sess-1", "sess-2", "sess-3"], start=3):
        session_path = claude_sessions_root / "demo" / f"{session_id}.jsonl"
        session_time = now - (offset * 60)
        os.utime(session_path, (session_time, session_time))

    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 2)) == 0
    assert run(cli.cmd_ingest("claude-code", "demo", 2)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert [observation.session_id for observation in observations] == ["sess-1", "sess-2"]
    finally:
        run(backend.close())


def test_full_rescan_bypasses_cursor_without_duplicate_ingest(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    write_claude_session(claude_sessions_root, "demo", "sess-1", "u1", ["a1"])
    write_claude_session(claude_sessions_root, "demo", "sess-2", "u2", ["a2"])
    write_claude_session(claude_sessions_root, "demo", "sess-3", "u3", ["a3"])

    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 1)) == 0
    assert run(cli.cmd_ingest("claude-code", "demo", 10, True)) == 0

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        observations = run(backend.verbatim_store.list(limit=10))
        assert sorted(observation.session_id for observation in observations) == ["sess-1", "sess-2", "sess-3"]
    finally:
        run(backend.close())

    captured = capsys.readouterr().out
    assert "[Full Rescan]" in captured


def test_incremental_ingest_warns_when_cursor_is_missing(
    data_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    write_claude_session(claude_sessions_root, "demo", "sess-1", "u1", ["a1"])
    write_claude_session(claude_sessions_root, "demo", "sess-2", "u2", ["a2"])
    write_claude_session(claude_sessions_root, "demo", "sess-3", "u3", ["a3"])

    profile_store = LocalProjectProfileStore(data_dir)
    run(
        profile_store.save(
            ProjectProfile(
                project_name="demo",
                last_ingest_session_id="missing-session",
                last_ingest_at=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_ingest("claude-code", "demo", 10)) == 0
    captured = capsys.readouterr().out
    assert "cursor missing-session not found" in captured


def test_ingest_detects_unity_profile_from_claude_session_cwd(
    data_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    claude_sessions_root: Path,
    codex_sessions_root: Path,
):
    unity_root = tmp_path / "My project"
    (unity_root / "Assets").mkdir(parents=True)
    (unity_root / "Packages").mkdir()
    (unity_root / "ProjectSettings").mkdir()
    (unity_root / "Packages" / "manifest.json").write_text(
        json.dumps({"dependencies": {"com.unity.inputsystem": "1.7.0"}}),
        encoding="utf-8",
    )
    (unity_root / "ProjectSettings" / "ProjectVersion.txt").write_text(
        "m_EditorVersion: 6000.0.0f1",
        encoding="utf-8",
    )
    (unity_root / "Assembly-CSharp.csproj").write_text("<Project />", encoding="utf-8")

    project_name = "f--pvz-pvzseason-My-project-Assets"
    session_dir = claude_sessions_root / project_name
    session_dir.mkdir(parents=True)
    records = [
        {
            "type": "user",
            "cwd": str(unity_root / "Assets"),
            "message": {"content": "Please inspect this Unity project."},
        },
        {
            "type": "assistant",
            "cwd": str(unity_root / "Assets"),
            "message": {"content": [{"type": "text", "text": "I checked the Unity project layout."}]},
        },
    ]
    (session_dir / "sess-unity.jsonl").write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )

    patch_cli_adapters(
        monkeypatch,
        claude_sessions_root=claude_sessions_root,
        codex_sessions_root=codex_sessions_root,
    )

    assert run(cli.cmd_ingest("claude-code", project_name, 1)) == 0

    profile_store = LocalProjectProfileStore(data_dir)
    profile = run(profile_store.get(project_name))
    assert profile is not None
    assert "unity" in profile.stacks
    assert "csharp" in profile.stacks
    assert "ProjectSettings/ProjectVersion.txt" in profile.key_files

    captured = capsys.readouterr().out
    assert "Auto-detected profile: unity, csharp" in captured
