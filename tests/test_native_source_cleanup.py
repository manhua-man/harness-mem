from __future__ import annotations

import hashlib
import asyncio
import json
import os
import time
from pathlib import Path

import pytest

import harness_mem.native_source_cleanup as native_cleanup_module
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.core.schemas.observation import Observation
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.native_source_cleanup import (
    apply_native_source_cleanup,
    cleanup_native_source,
    plan_native_source_cleanup,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _write_old(path: Path, content: bytes = b"native transcript\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    old = time.time() - 300
    os.utime(path, (old, old))
    return path


def _source(
    path: Path,
    root: Path,
    *,
    client: str,
    session_id: str,
    source_kind: str,
) -> TranscriptSource:
    content = path.read_bytes() if path.exists() and path.is_file() else b""
    stat_result = path.stat() if path.exists() else None
    digest = hashlib.sha256(content).hexdigest()
    return TranscriptSource(
        id=f"source-{session_id}",
        project_name="demo",
        project_root=str(root / "workspace"),
        client=client,
        session_id=session_id,
        source_kind=source_kind,
        source_uri=path.absolute().as_uri(),
        source_revision=f"sha256:{digest}",
        raw_sha256=digest,
        normalized_sha256=digest,
        raw_size_bytes=len(content),
        normalized_size_bytes=len(content),
        mtime_ns=stat_result.st_mtime_ns if stat_result is not None else None,
        metadata={
            "native_source_uri": path.absolute().as_uri(),
            "native_input_sha256": digest,
            "native_cleanup_descriptor": {
                "version": 1,
                "allowed_root_uris": [root.absolute().as_uri()],
            },
        },
    )


def test_claude_cleanup_deletes_transcript_and_session_sidecars(tmp_path: Path) -> None:
    root = tmp_path / ".claude" / "projects"
    file_history_root = tmp_path / ".claude" / "file-history"
    session_id = "11111111-1111-4111-8111-111111111111"
    source_path = _write_old(root / "project" / f"{session_id}.jsonl")
    sidecar = source_path.with_suffix("") / "tool-results" / "result.txt"
    _write_old(sidecar, b"private tool output")
    file_history = _write_old(file_history_root / session_id / "snapshot@v1", b"old file")
    source = _source(
        source_path,
        root,
        client="claude-code",
        session_id=session_id,
        source_kind="jsonl",
    )
    source.metadata["native_cleanup_descriptor"]["allowed_root_uris"].append(
        file_history_root.absolute().as_uri()
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert result["counts"]["deleted"] == 3
    assert not source_path.exists()
    assert not source_path.with_suffix("").exists()
    assert not file_history.parent.exists()


@pytest.mark.parametrize("client", ["codex", "codex-archive"])
def test_codex_cleanup_deletes_only_the_verified_rollout(
    tmp_path: Path,
    client: str,
) -> None:
    root = tmp_path / ("sessions" if client == "codex" else "archived_sessions")
    session_id = "019f0000-0000-7000-8000-000000000001"
    source_path = _write_old(root / "2026" / f"rollout-2026-01-01-{session_id}.jsonl")
    neighbor = _write_old(root / "2026" / "rollout-neighbor.jsonl", b"neighbor")
    source = _source(
        source_path,
        root,
        client=client,
        session_id=session_id,
        source_kind="codex-current" if client == "codex" else "jsonl",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert not source_path.exists()
    assert neighbor.read_bytes() == b"neighbor"


def test_cursor_cleanup_removes_only_exact_agent_transcript_bundle(tmp_path: Path) -> None:
    root = tmp_path / ".cursor" / "projects"
    session_id = "cursor-session"
    bundle = root / "project" / "agent-transcripts" / session_id
    source_path = _write_old(bundle / f"{session_id}.jsonl")
    _write_old(bundle / "sidecar.bin", b"sidecar")
    neighbor = _write_old(
        root / "project" / "agent-transcripts" / "neighbor" / "neighbor.jsonl",
        b"neighbor",
    )
    source = _source(
        source_path,
        root,
        client="cursor",
        session_id=session_id,
        source_kind="jsonl",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert not bundle.exists()
    assert neighbor.exists()


def test_grok_cleanup_removes_exact_session_directory(tmp_path: Path) -> None:
    root = tmp_path / ".grok" / "sessions"
    session_id = "grok-session"
    bundle = root / "encoded-project" / session_id
    source_path = _write_old(bundle / "chat_history.jsonl")
    _write_old(bundle / "events.jsonl", b"event")
    neighbor = _write_old(
        root / "encoded-project" / "neighbor" / "chat_history.jsonl",
        b"neighbor",
    )
    source = _source(
        source_path,
        root,
        client="grok",
        session_id=session_id,
        source_kind="jsonl",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert not bundle.exists()
    assert neighbor.exists()


def test_hermes_json_cleanup_removes_strict_request_dump_sidecars(tmp_path: Path) -> None:
    root = tmp_path / ".hermes" / "sessions"
    session_id = "session_20260728_abcd"
    source_path = _write_old(root / f"{session_id}.json")
    matching = _write_old(root / "request_dump_20260728_abcd_20260728_010101.json")
    neighbor = _write_old(root / "request_dump_20260728_other_20260728_010101.json")
    source = _source(
        source_path,
        root,
        client="hermes",
        session_id=session_id,
        source_kind="json",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert not source_path.exists()
    assert not matching.exists()
    assert neighbor.exists()


def test_antigravity_brain_cleanup_removes_exact_bundle_and_companions(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".gemini" / "antigravity"
    session_id = "22222222-2222-4222-8222-222222222222"
    bundle = root / "brain" / session_id
    source_path = _write_old(
        bundle / ".system_generated" / "logs" / "transcript_full.jsonl"
    )
    annotation = _write_old(root / "annotations" / f"{session_id}.pbtxt", b"note")
    conversation = _write_old(root / "conversations" / f"{session_id}.db", b"db")
    neighbor = _write_old(root / "conversations" / "neighbor.db", b"neighbor")
    source = _source(
        source_path,
        root,
        client="antigravity",
        session_id=session_id,
        source_kind="brain-jsonl",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "deleted"
    assert not bundle.exists()
    assert not annotation.exists()
    assert not conversation.exists()
    assert neighbor.exists()


@pytest.mark.parametrize(
    ("client", "source_kind", "fragment"),
    [
        ("hermes", "sqlite-session-export", "#session=one"),
        ("opencode", "sqlite-session-export", "#session=one"),
        ("antigravity", "antigravity-cli-session-export", "#conversation=one"),
    ],
)
def test_shared_sources_are_explicitly_unsupported_without_mutation(
    tmp_path: Path,
    client: str,
    source_kind: str,
    fragment: str,
) -> None:
    root = tmp_path / client
    container = _write_old(root / ("history.jsonl" if "history" in source_kind else "state.db"))
    source = _source(
        container,
        root,
        client=client,
        session_id="one",
        source_kind=source_kind,
    )
    source.source_uri += fragment
    source.metadata["native_source_uri"] = source.source_uri
    before = container.read_bytes()

    result = cleanup_native_source(source, quiet_seconds=0)

    assert result["status"] == "unsupported"
    assert result["success"] is False
    assert result["reason_codes"] == ["shared_source_requires_transactional_cleanup"]
    assert container.read_bytes() == before


def test_quiet_gate_retains_recent_source(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    session_id = "019f0000-0000-7000-8000-000000000002"
    source_path = root / f"rollout-{session_id}.jsonl"
    source_path.parent.mkdir(parents=True)
    source_path.write_bytes(b"still active")
    source = _source(
        source_path,
        root,
        client="codex",
        session_id=session_id,
        source_kind="codex-current",
    )

    result = cleanup_native_source(source, quiet_seconds=60)

    assert result["status"] == "retained"
    assert result["reason_codes"] == ["native_source_not_quiet"]
    assert source_path.exists()


def test_compare_and_swap_refuses_change_after_preview(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    session_id = "019f0000-0000-7000-8000-000000000003"
    source_path = _write_old(root / f"rollout-{session_id}.jsonl")
    source = _source(
        source_path,
        root,
        client="codex",
        session_id=session_id,
        source_kind="codex-current",
    )
    plan = plan_native_source_cleanup(source, quiet_seconds=60)
    source_path.write_bytes(b"new append")

    result = apply_native_source_cleanup(plan)

    assert result["status"] == "retained"
    assert result["reason_codes"] == ["native_source_changed_after_claim"]
    assert source_path.read_bytes() == b"new append"


def test_atomic_claim_preserves_bytes_written_during_apply(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "sessions"
    session_id = "019f0000-0000-7000-8000-000000000007"
    source_path = _write_old(root / f"rollout-{session_id}.jsonl")
    source = _source(
        source_path,
        root,
        client="codex",
        session_id=session_id,
        source_kind="codex-current",
    )
    plan = plan_native_source_cleanup(source, quiet_seconds=60)
    original_claim = native_cleanup_module._claim_action
    injected = False

    def claim_then_append(plan_arg, action):
        nonlocal injected
        claim = original_claim(plan_arg, action)
        if claim is not None and not injected:
            claim.write_bytes(b"host appended after atomic claim")
            injected = True
        return claim

    monkeypatch.setattr(native_cleanup_module, "_claim_action", claim_then_append)

    result = apply_native_source_cleanup(plan)

    assert result["status"] == "retained"
    assert result["reason_codes"] == ["native_source_changed_after_claim"]
    assert source_path.read_bytes() == b"host appended after atomic claim"


@pytest.mark.parametrize("late_change", ["add", "modify"])
def test_directory_manifest_preserves_late_sidecar_changes(
    tmp_path: Path,
    late_change: str,
) -> None:
    root = tmp_path / ".cursor" / "projects"
    session_id = f"late-{late_change}"
    bundle = root / "project" / "agent-transcripts" / session_id
    source_path = _write_old(bundle / f"{session_id}.jsonl")
    sidecar = _write_old(bundle / "sidecar.bin", b"preview sidecar")
    source = _source(
        source_path,
        root,
        client="cursor",
        session_id=session_id,
        source_kind="jsonl",
    )
    plan = plan_native_source_cleanup(source, quiet_seconds=60)
    if late_change == "add":
        late = bundle / "late.bin"
        late.write_bytes(b"late content")
    else:
        late = sidecar
        late.write_bytes(b"modified after preview")

    result = apply_native_source_cleanup(plan)

    assert result["status"] == "retained"
    assert result["reason_codes"] == ["native_action_changed_after_preview"]
    assert source_path.exists()
    assert late.read_bytes() in {b"late content", b"modified after preview"}


def test_partial_delete_resumes_from_deterministic_claim(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / ".claude" / "projects"
    session_id = "33333333-3333-4333-8333-333333333333"
    source_path = _write_old(root / "project" / f"{session_id}.jsonl")
    sidecar = _write_old(
        source_path.with_suffix("") / "tool-results" / "result.txt",
        b"sidecar",
    )
    source = _source(
        source_path,
        root,
        client="claude-code",
        session_id=session_id,
        source_kind="jsonl",
    )
    plan = plan_native_source_cleanup(source, quiet_seconds=60)
    original_remove = native_cleanup_module._remove_directory_tree

    def fail_once(_path: Path) -> None:
        raise OSError("injected failure")

    monkeypatch.setattr(native_cleanup_module, "_remove_directory_tree", fail_once)
    first = apply_native_source_cleanup(plan)
    monkeypatch.setattr(native_cleanup_module, "_remove_directory_tree", original_remove)
    second = apply_native_source_cleanup(plan)

    assert first["status"] == "partial_failure"
    assert second["status"] == "deleted"
    assert not source_path.exists()
    assert not sidecar.parent.parent.exists()


def test_outside_allowed_root_and_symlink_fail_closed(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = _write_old(
        tmp_path / "outside" / "rollout-019f0000-0000-7000-8000-000000000004.jsonl"
    )
    source = _source(
        outside,
        allowed,
        client="codex",
        session_id="019f0000-0000-7000-8000-000000000004",
        source_kind="codex-current",
    )

    outside_result = cleanup_native_source(source, quiet_seconds=0)

    assert outside_result["status"] == "unsupported"
    assert outside.exists()

    target = _write_old(allowed / "real.jsonl")
    link = allowed / "rollout-019f0000-0000-7000-8000-000000000005.jsonl"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available on this platform")
    linked = _source(
        link,
        allowed,
        client="codex",
        session_id="019f0000-0000-7000-8000-000000000005",
        source_kind="codex-current",
    )

    link_result = cleanup_native_source(linked, quiet_seconds=0)

    assert link_result["status"] == "unsupported"
    assert target.exists()


def test_cleanup_receipt_never_exposes_path_or_content(tmp_path: Path) -> None:
    root = tmp_path / "sessions"
    session_id = "019f0000-0000-7000-8000-000000000006"
    secret = "do-not-leak-secret"
    source_path = _write_old(
        root / f"rollout-{session_id}.jsonl",
        secret.encode("utf-8"),
    )
    source = _source(
        source_path,
        root,
        client="codex",
        session_id=session_id,
        source_kind="codex-current",
    )

    result = cleanup_native_source(source, quiet_seconds=0)
    encoded = json.dumps(result, sort_keys=True)

    assert result["status"] == "deleted"
    assert str(tmp_path) not in encoded
    assert secret not in encoded
    assert "file:" not in encoded
    assert len(result["locator_sha256"]) == 64


def test_snapshot_records_native_input_digest_for_cleanup_cas(tmp_path: Path) -> None:
    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            native = b"before <private>secret</private> after\n"
            result = await persist_session_snapshot(
                backend,
                Observation(
                    session_id="session-one",
                    client="codex",
                    raw_content="rendered",
                    content_type="transcript",
                ),
                project_name="demo",
                project_root=str(tmp_path),
                client="codex",
                session_id="session-one",
                source_kind="codex-current",
                source_uri=(tmp_path / "rollout-session-one.jsonl").as_uri(),
                source_text=native.decode("utf-8"),
                raw_bytes=native,
            )

            assert result.source is not None
            assert result.source.metadata["native_input_sha256"] == hashlib.sha256(
                native
            ).hexdigest()
        finally:
            await backend.close()

    asyncio.run(exercise())
