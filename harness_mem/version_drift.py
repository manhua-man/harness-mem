"""Local install/version drift checks for plugin, skill, MCP and CLI surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.plugin_assets import (
    DAILY_COMMANDS,
    expected_plugin_manifest_fields,
    plugin_asset_paths,
)
from harness_mem.version import WIRE_FORMAT_VERSION, runtime_version_payload


def version_drift_report(
    repo_root: Path | None = None,
    *,
    claude_home: Path | None = None,
) -> dict[str, Any]:
    """Return a read-only drift report for repo-local host registrations.

    The report is deliberately advisory. It never mutates global host config;
    callers render host-specific update hints when a stale or incompatible
    plugin/skill/slash registration is detected.
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    paths = plugin_asset_paths(root)
    expected_manifest = expected_plugin_manifest_fields()

    surfaces: dict[str, Any] = {
        "runtime": runtime_version_payload(),
        "plugin": _plugin_surface(paths.manifest),
        "skill": _text_surface(paths.skill),
        "slash_status": _text_surface(paths.daily_status),
        "host_slash_commands": _host_slash_commands_surface(claude_home),
        "host_skill": _host_skill_surface(claude_home),
    }
    issues: list[dict[str, str]] = []
    plugin = surfaces["plugin"]
    if plugin.get("found"):
        if plugin.get("version") != expected_manifest["version"]:
            issues.append(
                {
                    "surface": "plugin",
                    "kind": "version_mismatch",
                    "message": (
                        "plugin version "
                        f"{plugin.get('version')} differs from runtime "
                        f"{expected_manifest['version']}"
                    ),
                    "fix": "Reinstall or refresh the repo-local harness-mem plugin for this host.",
                }
            )
        if plugin.get("wire_format_version") != expected_manifest["wireFormatVersion"]:
            issues.append(
                {
                    "surface": "plugin",
                    "kind": "wire_format_mismatch",
                    "message": (
                        "plugin wire format "
                        f"{plugin.get('wire_format_version')} differs from "
                        f"{expected_manifest['wireFormatVersion']}"
                    ),
                    "fix": "Update the host plugin files; do not edit global config by hand.",
                }
            )
    else:
        issues.append(
            {
                "surface": "plugin",
                "kind": "missing_registration",
                "message": "repo-local plugin manifest was not found",
                "fix": "Run the host-specific plugin install flow from plugins/harness-mem/README.md.",
            }
        )

    for name in ("skill", "slash_status"):
        surface = surfaces[name]
        if not surface.get("found"):
            issues.append(
                {
                    "surface": name,
                    "kind": "missing_registration",
                    "message": f"{name} file was not found",
                    "fix": "Refresh the repo-local plugin assets before reinstalling in the host.",
                }
            )
        elif WIRE_FORMAT_VERSION not in surface.get("text", ""):
            issues.append(
                {
                    "surface": name,
                    "kind": "stale_wire_format",
                    "message": f"{name} does not advertise {WIRE_FORMAT_VERSION}",
                    "fix": "Refresh slash/skill assets, then reinstall in the host if needed.",
                }
            )

    _append_host_install_issues(issues, surfaces)

    return {
        "success": True,
        "runtime_version": expected_manifest["version"],
        "wire_format_version": WIRE_FORMAT_VERSION,
        "surfaces": surfaces,
        "issues": issues,
        "has_drift": bool(issues),
        "update_guidance": [
            "Codex plugin: reinstall or refresh plugins/harness-mem without mutating global config automatically.",
            "Slash commands: run sync-commands.ps1 or `harness-mem integration commands sync` so /hm:* registrations point at the current assets.",
            "MCP: restart the host MCP session after updating the runtime package.",
        ],
    }


def _plugin_surface(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"found": False, "path": str(path)}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return {"found": True, "path": str(path), "error": str(exc)}
    return {
        "found": True,
        "path": str(path),
        "version": data.get("version"),
        "wire_format_version": data.get("wireFormatVersion"),
    }


def _text_surface(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"found": False, "path": str(path), "text": ""}
    text = path.read_text(encoding="utf-8")
    return {"found": True, "path": str(path), "text": text[:2000]}


def _host_root(claude_home: Path | None) -> Path:
    return Path(claude_home).expanduser() if claude_home is not None else Path.home() / ".claude"


def _host_slash_commands_surface(claude_home: Path | None) -> dict[str, Any]:
    command_dir = _host_root(claude_home) / "commands" / "hm"
    files = {path.stem: path for path in command_dir.glob("*.md")} if command_dir.exists() else {}
    present = tuple(command for command in DAILY_COMMANDS if command in files)
    missing = tuple(command for command in DAILY_COMMANDS if command not in files)
    stale = tuple(
        command
        for command, path in files.items()
        if command in DAILY_COMMANDS and WIRE_FORMAT_VERSION not in _read_text(path)
    )
    return {
        "found": command_dir.exists(),
        "path": str(command_dir),
        "present": present,
        "missing": missing,
        "stale": stale,
    }


def _host_skill_surface(claude_home: Path | None) -> dict[str, Any]:
    path = _host_root(claude_home) / "skills" / "harness-mem" / "SKILL.md"
    surface = _text_surface(path)
    if surface.get("found"):
        surface["stale"] = WIRE_FORMAT_VERSION not in surface.get("text", "")
    return surface


def _append_host_install_issues(
    issues: list[dict[str, str]],
    surfaces: dict[str, Any],
) -> None:
    slash = surfaces["host_slash_commands"]
    if slash.get("found") and slash.get("missing"):
        issues.append(
            {
                "surface": "host_slash_commands",
                "kind": "incomplete_install",
                "message": "installed Claude /hm:* commands are incomplete",
                "fix": "Run plugins/harness-mem/scripts/install.ps1 or sync-commands.ps1.",
            }
        )
    if slash.get("found") and slash.get("stale"):
        issues.append(
            {
                "surface": "host_slash_commands",
                "kind": "stale_wire_format",
                "message": "installed Claude /hm:* commands are stale",
                "fix": "Run plugins/harness-mem/scripts/install.ps1 or sync-commands.ps1.",
            }
        )

    skill = surfaces["host_skill"]
    if skill.get("found") and skill.get("stale"):
        issues.append(
            {
                "surface": "host_skill",
                "kind": "stale_wire_format",
                "message": "installed Claude harness-mem skill is stale",
                "fix": "Run plugins/harness-mem/scripts/install.ps1.",
            }
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = ["version_drift_report"]
