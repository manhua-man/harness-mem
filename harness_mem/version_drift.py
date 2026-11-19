"""Local install/version drift checks for the repo-local plugin and runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem import __version__
from harness_mem.version import WIRE_FORMAT_VERSION, runtime_version_payload


def version_drift_report(
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Return a read-only drift report for repo-local host registrations.

    The report is deliberately advisory. It never mutates global host config;
    callers render host-specific update hints when a stale or incompatible
    plugin registration is detected.
    """
    root = Path(repo_root) if repo_root is not None else Path.cwd()
    plugin_root = root / "code" / "plugins" / "harness-mem"
    alternate = root / "plugins" / "harness-mem"
    if not plugin_root.exists() and alternate.exists():
        plugin_root = alternate

    surfaces: dict[str, Any] = {
        "runtime": runtime_version_payload(),
        "plugin": _plugin_surface(plugin_root / ".codex-plugin" / "plugin.json"),
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
                        "plugin version "
                        f"{plugin.get('version')} differs from runtime "
                        f"{__version__}"
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
                        f"{plugin.get('wire_format_version')} differs from "
                        f"{WIRE_FORMAT_VERSION}"
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
                "fix": "Check the repo-local plugin location under code/plugins/harness-mem.",
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
            "Codex plugin: reinstall or refresh code/plugins/harness-mem without mutating global config automatically.",
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


__all__ = ["version_drift_report"]
