from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from harness_mem import shell_completion


REPO_ROOT = Path(__file__).resolve().parent.parent


def test_bash_completion_lists_current_top_level_commands() -> None:
    script = shell_completion.completion_bash()

    assert "init quickstart doctor import purge maintenance config integration qs" in script
    assert "get set list validate" in script
    assert "install-cursor-hook install-claude-hook" in script


def test_zsh_completion_lists_current_top_level_commands_and_actions() -> None:
    script = shell_completion.completion_zsh()

    assert "commands=(init quickstart doctor import purge maintenance config integration qs)" in script
    assert "_values 'action' get set list validate" in script
    assert "_values 'action' install-cursor-hook install-claude-hook" in script


def test_fish_completion_lists_current_top_level_commands_and_actions() -> None:
    script = shell_completion.completion_fish()

    assert "init quickstart doctor import purge maintenance config integration qs" in script
    assert '__fish_seen_subcommand_from config' in script
    assert 'install-cursor-hook install-claude-hook' in script


def test_cli_completion_flag_uses_updated_surface() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness_mem.cli", "--completion", "bash"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "config integration qs" in result.stdout
    assert "get set list validate" in result.stdout
