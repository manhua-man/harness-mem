"""Local install/version drift checks for plugin, skill, MCP and CLI surfaces."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem import __version__
from harness_mem.version import WIRE_FORMAT_VERSION, runtime_version_payload


def version_drift_report(repo_root: Path | None = None) -> dict[str, Any]:
    """Return a read-only drift report for repo-local host registrations.

    The report is deliberately advisory. It never mutates global host config;
    callers render host-specific update hints when a stale or incompatible
    plugin/skill/slash registration is detected.
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    plugin_root = root / "plugins" / "harness-mem"
    plugin_manifest = plugin_root / ".codex-plugin" / "plugin.json"
    slash_status = plugin_root / "commands" / "hm" / "status.md"
    skill_file = plugin_root / "skills" / "harness-mem" / "SKILL.md"

    surfaces: dict[str, Any] = {
        "runtime": runtime_version_payload(),
        "plugin": _plugin_surface(plugin_manifest),
        "skill": _text_surface(skill_file),
        "slash_status": _text_surface(slash_status),
    }
    issues: list[dict[str, str]] = []
    plugin = surfaces["plugin"]
    if plugin.get("found"):
        if plugin.get("version") != __version__:
            issues.append(
                {
                    "surface": "plugin",
                    "kind": "version_mismatch",
                    "message": (
                        f"plugin version {plugin.get('version')} differs from runtime {__version__}"
                    ),
                    "fix": "Reinstall or refresh the repo-local harness-mem plugin for this host.",
                }
            )
        if plugin.get("wire_format_version") != WIRE_FORMAT_VERSION:
            issues.append(
                {
                    "surface": "plugin",
                    "kind": "wire_format_mismatch",
                    "message": (
                        "plugin wire format "
                        f"{plugin.get('wire_format_version')} differs from {WIRE_FORMAT_VERSION}"
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

    return {
        "success": True,
        "runtime_version": __version__,
        "wire_format_version": WIRE_FORMAT_VERSION,
        "surfaces": surfaces,
        "issues": issues,
        "has_drift": bool(issues),
        "update_guidance": [
            "Codex plugin: reinstall or refresh plugins/harness-mem without mutating global config automatically.",
            "Slash commands: rerun the host plugin install step so /hm:* registrations point at the current assets.",
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


__all__ = ["version_drift_report"]
