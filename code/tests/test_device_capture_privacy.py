"""Fictional device captures: privacy applies to every retained representation."""
from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

import pytest

from harness_mem.adapters.antigravity.adapter import AntigravityAdapter, _history_export
from harness_mem.adapters.snapshot import persist_inspected_session, persist_session_snapshot
from harness_mem.adapters.source_inspection import inspect_native_source
from harness_mem.capture_policy import (
    PRIVATE_REDACTION,
    decide_capture,
    redact_private_bytes,
    source_capture_policy,
)
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import sha256_bytes, transcript_bytes_revision


FORMAT = "harness-mem-antigravity-history-v1"
SECRET = 'fictional-secret-秘密-"quoted"'


@pytest.fixture(autouse=True)
def fictional_home(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "home")


def _wrapper(transcript: bytes) -> bytes:
    return (json.dumps({
        "format": FORMAT, "conversation_id": "selected",
        "transcript_name": "transcript_full.jsonl",
        "transcript_raw_base64": base64.b64encode(transcript).decode("ascii"),
    }) + "\n").encode()


def _decoded(raw: bytes) -> bytes:
    return base64.b64decode(json.loads(raw.splitlines()[0])["transcript_raw_base64"], validate=True)


@pytest.mark.parametrize("project_bound", [False, True])
@pytest.mark.parametrize("private_tags", [False, True])
def test_selected_capture_redacts_wrapper_and_attachment_before_persistence(
    tmp_path, project_bound, private_tags,
):
    root = tmp_path / "project"
    root.mkdir()
    cli = tmp_path / "cli"
    transcript = cli / "brain" / "selected" / ".system_generated" / "logs" / "transcript_full.jsonl"
    transcript.parent.mkdir(parents=True)
    native_record = {"type": "USER_INPUT", "content": f'public <PRIVATE note="fixture">{SECRET}</PRIVATE> tail'}
    # Escaped delimiters and Unicode survive a literal byte regex.
    native = b"\xef\xbb\xbf" + json.dumps(native_record, ensure_ascii=True).replace("<", r"\u003c").encode() + b"\r\n"
    transcript.write_bytes(native)
    history = cli / "history.jsonl"
    history_record = {
        "conversationId": "selected", "workspace": str(root),
        "display": f"public <private>{SECRET}</private> tail",
        "nested": [{"text": f"nested <private>{SECRET}</private> tail"}],
    }
    history.write_text(json.dumps(history_record) + "\n", encoding="utf-8")
    adapter = AntigravityAdapter(None, cli_root=cli, home_dir=tmp_path / "home")
    record = {"path": history, "session_id": "selected", "metadata_paths": [transcript]}
    exported = _history_export([history_record], transcript_path=transcript)
    config = MergedConfig(capture_private_tags=private_tags)
    selected = inspect_native_source(
        adapter, "antigravity", record, project_root=root if project_bound else None, config=config,
    )
    assert selected.ownership == ("project" if project_bound else "source")
    assert selected.readability == "readable"
    assert selected.project_roots == [str(root)]
    assert selected.native_input_bytes == exported["raw_bytes"]
    assert selected.captured_bytes is not None
    assert selected.native_digest == sha256_bytes(selected.captured_bytes)
    decoded = _decoded(selected.captured_bytes)
    attached_record = json.loads(decoded.decode("utf-8-sig"))
    assert attached_record["type"] == native_record["type"]
    if private_tags:
        assert attached_record["content"] == f"public {PRIVATE_REDACTION} tail"
        saved_history = json.loads(selected.captured_bytes.splitlines()[1])["record"]
        assert saved_history["workspace"] == str(root)
        assert saved_history["nested"][0]["text"] == f"nested {PRIVATE_REDACTION} tail"
        assert SECRET not in json.dumps(saved_history, ensure_ascii=False)
        assert redact_private_bytes(selected.captured_bytes) == (selected.captured_bytes, 0)
    else:
        assert selected.captured_bytes == exported["raw_bytes"]
        assert decoded == native

    async def run():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            result = await persist_inspected_session(
                backend, selected, project_name="fixture", project_root=str(root) if project_bound else "",
                capture_config=config,
            )
            assert result.source is not None
            source = result.source
            assert source.raw_sha256 == selected.native_digest
            assert source.source_revision == transcript_bytes_revision(selected.captured_bytes)
            assert source.metadata["native_input_sha256"] == sha256_bytes(exported["raw_bytes"])
            stored_raw = backend.transcript_store.reconstruct_raw(source.id)
            assert stored_raw == selected.captured_bytes
            stored_text = backend.transcript_store.reconstruct(source.id)
            observation = await backend.verbatim_store.get(result.observation_id)
            assert observation is not None
            assert (SECRET in json.loads(_decoded(stored_raw).decode("utf-8-sig"))["content"]) is not private_tags
            if private_tags:
                for text in (stored_text, observation.raw_content):
                    assert SECRET not in text
                    assert PRIVATE_REDACTION in text
        finally:
            await backend.close()

    asyncio.run(run())
    assert transcript.read_bytes() == native
    assert json.loads(history.read_text()) == history_record


@pytest.mark.parametrize("native", [b"", b'\xef\xbb\xbf{"type":"USER_INPUT","content":"public"}\r\n'])
def test_public_wrapper_keeps_exact_bytes_and_empty_attachment(native):
    wrapper = _wrapper(native)
    assert redact_private_bytes(wrapper) == (wrapper, 0)


@pytest.mark.parametrize("container", ["jsonl", "pretty-json", "cursor-values"])
def test_escaped_native_private_delimiters_are_redacted_after_decoding(container):
    record = {"role": "user", "content": f"public <private>{SECRET}</private> tail"}
    if container == "cursor-values":
        encoded = json.dumps({"bubbleId": "user", "type": 1, "text": record["content"]}).replace("<", r"\u003c")
        raw = json.dumps({"format": "cursorDiskKV-v1", "records": [["bubbleId:selected:user", encoded]]}).encode()
    elif container == "pretty-json":
        raw = json.dumps({"messages": [record]}, indent=2).replace("<", r"\u003c").encode()
    else:
        raw = (json.dumps(record).replace("<", r"\u003c") + "\r\n").encode()
    captured, count = redact_private_bytes(raw)
    assert count == 1
    restored = json.loads(captured)
    if container == "cursor-values":
        text = json.loads(restored["records"][0][1])["text"]
    elif container == "pretty-json":
        text = restored["messages"][0]["content"]
    else:
        text = restored["content"]
    assert text == f"public {PRIVATE_REDACTION} tail"
    assert redact_private_bytes(captured) == (captured, 0)


@pytest.mark.parametrize("encoded", [
    None, 7, ["unknown"], "%%%fictional-secret%%%", "non-ascii-秘密",
    base64.b64encode(b"\xff").decode(),
    base64.b64encode(b"\x1f\x8bcompressed fixture").decode(),
    base64.b64encode(b'{"type":"USER_INPUT"}'.decode().encode("utf-16")).decode(),
    base64.b64encode(b"not JSON <private>fictional-secret</private>").decode(),
    base64.b64encode(base64.b64encode(b'{"content":"<private>fictional-secret</private>"}')).decode(),
])
def test_corrupt_or_non_native_encoding_fails_before_any_ledger_write(tmp_path, encoded):
    header = json.loads(_wrapper(b""))
    header["transcript_raw_base64"] = encoded
    raw = (json.dumps(header) + "\n").encode()

    async def run():
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            with pytest.raises(ValueError) as error:
                await persist_session_snapshot(
                    backend, Observation(session_id="selected", client="antigravity", raw_content="public"),
                    project_name="fixture", project_root="", client="antigravity", session_id="selected",
                    source_kind="native-session-export", source_uri="file:///fictional/history.jsonl",
                    source_text="public", raw_bytes=raw, capture_config=MergedConfig(),
                )
            assert "fictional-secret" not in str(error.value)
            assert backend.transcript_store.list_sources(project_name="fixture") == []
            assert backend.transcript_store.list_distill_jobs(project_name="fixture") == []
            assert await backend.verbatim_store.list(project_name="fixture") == []
        finally:
            await backend.close()

    asyncio.run(run())


@pytest.mark.parametrize("change", ["version", "field", "case", "nested", "duplicate", "truncated"])
def test_unknown_or_ambiguous_wrapper_encodings_fail_safe(change):
    header = json.loads(_wrapper(b'{"type":"USER_INPUT","content":"public"}'))
    if change == "version":
        header["format"] = "harness-mem-antigravity-history-v2"
    elif change == "field":
        header["transcript_raw_base85"] = header.pop("transcript_raw_base64")
    elif change == "case":
        header["TRANSCRIPT_RAW_BASE64"] = header.pop("transcript_raw_base64")
    elif change == "nested":
        header["nested"] = {"transcript_raw_base64": header["transcript_raw_base64"]}
    raw = json.dumps(header).encode()
    if change == "duplicate":
        raw = raw[:-1] + b',"transcript_raw_base64":"unknown"}'
    elif change == "truncated":
        raw = raw[:-1]
    with pytest.raises(ValueError):
        redact_private_bytes(raw)


def test_only_known_attachment_is_decoded_once_and_json_depth_is_bounded(monkeypatch):
    decode = base64.b64decode
    calls = []

    def counted(value, **kwargs):
        calls.append(value)
        return decode(value, **kwargs)

    monkeypatch.setattr(base64, "b64decode", counted)
    opaque = base64.b64encode(b"arbitrary encoded content").decode()
    native = json.dumps({"type": "USER_INPUT", "content": opaque}).encode()
    assert redact_private_bytes(_wrapper(native)) == (_wrapper(native), 0)
    assert calls == [base64.b64encode(native).decode()]
    calls.clear()
    assert redact_private_bytes(opaque.encode()) == (opaque.encode(), 0)
    assert calls == []
    deep = b'{"content":' + b"[" * 80 + b'"public"' + b"]" * 80 + b"}"
    with pytest.raises(ValueError):
        redact_private_bytes(_wrapper(deep))
    calls.clear()
    with pytest.raises(ValueError):
        redact_private_bytes(_wrapper(_wrapper(native)))
    assert calls == [base64.b64encode(_wrapper(native)).decode()]


@pytest.mark.parametrize("disabled", ["user", "first", "second", None])
def test_device_policy_intersects_user_and_all_existing_local_roots(tmp_path, disabled):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    configs = {
        None: MergedConfig(capture_enabled=disabled != "user", capture_private_tags=True,
                           capture_ignore_clients=("CURSOR",)),
        first: MergedConfig(capture_enabled=disabled != "first", capture_private_tags=False,
                            capture_ignore_session_ids=("private-session",)),
        second: MergedConfig(capture_enabled=disabled != "second", capture_private_tags=False,
                             capture_ignore_source_globs=("*secret*",)),
    }
    loaded = []

    def loader(root):
        loaded.append(root)
        return configs[root]

    config = source_capture_policy([
        str(first), str(first), str(second), str(tmp_path / "missing"),
        "relative", "vscode-remote://fictional/root", "//fictional/share",
    ], config_loader=loader)
    assert loaded == [None, first, second]
    assert config.capture_enabled is (disabled is None)
    assert config.capture_private_tags is True
    assert config.capture_ignore_clients == ("CURSOR",)
    assert config.capture_ignore_session_ids == ("private-session",)
    assert config.capture_ignore_source_globs == ("*secret*",)
    if disabled is None:
        for client, session, uri, reason in [
            ("cursor", "public", "file:///public", "client_ignored"),
            ("codex", "private-session", "file:///public", "session_ignored"),
            ("codex", "public", "file:///SECRET", "source_ignored"),
        ]:
            assert decide_capture(config, client=client, session_id=session, source_uri=uri).reason == reason


def test_unknown_roots_use_user_policy_and_unreadable_local_policy_is_not_bypassed(tmp_path):
    user = MergedConfig(capture_private_tags=False, capture_ignore_clients=("antigravity",))
    assert source_capture_policy([], config_loader=lambda root: user) == user
    root = tmp_path / "local"
    root.mkdir()

    def loader(path):
        if path is not None:
            raise PermissionError("fictional policy denied")
        return user

    with pytest.raises(PermissionError):
        source_capture_policy([str(root)], config_loader=loader)
