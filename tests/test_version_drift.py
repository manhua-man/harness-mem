from __future__ import annotations

import json
from pathlib import Path

from harness_mem import __version__
from harness_mem.version_drift import version_drift_report


def _write_plugin_manifest(plugin_root: Path, *, version: str, wire: str) -> None:
    manifest_dir = plugin_root / ".codex-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_dir.joinpath("plugin.json").write_text(
        json.dumps(
            {
                "name": "harness-mem",
                "version": version,
                "wireFormatVersion": wire,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def _write_daily_status(plugin_root: Path, *, wire: str) -> None:
    status_dir = plugin_root / "commands" / "hm" / "daily"
    status_dir.mkdir(parents=True, exist_ok=True)
    status_dir.joinpath("status.md").write_text(
        f"---\nwireFormatVersion: {wire}\n---\n",
        encoding="utf-8",
    )


def _write_skill(plugin_root: Path, *, wire: str) -> None:
    skill_dir = plugin_root / "skills" / "harness-mem"
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_dir.joinpath("SKILL.md").write_text(
        f"---\nwireFormatVersion: {wire}\n---\n",
        encoding="utf-8",
    )


def test_version_drift_uses_daily_status_path_and_accepts_matching_manifest(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    plugin_root = repo_root / "plugins" / "harness-mem"
    _write_plugin_manifest(plugin_root, version=__version__, wire="hm-wire-v3.5")
    _write_daily_status(plugin_root, wire="hm-wire-v3.5")
    _write_skill(plugin_root, wire="hm-wire-v3.5")

    report = version_drift_report(repo_root)

    assert report["surfaces"]["slash_status"]["found"] is True
    assert report["issues"] == []


def test_version_drift_flags_plugin_version_mismatch(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    plugin_root = repo_root / "plugins" / "harness-mem"
    _write_plugin_manifest(plugin_root, version="0.8.7", wire="hm-wire-v3.5")
    _write_daily_status(plugin_root, wire="hm-wire-v3.5")
    _write_skill(plugin_root, wire="hm-wire-v3.5")

    report = version_drift_report(repo_root)

    assert any(issue["kind"] == "version_mismatch" for issue in report["issues"])
