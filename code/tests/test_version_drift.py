from __future__ import annotations

import json
from pathlib import Path

from harness_mem import __version__
from harness_mem.plugin_assets import DAILY_COMMANDS
from harness_mem.version import WIRE_FORMAT_VERSION
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
    status_dir.parent.joinpath("hm.md").write_text(
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
    plugin_root = repo_root / "code" / "plugins" / "harness-mem"
    _write_plugin_manifest(plugin_root, version=__version__, wire="hm-wire-v3.5")
    _write_daily_status(plugin_root, wire="hm-wire-v3.5")
    _write_skill(plugin_root, wire="hm-wire-v3.5")

    report = version_drift_report(repo_root, claude_home=tmp_path / "claude")

    assert report["surfaces"]["slash_status"]["found"] is True
    assert report["issues"] == []


def test_version_drift_flags_plugin_version_mismatch(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path
    plugin_root = repo_root / "code" / "plugins" / "harness-mem"
    _write_plugin_manifest(plugin_root, version="0.8.7", wire="hm-wire-v3.5")
    _write_daily_status(plugin_root, wire="hm-wire-v3.5")
    _write_skill(plugin_root, wire="hm-wire-v3.5")

    report = version_drift_report(repo_root, claude_home=tmp_path / "claude")

    assert any(issue["kind"] == "version_mismatch" for issue in report["issues"])


def test_repo_plugin_manifest_matches_runtime_contract() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    manifest = repo_root / "code" / "plugins" / "harness-mem" / ".codex-plugin" / "plugin.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))

    assert data["version"] == __version__
    assert data["wireFormatVersion"] == WIRE_FORMAT_VERSION


def test_repo_daily_commands_advertise_runtime_wire_format() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    command_dir = (
        repo_root / "code" / "plugins" / "harness-mem" / "commands" / "hm" / "daily"
    )

    for command in DAILY_COMMANDS:
        body = command_dir.joinpath(f"{command}.md").read_text(encoding="utf-8")
        assert f"wireFormatVersion: {WIRE_FORMAT_VERSION}" in body
    primary = command_dir.parent.joinpath("hm.md").read_text(encoding="utf-8")
    assert f"wireFormatVersion: {WIRE_FORMAT_VERSION}" in primary


def test_version_drift_reports_existing_stale_host_install(
    tmp_path: Path,
) -> None:
    repo_root = tmp_path / "repo"
    plugin_root = repo_root / "code" / "plugins" / "harness-mem"
    _write_plugin_manifest(plugin_root, version=__version__, wire="hm-wire-v3.5")
    _write_daily_status(plugin_root, wire="hm-wire-v3.5")
    _write_skill(plugin_root, wire="hm-wire-v3.5")
    host_command_dir = tmp_path / "claude" / "commands" / "hm"
    host_command_dir.mkdir(parents=True)
    host_command_dir.joinpath("status.md").write_text(
        "---\nwireFormatVersion: hm-wire-v0\n---\n",
        encoding="utf-8",
    )

    report = version_drift_report(repo_root, claude_home=tmp_path / "claude")

    issue_kinds = {(issue["surface"], issue["kind"]) for issue in report["issues"]}
    assert ("host_slash_commands", "incomplete_install") in issue_kinds
    assert ("host_slash_commands", "stale_wire_format") in issue_kinds
