"""Resolve the active profile shared by Hermes capture, cleanup and Hooks."""

from __future__ import annotations

import os
from pathlib import Path
import sys


def default_hermes_home() -> Path:
    """Return Hermes' platform-native active profile for commands and Hooks."""

    configured_home = os.environ.get("HERMES_HOME", "").strip()
    if configured_home:
        return Path(configured_home).expanduser()
    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA", "").strip()
        base = (
            Path(local_appdata)
            if local_appdata
            else Path.home() / "AppData" / "Local"
        )
        return base / "hermes"
    return Path.home() / ".hermes"
