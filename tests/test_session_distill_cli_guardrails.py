from __future__ import annotations

import json
import sys
from pathlib import Path

SESSION_DISTILL_ROOT = Path(__file__).resolve().parents[1] / "tools" / "session-distill"
sys.path.insert(0, str(SESSION_DISTILL_ROOT))

from lib import cli  # noqa: E402
from lib.guardrails import contains_pending_draft, raw_deletion_root  # noqa: E402


def _point_cli_at_tmp(monkeypatch, tmp_path: Path) -> Path:
    distill_dir = tmp_path / "session-distill"
    monkeypatch.setattr(cli, "DISTILL_DIR", distill_dir)
    monkeypatch.setattr(cli, "MANIFEST_FILE", distill_dir / "manifest.json")
    monkeypatch.setattr(cli, "PACKETS_DIR", distill_dir / "packets")
    monkeypatch.setattr(cli, "DISTILLED_DIR", distill_dir / "distilled" / "sessions")
    monkeypatch.setattr(cli, "MEMORY_DRAFTS_DIR", distill_dir / "memory-drafts")
    monkeypatch.setattr(cli, "PRUNED_SOURCES_FILE", distill_dir / "pruned-sources.jsonl")
    return distill_dir


def test_session_distill_cli_does_not_register_artifact_lifecycle_commands() -> None:
    parser = cli.build_parser()
    choices = parser._subparsers._group_actions[0].choices  # type: ignore[attr-defined]

    assert set(choices) == {"run", "status", "list", "help"}
    assert "mark" not in choices
    assert "prune" not in choices


def test_raw_cleanup_requires_guardrail(monkeypatch, tmp_path: Path) -> None:
    _point_cli_at_tmp(monkeypatch, tmp_path)
    raw_path = tmp_path / "outside-raw.jsonl"
    raw_path.write_text('{"role":"user","content":"keep me"}\n', encoding="utf-8")
    monkeypatch.setattr(cli, "CODEX_RAW_ROOTS", (tmp_path / "allowed-raw",))
    session = {
        "session_id": "session-raw",
        "file_path": str(raw_path),
    }

    cli.maybe_delete_raw_source(session, keep_raw=False)

    assert raw_path.exists()
    assert session["raw_retained_reason"] == "outside_codex_raw_roots"
    assert not cli.PRUNED_SOURCES_FILE.exists()


def test_prune_manifest_requires_source_missing_guardrail(monkeypatch, tmp_path: Path) -> None:
    _point_cli_at_tmp(monkeypatch, tmp_path)
    cli.ensure_dirs()
    cli.save_manifest(
        {
            "version": 1,
            "sessions": [
                {
                    "session_id": "session-1",
                    "status": "distilled",
                    "source_missing": True,
                }
            ],
        }
    )

    result = cli.cmd_prune("distilled", source_missing=False, apply=True)
    manifest = json.loads(cli.MANIFEST_FILE.read_text(encoding="utf-8"))

    assert result == 1
    assert len(manifest["sessions"]) == 1


def test_shared_pending_draft_guardrail_scans_nested_payloads() -> None:
    payload = {
        "session": {
            "candidates": [
                {"status": "user_confirmed"},
                {"review": {"readiness": "pending"}},
            ]
        }
    }

    assert contains_pending_draft(payload) is True


def test_shared_raw_deletion_root_guardrail_requires_allowed_root(tmp_path: Path) -> None:
    allowed = tmp_path / "allowed"
    outside = tmp_path / "outside"
    raw_path = allowed / "session.jsonl"
    outside_path = outside / "session.jsonl"
    raw_path.parent.mkdir()
    outside_path.parent.mkdir()
    raw_path.write_text("{}", encoding="utf-8")
    outside_path.write_text("{}", encoding="utf-8")

    assert raw_deletion_root(raw_path, (allowed,)) == allowed
    assert raw_deletion_root(outside_path, (allowed,)) is None
