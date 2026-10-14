from __future__ import annotations

import base64
import asyncio
import json
from pathlib import Path

import pytest

from harness_mem.adapters.antigravity import adapter as module
from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.source_inspection import ownership_for
from harness_mem.adapters.source_metadata import HEADER_BYTES
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _write(path: Path, records: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"\xef\xbb\xbf" + b"".join(
        json.dumps(record, ensure_ascii=False).encode("utf-8") + b"\r\n"
        for record in records
    ))
    return path


def _transcript(brain: Path, session_id: str, records: list[dict]) -> Path:
    return _write(
        brain / session_id / ".system_generated" / "logs" / "transcript_full.jsonl",
        records,
    )


def _cli(tmp_path: Path):
    cli = tmp_path / "cli"
    history = cli / "history.jsonl"
    root = tmp_path / "project"
    adapter = AntigravityAdapter(None, brain_dir=tmp_path / "brain", cli_root=cli)
    return adapter, cli, history, root


def _forbidden(*args, **kwargs):
    raise AssertionError("unrelated transcript/export must not be read")


def test_history_enumeration_streams_once_without_body_exports(tmp_path, monkeypatch):
    adapter, cli, history, root = _cli(tmp_path)
    rows = [
        {"conversationId": "wanted", "workspace": str(root), "display": "one", "timestamp": 10},
        {"conversationId": "other", "cwd": str(tmp_path / "elsewhere"), "display": "SECRET", "timestamp": 20},
        {"conversationId": "wanted", "cwd": str(root), "display": "two", "timestamp": 30},
    ]
    _write(history, rows)
    wanted = _transcript(cli / "brain", "wanted", [{"type": "USER_INPUT", "content": "wanted"}])
    other = _transcript(cli / "brain", "other", [{"type": "USER_INPUT", "content": "SECRET" * 1000}])
    native_sizes = {"wanted": wanted.stat().st_size, "other": other.stat().st_size}
    row_sizes = {}
    for line in history.read_bytes().splitlines(keepends=True):
        row = json.loads(line.decode("utf-8-sig"))
        key = row["conversationId"]
        row_sizes[key] = row_sizes.get(key, 0) + len(line)
    original_open = Path.open
    opens = []

    def guarded_open(path, *args, **kwargs):
        assert path not in {wanted, other}
        if path == history:
            opens.append(path)
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(module, "_history_export", _forbidden)
    monkeypatch.setattr(module, "_history_sessions", _forbidden)
    monkeypatch.setattr(module, "_read_records", _forbidden)
    sessions = adapter.list_session_metadata()
    assert opens == [history]
    assert {record["session_id"] for record in sessions} == {"wanted", "other"}
    for record in sessions:
        key = record["session_id"]
        assert record["path"] == history
        assert record["size_bytes"] == row_sizes[key] + native_sizes[key]
        assert record["mtime_ns"] > 0
        assert record["metadata_status"] == "available"
        assert "lines" not in record
    assert "SECRET" not in repr(sessions)
    assert len(adapter.list_session_metadata(limit=1)) == 1
    assert adapter.list_session_metadata(min_size_kb=10_000) == []


def test_history_conflicts_preserve_all_roots_and_unknown_ownership(tmp_path):
    adapter, _, history, root = _cli(tmp_path)
    other = tmp_path / "other"
    _write(history, [
        {"conversationId": "conflict", "workspace": str(root), "cwd": str(other)},
        {"conversationId": "conflict", "workspace_root": str(root / "third")},
    ])
    record, = adapter.list_session_metadata()
    assert set(record["project_roots"]) == {str(root), str(other), str(root / "third")}
    assert record["metadata_status"] == "unknown"
    assert "cwd" not in record
    assert ownership_for(record["project_roots"], root) == "unknown"
    with pytest.raises(ValueError, match="conflicting"):
        adapter.read_session_source(history, "conflict")


def test_selected_history_exports_only_target_and_complete_native_bytes(tmp_path, monkeypatch):
    adapter, cli, history, root = _cli(tmp_path)
    _write(history, [
        {"conversationId": "wanted", "workspace": str(root), "display": "first"},
        {"conversationId": "other", "workspace": str(root), "display": "UNRELATED_SECRET"},
        {"conversationId": "wanted", "cwd": str(root), "response": "last"},
    ])
    selected = _transcript(cli / "brain", "wanted", [
        {"type": "USER_INPUT", "content": "中" * HEADER_BYTES + "COMPLETE_TAIL"},
        {"type": "TOOL_RESULT", "content": "<private>private-native-span</private>"},
    ])
    unrelated = _transcript(cli / "brain", "other", [{"content": "UNRELATED_SECRET"}])
    native = selected.read_bytes()
    adapter.list_session_metadata()
    original_read_bytes = Path.read_bytes
    reads = []

    def guarded_read_bytes(path):
        assert path != unrelated
        reads.append(path)
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read_bytes)
    monkeypatch.setattr(module, "_history_sessions", _forbidden)
    monkeypatch.setattr(module, "_read_records", _forbidden)
    exported = adapter.read_session_source(history, "wanted")
    assert reads == [selected]
    assert exported["project_roots"] == [str(root)]
    assert "COMPLETE_TAIL" in exported["source_text"]
    assert "private-native-span" in exported["source_text"]  # caller owns privacy filtering
    assert "UNRELATED_SECRET" not in exported["source_text"]
    assert b"UNRELATED_SECRET" not in exported["raw_bytes"]
    raw_records = [json.loads(line) for line in exported["raw_bytes"].splitlines()]
    assert base64.b64decode(raw_records[0]["transcript_raw_base64"]) == native
    assert len(exported["records"]) == 2
    assert len(exported["transcript_records"]) == 2
    assert exported["source_uri"].endswith("#conversation=wanted")
    assert original_read_bytes(selected) == native


def test_selected_brain_uses_exact_history_membership_and_complete_source(tmp_path):
    adapter, _, history, root = _cli(tmp_path)
    path = _transcript(adapter.brain_dir, "exact", [
        {"type": "USER_INPUT", "content": "x" * (HEADER_BYTES * 2) + "TAIL"},
    ])
    _write(history, [{"conversationId": "exact", "workspace": str(root), "display": "prompt"}])
    native = path.read_bytes()
    exported = adapter.read_session_source(path, "exact")
    assert exported["project_roots"] == [str(root)]
    assert exported["raw_bytes"] == native
    assert exported["source_text"].endswith("TAIL\"}\r\n")
    assert ownership_for(exported["project_roots"], root) == "project"


def test_helper_cwd_and_path_mentions_never_confer_metadata_ownership(tmp_path):
    adapter, _, history, root = _cli(tmp_path)
    _write(history, [{
        "conversationId": "helper-only", "display": f"work on {root}",
        "tool_calls": [{"name": "list_dir", "args": {"Cwd": str(root), "cwd": str(root)}}],
    }])
    path = _transcript(adapter.brain_dir, "brain-helper", [{
        "type": "PLANNER_RESPONSE", "content": f"work on {root}",
        "tool_calls": [{"name": "list_dir", "args": {"Cwd": str(root)}}],
    }])
    records = adapter.list_session_metadata()
    assert {record["session_id"] for record in records} == {"helper-only", "brain-helper"}
    for record in records:
        assert record["project_roots"] == []
        assert record["metadata_status"] == "unknown"
        assert "cwd" not in record
    assert adapter.read_session_source(path, "brain-helper")["project_roots"] == []
    assert adapter.read_session_source(history, "helper-only")["project_roots"] == []


def test_brain_header_is_bounded_but_selected_tail_conflict_is_rejected(tmp_path, monkeypatch):
    adapter = AntigravityAdapter(None, brain_dir=tmp_path / "brain")
    root = tmp_path / "project"
    path = _transcript(adapter.brain_dir, "long", [
        {"type": "USER_INPUT", "cwd": str(root), "content": "start"},
        {"type": "AI_RESPONSE", "content": "x" * (HEADER_BYTES * 2)},
        {"type": "USER_INPUT", "cwd": str(tmp_path / "other"), "content": "end"},
    ])
    original_open = Path.open
    budgets = []

    class HeaderReader:
        def __enter__(self):
            self.stream = original_open(path, "rb")
            return self

        def __exit__(self, *args):
            self.stream.close()

        def read(self, size=-1):
            assert size == HEADER_BYTES
            budgets.append(size)
            return self.stream.read(size)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", lambda selected, *args, **kwargs: HeaderReader())
        scoped.setattr(module, "_read_records", _forbidden)
        record, = adapter.list_session_metadata()
    assert budgets == [HEADER_BYTES]
    assert record["size_bytes"] == path.stat().st_size
    assert record["project_roots"] == [str(root)]
    with pytest.raises(ValueError, match="conflicting"):
        adapter.read_session_source(path, "long")


@pytest.mark.parametrize("kind", ["history", "brain"])
def test_selected_source_rejects_workspace_drift(tmp_path, kind):
    adapter, _, history, root = _cli(tmp_path)
    if kind == "history":
        path = _write(history, [{"conversationId": "drift", "workspace": str(root), "display": "same"}])
        replacement = [{"conversationId": "drift", "workspace": str(tmp_path / "other"), "display": "same"}]
    else:
        path = _transcript(adapter.brain_dir, "drift", [{"cwd": str(root), "type": "USER_INPUT", "content": "same"}])
        replacement = [{"cwd": str(tmp_path / "other"), "type": "USER_INPUT", "content": "same"}]
    adapter.list_session_metadata()
    _write(path, replacement)
    with pytest.raises(ValueError, match="changed"):
        adapter.read_session_source(path, "drift")


def test_history_and_complete_transcript_conflict_is_rejected(tmp_path):
    adapter, cli, history, root = _cli(tmp_path)
    _write(history, [{"conversationId": "one", "workspace": str(root), "display": "one"}])
    _transcript(cli / "brain", "one", [{"cwd": str(tmp_path / "other"), "type": "USER_INPUT", "content": "one"}])
    record, = adapter.list_session_metadata()
    assert record["project_roots"] == [str(root)]
    exported = module._history_export_for_session(history, "one", cli_root=cli)
    assert exported["project_roots"] == [str(root), str(tmp_path / "other")]
    with pytest.raises(ValueError, match="conflicting"):
        adapter.read_session_source(history, "one")


def test_similar_conversation_id_cannot_supply_brain_root(tmp_path):
    adapter, _, history, root = _cli(tmp_path)
    _write(history, [{"conversationId": "one-helper", "cwd": str(root), "display": "one"}])
    path = _transcript(adapter.brain_dir, "one", [{"type": "USER_INPUT", "content": "one-helper"}])
    record = next(row for row in adapter.list_session_metadata() if row["session_id"] == "one")
    assert record["project_roots"] == []
    assert adapter.read_session_source(path, "one")["project_roots"] == []


def test_selected_source_keeps_legacy_sync_helper_matching(tmp_path):
    root = tmp_path / "project"
    brain = tmp_path / "brain"
    path = _transcript(brain, "legacy", [{
        "type": "PLANNER_RESPONSE", "tool_calls": [{"args": {"Cwd": str(root)}}],
    }])
    adapter = AntigravityAdapter(None, brain_dir=brain, project_root=root)
    assert [row["session_id"] for row in adapter.list_sessions()] == ["legacy"]
    record, = adapter.list_session_metadata()
    assert record["metadata_status"] == "unknown"
    assert adapter.read_session_source(path, "legacy")["project_roots"] == []


def test_metadata_prefers_full_known_transcript_and_reports_unreadable(tmp_path, monkeypatch):
    adapter = AntigravityAdapter(None, brain_dir=tmp_path / "brain")
    path = _transcript(adapter.brain_dir, "one", [{"cwd": str(tmp_path / "project")}])
    _write(path.with_name("transcript.jsonl"), [{"cwd": str(tmp_path / "wrong")}])
    _write(path.with_name("transcript_backup.jsonl"), [{"cwd": str(tmp_path / "wrong")}])
    record, = adapter.list_session_metadata()
    assert record["path"] == path
    issues = []

    def unreadable(*args, **kwargs):
        raise PermissionError("synthetic unreadable header")

    monkeypatch.setattr(module, "read_jsonl_metadata", unreadable)
    assert adapter.list_session_metadata(issues=issues) == []
    assert issues[0]["code"] == "session_metadata_unreadable"
    assert issues[0]["path"] == str(path)


@pytest.mark.parametrize("root", ["relative/workspace", "vscode-remote://server/work"])
def test_nonlocal_metadata_is_unknown(tmp_path, root):
    adapter, _, history, _ = _cli(tmp_path)
    _write(history, [{"conversationId": "one", "workspace": root, "display": "one"}])
    record, = adapter.list_session_metadata()
    assert record["project_roots"] == [root]
    assert record["metadata_status"] == "unknown"
    assert "cwd" not in record


def test_native_aliases_preserve_roots_without_false_conflicts(tmp_path):
    adapter, _, history, root = _cli(tmp_path)
    alias = str(root / ".." / root.name)
    _write(history, [{
        "conversationId": "one", "workspace": str(root), "cwd": alias, "display": "one",
    }])
    record, = adapter.list_session_metadata()
    assert record["project_roots"] == [str(root)]
    assert record["metadata_status"] == "available"
    assert ownership_for(adapter.read_session_source(history, "one")["project_roots"], root) == "project"


def _stamps(record):
    return [(path, path.stat().st_mtime_ns, path.stat().st_size)
            for path in record["metadata_paths"]]


def _unchanged(stamps):
    return all(path.exists() and (path.stat().st_mtime_ns, path.stat().st_size) == (mtime, size)
               for path, mtime, size in stamps)


def test_history_dependencies_invalidate_preview_when_attachment_changes(tmp_path):
    adapter, cli, history, root = _cli(tmp_path)
    _write(history, [{"conversationId": "one", "cwd": str(root), "display": "one"}])
    transcript = _transcript(cli / "brain", "one", [{"type": "USER_INPUT", "content": "one"}])
    record, = adapter.list_session_metadata()
    assert {history, transcript} <= set(record["metadata_paths"])
    assert all(isinstance(path, Path) and path.exists() for path in record["metadata_paths"])
    stamps = _stamps(record)
    assert _unchanged(stamps)
    _write(transcript, [{"type": "USER_INPUT", "content": "different complete body"}])
    assert not _unchanged(stamps)


@pytest.mark.parametrize("kind", ["history", "brain"])
def test_native_workspace_corroborates_attached_child_cwd_but_not_conflicting_root(tmp_path, kind):
    adapter, cli, history, root = _cli(tmp_path)
    _write(history, [{"conversationId": "one", "workspace": str(root), "display": "one"}])
    path = _transcript(cli / "brain" if kind == "history" else adapter.brain_dir, "one", [
        {"type": "USER_INPUT", "cwd": str(root / "src"), "content": "complete body"},
    ])
    selected = history if kind == "history" else path
    adapter.list_session_metadata()
    assert ownership_for(adapter.read_session_source(selected, "one")["project_roots"], root) == "project"
    _write(path, [{"type": "USER_INPUT", "workspace_root": str(root / "other"), "content": "complete body"}])
    with pytest.raises(ValueError, match="conflicting"):
        adapter.read_session_source(selected, "one")


def test_absent_attachment_creation_and_full_preference_invalidate_preview(tmp_path):
    adapter, cli, history, root = _cli(tmp_path)
    _write(history, [{"conversationId": "one", "cwd": str(root), "display": "one"}])
    record, = adapter.list_session_metadata()
    stamps = _stamps(record)
    full = _transcript(cli / "brain", "one", [{"type": "USER_INPUT", "content": "full"}])
    assert not _unchanged(stamps)
    full.unlink()  # synthetic fixture only
    short = _write(full.with_name("transcript.jsonl"), [{"type": "USER_INPUT", "content": "short"}])
    record, = adapter.list_session_metadata()
    assert short in record["metadata_paths"]
    assert short.parent in record["metadata_paths"]
    stamps = _stamps(record)
    _write(full, [{"type": "USER_INPUT", "content": "new preferred full"}])
    assert not _unchanged(stamps)


def test_brain_dependencies_track_history_membership_changes_and_creation(tmp_path):
    adapter, cli, history, root = _cli(tmp_path)
    cli.mkdir()
    path = _transcript(adapter.brain_dir, "one", [{"type": "USER_INPUT", "cwd": str(root), "content": "one"}])
    record, = adapter.list_session_metadata()
    assert record["path"] == path
    stamps = _stamps(record)
    _write(history, [{"conversationId": "different", "cwd": str(root), "display": "one"}])
    assert not _unchanged(stamps)
    record = next(row for row in adapter.list_session_metadata() if row["session_id"] == "one")
    assert history in record["metadata_paths"]
    stamps = _stamps(record)
    _write(history, [{"conversationId": "one", "cwd": str(tmp_path / "other"), "display": "one"}])
    assert not _unchanged(stamps)
    with pytest.raises(ValueError, match="conflicting"):
        adapter.read_session_source(path, "one")


@pytest.mark.parametrize("kind", ["history", "brain"])
def test_complete_selected_read_matches_sync_pinned_revision(tmp_path, kind):
    async def run():
        adapter, cli, history, root = _cli(tmp_path)
        if kind == "history":
            path = _write(history, [{"conversationId": "one", "cwd": str(root), "display": "one"}])
            _transcript(cli / "brain", "one", [{"type": "USER_INPUT", "content": "complete tail"}])
        else:
            path = _transcript(adapter.brain_dir, "one", [{"type": "USER_INPUT", "cwd": str(root), "content": "complete tail"}])
        adapter.list_session_metadata()
        exported = adapter.read_session_source(path, "one")
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter.backend = backend
            adapter.project_root = str(root)
            result = await adapter.sync_session(path, "one", "project")
            assert backend.transcript_store.reconstruct_raw(result.source.id) == exported["raw_bytes"]
            assert backend.transcript_store.reconstruct(result.source.id) == exported["source_text"]
            assert result.source.source_uri == exported["source_uri"]
            assert result.action == "ingested"
        finally:
            await backend.close()
    asyncio.run(run())
