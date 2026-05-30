"""Tests for ``harness_mem.integration.installer.install_hook`` (v2.4.3 Task 3).

These cover the generic installer in isolation: template substitution, the
loud-failure on a missing variable, the internal hook-boundary self-check, the
``force`` overwrite policy, and the refuse-overwrite default. The two real
packaged templates are also rendered to prove they substitute cleanly with
exactly the four documented variables and that no other ``${...}`` shell
reference triggers a ``string.Template`` error.

All writes target ``tmp_path`` (project rule P1: data-path isolation); no test
touches the real filesystem outside its tmp dir.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.integration import installer
from harness_mem.integration.installer import install_hook

_GENERATED_AT = datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
_VERSION = "9.9.9"
_TEMPLATE_NAMES = ["cursor_after_agent.sh.template", "claude_code_hook.sh.template"]


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """An existing absolute project directory under tmp_path."""
    proj = tmp_path / "project"
    proj.mkdir()
    return proj


class _FakeResource:
    """Stand-in for an ``importlib.resources`` Traversable returning a body."""

    def __init__(self, body: str) -> None:
        self._body = body

    def joinpath(self, _name: str) -> "_FakeResource":
        return self

    def read_text(self, encoding: str = "utf-8") -> str:  # noqa: ARG002
        return self._body


def _patch_template_body(monkeypatch: pytest.MonkeyPatch, body: str) -> None:
    """Make the installer read ``body`` instead of a packaged template file."""
    monkeypatch.setattr(
        installer.resources, "files", lambda _pkg: _FakeResource(body)
    )


# ---- substitute round-trip on the real templates ------------------------


@pytest.mark.parametrize("template_name", _TEMPLATE_NAMES)
def test_substitute_round_trip(
    tmp_path: Path, project_dir: Path, template_name: str
) -> None:
    target = tmp_path / "hook.sh"
    result = install_hook(
        template_name=template_name,
        target_path=target,
        project_root=project_dir,
        harness_mem_version=_VERSION,
        generated_at=_GENERATED_AT,
        doc_pointer="docs/cli/v2.4.md",
    )
    assert result == target.resolve()
    body = target.read_text(encoding="utf-8")

    # The four documented variables are substituted.
    assert str(project_dir.resolve()) in body
    assert _VERSION in body
    assert _GENERATED_AT.isoformat() in body
    assert "docs/cli/v2.4.md" in body

    # Host-entry invocation + IDE source marker are present.
    assert "python -m harness_mem.host_entry" in body
    assert "--source ide_hook" in body

    # The ``$$``-escaped shell references survive as single-dollar shell vars,
    # i.e. string.Template did NOT try to resolve them.
    assert "$PROJECT_ROOT" in body
    assert ":-unknown}" in body  # ${...:-unknown} env-var default preserved


@pytest.mark.parametrize("template_name", _TEMPLATE_NAMES)
def test_real_templates_render_without_keyerror(
    tmp_path: Path, project_dir: Path, template_name: str
) -> None:
    # Rendering with exactly the four variables must not raise: no other
    # ``${...}`` in the shell body may look like a substitution variable.
    install_hook(
        template_name=template_name,
        target_path=tmp_path / template_name,
        project_root=project_dir,
        harness_mem_version=_VERSION,
        generated_at=_GENERATED_AT,
    )


# ---- missing variable raises (loud failure) ------------------------------


def test_missing_variable_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project_dir: Path
) -> None:
    _patch_template_body(
        monkeypatch,
        "python -m harness_mem.host_entry --source ide_hook ${FOO}\n",
    )
    with pytest.raises(KeyError):
        install_hook(
            template_name="anything.template",
            target_path=tmp_path / "hook.sh",
            project_root=project_dir,
            harness_mem_version=_VERSION,
            generated_at=_GENERATED_AT,
        )
    # A failed render must not leave a file behind.
    assert not (tmp_path / "hook.sh").exists()


# ---- internal boundary self-check ---------------------------------------


def test_boundary_self_check_rejects_console_script_invocation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project_dir: Path
) -> None:
    bad_body = (
        "#!/usr/bin/env bash\n"
        "python -m harness_mem.host_entry --source ide_hook\n"
        "harness-mem reflection now\n"  # forbidden console-script invocation
    )
    _patch_template_body(monkeypatch, bad_body)
    target = tmp_path / "hook.sh"
    with pytest.raises(RuntimeError, match="forbidden pattern"):
        install_hook(
            template_name="bad.template",
            target_path=target,
            project_root=project_dir,
            harness_mem_version=_VERSION,
            generated_at=_GENERATED_AT,
        )
    # The violating file is never written.
    assert not target.exists()


def test_boundary_self_check_rejects_missing_host_entry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project_dir: Path
) -> None:
    _patch_template_body(monkeypatch, "#!/usr/bin/env bash\necho noop\n")
    with pytest.raises(RuntimeError, match="forbidden pattern"):
        install_hook(
            template_name="bad.template",
            target_path=tmp_path / "hook.sh",
            project_root=project_dir,
            harness_mem_version=_VERSION,
            generated_at=_GENERATED_AT,
        )


def test_boundary_self_check_allows_harness_mem_in_comments(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, project_dir: Path
) -> None:
    # A comment mentioning `harness-mem config set ...` is exempt (Req 7.3).
    good_body = (
        "#!/usr/bin/env bash\n"
        "# harness-mem config set triggers.after_agent on --scope project\n"
        "python -m harness_mem.host_entry --source ide_hook\n"
    )
    _patch_template_body(monkeypatch, good_body)
    target = tmp_path / "hook.sh"
    result = install_hook(
        template_name="ok.template",
        target_path=target,
        project_root=project_dir,
        harness_mem_version=_VERSION,
        generated_at=_GENERATED_AT,
    )
    assert result == target.resolve()


# ---- overwrite policy ----------------------------------------------------


def test_refuse_overwrite_default_raises(
    tmp_path: Path, project_dir: Path
) -> None:
    target = tmp_path / "hook.sh"
    original = "pre-existing content\n"
    target.write_text(original, encoding="utf-8")
    with pytest.raises(FileExistsError):
        install_hook(
            template_name="cursor_after_agent.sh.template",
            target_path=target,
            project_root=project_dir,
            harness_mem_version=_VERSION,
            generated_at=_GENERATED_AT,
        )
    # Existing file is untouched.
    assert target.read_text(encoding="utf-8") == original


def test_force_flag_overwrites(tmp_path: Path, project_dir: Path) -> None:
    target = tmp_path / "hook.sh"
    target.write_text("stale content\n", encoding="utf-8")
    install_hook(
        template_name="cursor_after_agent.sh.template",
        target_path=target,
        project_root=project_dir,
        force=True,
        harness_mem_version=_VERSION,
        generated_at=_GENERATED_AT,
    )
    body = target.read_text(encoding="utf-8")
    assert "stale content" not in body
    assert "python -m harness_mem.host_entry" in body


def test_creates_parent_directory(tmp_path: Path, project_dir: Path) -> None:
    target = tmp_path / "nested" / "hooks" / "hook.sh"
    assert not target.parent.exists()
    install_hook(
        template_name="claude_code_hook.sh.template",
        target_path=target,
        project_root=project_dir,
        harness_mem_version=_VERSION,
        generated_at=_GENERATED_AT,
    )
    assert target.is_file()
