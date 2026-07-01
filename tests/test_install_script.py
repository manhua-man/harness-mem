from __future__ import annotations

from pathlib import Path


def test_install_script_passes_named_profile_argument() -> None:
    script = Path("plugins/harness-mem/scripts/install.ps1").read_text(encoding="utf-8")

    assert '& $syncCommands -Profile "Daily"' in script
    assert "@syncArgs" not in script
