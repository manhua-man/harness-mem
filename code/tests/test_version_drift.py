from __future__ import annotations

import json
from pathlib import Path

from harness_mem import __version__
from harness_mem.version_drift import version_drift_report


def _write_repo_assets(root: Path, *, version: str, wire: str) -> None:
    plugin = root / "code" / "plugins" / "harness-mem"
    manifest = plugin / ".codex-plugin" / "plugin.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps({"version": version, "wireFormatVersion": wire}),
        encoding="utf-8",
    )
    command = plugin / "commands" / "hm" / "hm.md"
    command.parent.mkdir(parents=True)
    command.write_text(f"wireFormatVersion: {wire}\n", encoding="utf-8")


def test_version_drift_accepts_the_single_current_entry(tmp_path: Path) -> None:
    _write_repo_assets(tmp_path, version=__version__, wire="hm-wire-v3.5")
    claude_home = tmp_path / "claude"
    command = claude_home / "commands" / "hm.md"
    command.parent.mkdir(parents=True)
    command.write_text("wireFormatVersion: hm-wire-v3.5\n", encoding="utf-8")

    report = version_drift_report(tmp_path, claude_home=claude_home)

    assert report["surfaces"]["primary_command"]["found"] is True
    assert report["surfaces"]["host_command"]["found"] is True
    assert "slash_status" not in report["surfaces"]
    assert "host_slash_commands" not in report["surfaces"]
    assert report["has_drift"] is False


def test_version_drift_reports_manifest_and_single_entry_drift(tmp_path: Path) -> None:
    _write_repo_assets(tmp_path, version="0.8.7", wire="hm-wire-v3.5")
    claude_home = tmp_path / "claude"
    command = claude_home / "commands" / "hm.md"
    command.parent.mkdir(parents=True)
    command.write_text("wireFormatVersion: old\n", encoding="utf-8")

    report = version_drift_report(tmp_path, claude_home=claude_home)
    issue_kinds = {
        (item["surface"], item["kind"]) for item in report["issues"]
    }

    assert ("plugin", "version_mismatch") in issue_kinds
    assert ("host_command", "stale_wire_format") in issue_kinds
    assert all("/hm:*" not in item["message"] for item in report["issues"])
