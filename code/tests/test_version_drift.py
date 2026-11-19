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


def test_version_drift_accepts_current_manifest(tmp_path: Path) -> None:
    _write_repo_assets(tmp_path, version=__version__, wire="hm-wire-v3.5")
    report = version_drift_report(tmp_path)
    assert set(report["surfaces"]) == {"runtime", "plugin"}
    assert report["has_drift"] is False


def test_version_drift_reports_manifest_and_wire_drift(tmp_path: Path) -> None:
    _write_repo_assets(tmp_path, version="0.8.7", wire="old")
    report = version_drift_report(tmp_path)
    issue_kinds = {
        (item["surface"], item["kind"]) for item in report["issues"]
    }

    assert ("plugin", "version_mismatch") in issue_kinds
    assert ("plugin", "wire_format_mismatch") in issue_kinds
