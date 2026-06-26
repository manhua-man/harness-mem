from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

SESSION_DISTILL_ROOT = Path(__file__).resolve().parents[1] / "tools" / "session-distill"
sys.path.insert(0, str(SESSION_DISTILL_ROOT))

from lib.adapters import (  # noqa: E402
    ClaudeSourceAdapter,
    CodexSourceAdapter,
    GenericJsonlSourceAdapter,
    exclude_self_sessions,
)
from lib.harness_mem_export import build_suggest_calls  # noqa: E402
from lib.models import CandidateDraft, Packet, PacketAudit, SessionSource  # noqa: E402
from lib.packet import packet_from_source  # noqa: E402


def _write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("adapter_type", "records", "client", "expected_text"),
    [
        (
            ClaudeSourceAdapter,
            [
                {
                    "type": "user",
                    "metadata": {"project_name": "demo"},
                    "message": {"content": "Summarize the adapter boundary."},
                },
                {
                    "type": "assistant",
                    "message": {
                        "content": [
                            {"type": "text", "text": "Use SourceAdapter for packet input."}
                        ]
                    },
                },
            ],
            "claude",
            "Use SourceAdapter for packet input.",
        ),
        (
            CodexSourceAdapter,
            [
                {
                    "role": "user",
                    "content": "Index the Codex archive.",
                    "project_name": "demo",
                    "cwd": "F:/AIInfra/harness-mem",
                },
                {
                    "payload": {
                        "role": "assistant",
                        "content": "Codex packetization uses the same interface.",
                        "cwd": "F:/AIInfra/harness-mem",
                    }
                },
            ],
            "codex",
            "Codex packetization uses the same interface.",
        ),
        (
            GenericJsonlSourceAdapter,
            [
                {
                    "role": "user",
                    "content": "Read a generic agent trace.",
                    "metadata": {"project_name": "demo"},
                },
                {
                    "event": "assistant_message",
                    "text": "Generic traces use role/content style records.",
                },
            ],
            "generic",
            "Generic traces use role/content style records.",
        ),
    ],
)
def test_source_adapter_unified_interface_across_client_fixtures(
    tmp_path: Path,
    adapter_type: type[ClaudeSourceAdapter | CodexSourceAdapter | GenericJsonlSourceAdapter],
    records: list[dict[str, Any]],
    client: str,
    expected_text: str,
) -> None:
    source_path = tmp_path / "session-fixture.jsonl"
    _write_jsonl(source_path, records)

    adapter = adapter_type(tmp_path)
    sources = adapter.discover(project="demo")
    assert len(sources) == 1
    assert sources[0].client == client

    packet = packet_from_source(adapter, sources[0])

    assert packet is not None
    assert packet.session_id == "session-fixture"
    assert packet.project_name == "demo"
    assert packet.audit.coverage == "high"
    assert packet.metadata["client"] == client
    assert expected_text in packet.text


def test_packetizer_excludes_self_session_sources(tmp_path: Path) -> None:
    self_path = tmp_path / "active-session.jsonl"
    other_path = tmp_path / "older-session.jsonl"
    _write_jsonl(self_path, [{"role": "user", "content": "Current distill turn."}])
    _write_jsonl(other_path, [{"role": "user", "content": "Older useful turn."}])

    adapter = GenericJsonlSourceAdapter(tmp_path)
    sources = [
        SessionSource(session_id="active-session", path=self_path, client="generic"),
        SessionSource(session_id="older-session", path=other_path, client="generic"),
    ]

    filtered = exclude_self_sessions(sources, current_session_id="active-session")
    packet = packet_from_source(
        adapter,
        sources[0],
        current_session_id="active-session",
    )

    assert [source.session_id for source in filtered] == ["older-session"]
    assert packet is None


def test_distill_self_session_not_promoted() -> None:
    packet = Packet(
        session_id="older-session",
        project_name="demo",
        audit=PacketAudit(coverage="high"),
    )
    drafts = [
        CandidateDraft(
            kind="memory_entry",
            category="decision",
            content="This active turn should not be promoted.",
            source_session_id="active-session",
        ),
        CandidateDraft(
            kind="memory_entry",
            category="decision",
            content="An older reviewed session may be suggested.",
            source_session_id="older-session",
        ),
    ]

    calls = build_suggest_calls(
        drafts,
        packet,
        current_session_id="active-session",
    )

    assert len(calls) == 1
    assert calls[0].arguments["source"] == "session-distill:older-session"
