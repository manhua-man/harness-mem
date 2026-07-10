from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

from harness_mem.commands.integration_cmds import cmd_transcript_evidence
from harness_mem.transcript_evidence import (
    TranscriptEvidence,
    collect_transcript_evidence,
    render_transcript_evidence,
)


def test_collect_transcript_evidence_verifies_grok_project_bucket(
    tmp_path: Path,
) -> None:
    project_root = (tmp_path / "repo").resolve()
    project_root.mkdir()
    home = tmp_path / "home"
    bucket = home / ".grok" / "sessions" / quote(str(project_root), safe="")
    first_session = bucket / "session-1"
    second_session = bucket / "session-2"
    first_session.mkdir(parents=True)
    second_session.mkdir(parents=True)
    (first_session / "chat_history.jsonl").write_text(
        '{"type":"user","content":"hello"}\n',
        encoding="utf-8",
    )
    (second_session / "chat_history.jsonl").write_text(
        '{"type":"assistant","content":"world"}\n',
        encoding="utf-8",
    )

    report = collect_transcript_evidence(
        project_root,
        clients=("grok",),
        home_dir=home,
        sample_limit=1,
    )[0]

    assert report.client == "grok"
    assert report.status == "verified_transcript_path"
    assert report.session_count == 2
    assert len(report.sample_files) == 1
    assert report.sample_files[0].name == "chat_history.jsonl"
    assert report.adapter_available is False


def test_collect_transcript_evidence_keeps_unknown_hosts_unavailable(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    (home / ".hermes").mkdir(parents=True)

    hermes, opencode = collect_transcript_evidence(
        tmp_path,
        clients=("hermes", "opencode"),
        home_dir=home,
    )

    assert hermes.status == "insufficient_evidence"
    assert hermes.adapter_available is False
    assert "no verified transcript path/schema" in hermes.note
    assert opencode.status == "missing"
    assert opencode.adapter_available is False


def test_render_transcript_evidence_reports_adapter_separately(tmp_path: Path) -> None:
    report = TranscriptEvidence(
        client="grok",
        status="verified_transcript_path",
        adapter_available=False,
        roots=(tmp_path / ".grok" / "sessions",),
        session_count=3,
        sample_files=(tmp_path / "chat_history.jsonl",),
        note="Found local transcripts.",
    )

    out = render_transcript_evidence((report,))

    assert "grok: verified_transcript_path | adapter=unavailable" in out
    assert "sessions: 3" in out
    assert "sample:" in out
    assert "Found local transcripts." in out


def test_cmd_transcript_evidence_prints_report(monkeypatch, tmp_path: Path, capsys) -> None:
    calls: list[tuple[Path, tuple[str, ...]]] = []

    def fake_collect(project_root: Path, *, clients):
        calls.append((project_root, tuple(clients)))
        return (
            TranscriptEvidence(
                client="grok",
                status="missing",
                adapter_available=False,
                roots=(tmp_path / ".grok",),
            ),
        )

    monkeypatch.setattr(
        "harness_mem.commands.integration_cmds.collect_transcript_evidence",
        fake_collect,
    )

    assert cmd_transcript_evidence("grok", str(tmp_path)) == 0

    out = capsys.readouterr().out
    assert "Transcript evidence:" in out
    assert "grok: missing | adapter=unavailable" in out
    assert calls == [(tmp_path.resolve(), ("grok",))]
