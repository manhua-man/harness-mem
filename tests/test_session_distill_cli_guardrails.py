from __future__ import annotations

import json
import sys
from pathlib import Path

SESSION_DISTILL_ROOT = Path(__file__).resolve().parents[1] / "tools" / "session-distill"
sys.path.insert(0, str(SESSION_DISTILL_ROOT))

from lib import cli  # noqa: E402


def _point_cli_at_tmp(monkeypatch, tmp_path: Path) -> Path:
    distill_dir = tmp_path / "session-distill"
    monkeypatch.setattr(cli, "DISTILL_DIR", distill_dir)
    monkeypatch.setattr(cli, "MANIFEST_FILE", distill_dir / "manifest.json")
    monkeypatch.setattr(cli, "KNOWLEDGE_FILE", distill_dir / "knowledge-base.md")
    monkeypatch.setattr(cli, "PACKETS_DIR", distill_dir / "packets")
    monkeypatch.setattr(cli, "DISTILLED_DIR", distill_dir / "distilled" / "sessions")
    monkeypatch.setattr(cli, "MEMORY_DRAFTS_DIR", distill_dir / "memory-drafts")
    monkeypatch.setattr(cli, "KB_BACKUPS_DIR", distill_dir / "backups" / "knowledge-base")
    monkeypatch.setattr(cli, "KB_REVIEW_STATE_FILE", distill_dir / "kb-review-state.json")
    monkeypatch.setattr(cli, "PRUNED_SOURCES_FILE", distill_dir / "pruned-sources.jsonl")
    monkeypatch.setattr(cli, "PRD_DISTILLED_DIR", distill_dir / "prd-distilled")
    return distill_dir


def test_prd_sync_dry_run_no_write(monkeypatch, tmp_path: Path) -> None:
    distill_dir = _point_cli_at_tmp(monkeypatch, tmp_path)
    cli.ensure_dirs()
    packet_path = cli.PACKETS_DIR / "session-1.md"
    packet_path.write_text(
        "# Packet\n\nRoadmap decision: keep PRD sync as a candidate artifact.\n",
        encoding="utf-8",
    )
    cli.save_manifest(
        {
            "version": 1,
            "sessions": [
                {
                    "session_id": "session-1",
                    "status": "bundled",
                    "bundle_path": str(packet_path),
                }
            ],
        }
    )

    result = cli.cmd_prd_sync(dry_run=True)

    assert result == 0
    assert not (distill_dir / "prd-distilled").exists()


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
