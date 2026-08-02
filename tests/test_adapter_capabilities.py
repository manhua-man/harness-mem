from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import harness_mem.adapters.capabilities as capabilities_module
from harness_mem.adapters import AdapterRegistry
from harness_mem.core.schemas.transcript import TranscriptSource


@pytest.mark.parametrize(
    ("host", "capture_mode", "native_cleanup_mode"),
    [
        ("claude-code", "file", "file"),
        ("codex", "file", "file"),
        ("cursor", "file", "file"),
        ("grok", "file", "file"),
        ("hermes", "mixed", "source_dependent"),
        ("opencode", "shared_container", "unsupported"),
        ("antigravity", "mixed", "source_dependent"),
    ],
)
def test_registry_enumerates_seven_host_capability_rows(
    host: str,
    capture_mode: str,
    native_cleanup_mode: str,
) -> None:
    rows = AdapterRegistry.list_capabilities()

    assert len(rows) == 7
    assert set(rows) == {
        "claude-code",
        "codex",
        "cursor",
        "grok",
        "hermes",
        "opencode",
        "antigravity",
    }
    assert rows[host].to_dict() == {
        "capture_mode": capture_mode,
        "native_cleanup_mode": native_cleanup_mode,
    }


def test_codex_archive_remains_a_client_alias_not_an_eighth_host() -> None:
    assert "codex-archive" in AdapterRegistry.list()
    assert "codex-archive" not in AdapterRegistry.list_capabilities()
    assert AdapterRegistry.capabilities("codex-archive") == AdapterRegistry.capabilities(
        "codex"
    )


def test_registry_cleanup_delegates_to_existing_cleanup_implementation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    calls: list[tuple[str, int]] = []

    def fake_cleanup(source: TranscriptSource, *, quiet_seconds: int = 60) -> dict:
        calls.append((source.client, quiet_seconds))
        return {"status": "deleted"}

    monkeypatch.setattr(capabilities_module, "cleanup_native_source", fake_cleanup)
    source = _shared_source(
        tmp_path / "rollout.jsonl",
        client="codex",
        source_kind="codex-current",
        fragment="",
    )

    result = AdapterRegistry.cleanup_native_source(source, quiet_seconds=12)

    assert result == {"status": "deleted"}
    assert calls == [("codex", 12)]


@pytest.mark.parametrize(
    ("client", "source_kind", "fragment"),
    [
        ("opencode", "sqlite-session-export", "session=one"),
        ("hermes", "sqlite-session-export", "session=one"),
        (
            "antigravity",
            "antigravity-cli-session-export",
            "conversation=one",
        ),
    ],
)
def test_shared_containers_report_unsupported_without_deleting_container(
    tmp_path: Path,
    client: str,
    source_kind: str,
    fragment: str,
) -> None:
    container = tmp_path / ("state.db" if "sqlite" in source_kind else "history.jsonl")
    content = b"shared container\n"
    container.write_bytes(content)
    source = _shared_source(
        container,
        client=client,
        source_kind=source_kind,
        fragment=fragment,
    )

    result = AdapterRegistry.cleanup_native_source(source, quiet_seconds=0)

    assert result["status"] == "unsupported"
    assert result["reason_codes"] == [
        "shared_source_requires_transactional_cleanup"
    ]
    assert container.read_bytes() == content


def _shared_source(
    container: Path,
    *,
    client: str,
    source_kind: str,
    fragment: str,
) -> TranscriptSource:
    content = container.read_bytes() if container.exists() else b""
    digest = hashlib.sha256(content).hexdigest()
    source_uri = container.absolute().as_uri()
    if fragment:
        source_uri = f"{source_uri}#{fragment}"
    return TranscriptSource(
        id=f"source-{client}",
        project_name="demo",
        project_root=str(container.parent),
        client=client,
        session_id="one",
        source_kind=source_kind,
        source_uri=source_uri,
        source_revision=f"sha256:{digest}",
        raw_sha256=digest,
        normalized_sha256=digest,
        raw_size_bytes=len(content),
        normalized_size_bytes=len(content),
        metadata={"native_source_uri": source_uri},
    )
