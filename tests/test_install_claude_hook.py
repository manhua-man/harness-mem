"""Tests for ``cmd_install_claude_hook`` (v2.4.3 Task 4, Req 6).

Mirror of ``test_install_cursor_hook`` for the Claude Code after-turn hook at
``<project_root>/.claude/hooks/after-turn.sh``. Handlers are exercised directly
against a ``tmp_path`` project_root (project rule P1: data-path isolation).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from harness_mem import __version__
from harness_mem.commands import integration_cmds
from harness_mem.commands.integration_cmds import cmd_install_claude_hook

_HOOK_RELATIVE = Path(".claude") / "hooks" / "after-turn.sh"


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An existing absolute project directory under tmp_path."""
    proj = tmp_path / "project"
    proj.mkdir()
    return proj


# ---- Req 6.4: successful install -----------------------------------------


def test_install_success_stdout_and_file(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = cmd_install_claude_hook(str(project_dir), False)
    assert rc == 0
    target = project_dir / _HOOK_RELATIVE
    assert target.is_file()
    out = capsys.readouterr()
    assert out.out.strip() == f"installed: {target.resolve()}"
    assert out.err == ""


# ---- Req 6.2: rendered content + host-entry boundary marker --------------


def test_hook_body_contains_host_entry_invocation(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_install_claude_hook(str(project_dir), False)
    capsys.readouterr()
    body = (project_dir / _HOOK_RELATIVE).read_text(encoding="utf-8")
    assert "python -m harness_mem.host_entry" in body
    assert "--source ide_hook" in body


# ---- Req 6.8: version + ISO date in the comment header -------------------


def test_hook_header_has_version_and_iso_date(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_install_claude_hook(str(project_dir), False)
    capsys.readouterr()
    body = (project_dir / _HOOK_RELATIVE).read_text(encoding="utf-8")
    assert __version__ in body
    assert re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", body)


# ---- Req 6.2: project_root substituted to an ABSOLUTE path ---------------


def test_project_root_substituted_absolute(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cmd_install_claude_hook(str(project_dir), False)
    capsys.readouterr()
    body = (project_dir / _HOOK_RELATIVE).read_text(encoding="utf-8")
    abs_root = str(project_dir.resolve())
    assert f'PROJECT_ROOT="{abs_root}"' in body


def test_project_root_defaults_to_cwd(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(project_dir)
    rc = cmd_install_claude_hook(None, False)
    assert rc == 0
    capsys.readouterr()
    assert (project_dir / _HOOK_RELATIVE).is_file()


# ---- Req 6.7: force overwrites; default refuses --------------------------


def test_force_flag_overwrites_existing_hook(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project_dir / _HOOK_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("stale content\n", encoding="utf-8")
    rc = cmd_install_claude_hook(str(project_dir), True)
    assert rc == 0
    capsys.readouterr()
    body = target.read_text(encoding="utf-8")
    assert "stale content" not in body
    assert "python -m harness_mem.host_entry" in body


def test_refuse_overwrite_default(
    project_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    target = project_dir / _HOOK_RELATIVE
    target.parent.mkdir(parents=True, exist_ok=True)
    original = "pre-existing content\n"
    target.write_text(original, encoding="utf-8")
    rc = cmd_install_claude_hook(str(project_dir), False)
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "hook already exists:" in out.err
    assert "use --force to overwrite" in out.err
    assert target.read_text(encoding="utf-8") == original


# ---- Req 6.5: OSError surfaces as exit 1 + stderr ------------------------


def test_oserror_surfaces_install_failed(
    project_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _boom(**kwargs: object) -> None:
        raise OSError("permission denied")

    monkeypatch.setattr(integration_cmds, "install_hook", _boom)
    rc = cmd_install_claude_hook(str(project_dir), False)
    assert rc == 1
    out = capsys.readouterr()
    assert out.out == ""
    assert "install failed:" in out.err
    assert "permission denied" in out.err
