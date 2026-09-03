"""Local install/version drift checks for plugin, skill, MCP and CLI surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.plugin_assets import expected_plugin_manifest_fields, plugin_asset_paths
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
        "primary_command": _text_surface(paths.primary_command),
        "host_command": _host_command_surface(claude_home),
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
                "fix": "Run the host-specific plugin install flow from code/plugins/harness-mem/README.md.",
            }
        )

    for name in ("skill", "primary_command"):
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
            "Codex plugin: reinstall or refresh code/plugins/harness-mem without mutating global config automatically.",
            "Memory entry: run `harness-mem quickstart` in the current Agent app, or use `harness-mem integration commands sync --client <host>` for explicit repair.",
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


def _host_command_surface(claude_home: Path | None) -> dict[str, Any]:
    commands_root = _host_root(claude_home) / "commands"
    primary_path = commands_root / "hm.md"
    return {
        "found": primary_path.is_file(),
        "path": str(primary_path),
        "stale": (
            primary_path.is_file() and WIRE_FORMAT_VERSION not in _read_text(primary_path)
        ),
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
    command = surfaces["host_command"]
    if command.get("stale"):
        issues.append(
            {
                "surface": "host_command",
                "kind": "stale_wire_format",
                "message": "installed Claude /hm entry is stale",
                "fix": "Run harness-mem quickstart --client claude-code.",
            }
        )

    skill = surfaces["host_skill"]
    if skill.get("found") and skill.get("stale"):
        issues.append(
            {
                "surface": "host_skill",
                "kind": "stale_wire_format",
                "message": "installed Claude harness-mem skill is stale",
                "fix": "Refresh the plugin through the Agent tool that owns its installation.",
            }
        )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


__all__ = ["version_drift_report"]
