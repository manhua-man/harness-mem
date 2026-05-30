"""Hook boundary contract tests (v2.4.3 Task 5, Req 7).

This is the v2.4.3 *single guard against future hook-template drift*. Rather
than hard-coding the Cursor / Claude installers, it discovers every installer
subcommand by introspecting the live ``harness-mem`` argparse tree: it finds
the ``integration`` parent subparser and collects every child whose name matches
``install-*-hook``. A future IDE installer added under ``integration`` therefore
lights up these checks automatically with zero test edits (Req 7.4).

For each discovered installer the suite invokes it through the real CLI dispatch
against a fresh ``tmp_path`` project root, locates the single generated hook
file generically (no hard-coded per-IDE paths, Req 7.5/7.7), and asserts the
v2.4.0 Req 10.2 boundary on the rendered body:

* contains the literal ``python -m harness_mem.host_entry`` (Req 7.1, 7.2);
* has no non-comment line invoking the ``harness-mem`` console script, i.e. no
  line matching ``^[^#]*\\bharness-mem\\s+\\S`` (Req 7.3) — Property 2;
* contains ``--source ide_hook`` (Req 7.6);
* every ``--source`` value present is a member of the v2.4.0 Trigger_Source set
  ``{user, agent, ide_hook, scheduler}`` (Req 7.7).

It also verifies Property 4 (force-flag symmetry, Req 5.7/6.7).

The Trigger_Source "enum" is not a Python ``Enum`` class in this codebase: it is
a literal set expressed as ``Literal["user", "agent", "ide_hook", "scheduler"]``
in the schemas and as the validation tuple ``_VALID_SOURCES`` in the host entry.
We derive the allowed set from ``_VALID_SOURCES`` (the runtime gate the hook's
``--source`` value actually passes through) instead of hard-coding it.

All writes target ``tmp_path`` so the suite is deterministic and never touches
the operator filesystem (project rule P1: data-path isolation; Req 7.5).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any, cast
from unittest import mock

import pytest

from harness_mem import cli

# The authoritative Trigger_Source set: the host-entry validation tuple that
# every ``--source`` value must satisfy at runtime. Imported (not hard-coded)
# so drift in the source of truth is reflected here automatically (Req 7.7).
from harness_mem.host_entry.__main__ import _VALID_SOURCES

# Executable invocation of the ``harness-mem`` console script on a non-comment
# line. ``^[^#]*`` cannot cross a ``#`` so any comment (leading or inline) that
# merely mentions ``harness-mem`` for documentation is exempt (Req 7.3).
_FORBIDDEN_INVOCATION = re.compile(r"^[^#]*\bharness-mem\s+\S")
_REQUIRED_HOST_ENTRY = "python -m harness_mem.host_entry"
_SOURCE_VALUE = re.compile(r"--source\s+(\S+)")
_INSTALLER_NAME = re.compile(r"^install-.+-hook$")


# ---------------------------------------------------------------------------
# Argparse-tree introspection (Req 7.4): discover installers generically.
# ---------------------------------------------------------------------------


def _build_cli_parser() -> argparse.ArgumentParser:
    """Capture the exact parser ``cli.main()`` builds, without dispatching.

    ``cli.main()`` constructs its argparse tree inline and exposes no builder
    helper, so we run ``main()`` with ``parse_args`` patched to record the
    top-level parser and short-circuit. Returning a Namespace whose ``command``
    matches no dispatch branch makes ``main()`` fall through to ``return 0``
    silently, so no command actually executes.
    """
    captured: dict[str, argparse.ArgumentParser] = {}
    original_parse_args = argparse.ArgumentParser.parse_args

    def _capture(
        self: argparse.ArgumentParser, args: Any = None, namespace: Any = None
    ) -> argparse.Namespace:
        if self.prog == "harness-mem":
            captured["parser"] = self
            return argparse.Namespace(command="__introspect_noop__")
        return original_parse_args(self, args, namespace)

    saved_argv = list(sys.argv)
    try:
        sys.argv = ["harness-mem"]
        with mock.patch.object(argparse.ArgumentParser, "parse_args", _capture):
            cli.main()
    finally:
        sys.argv = saved_argv

    if "parser" not in captured:  # pragma: no cover - defensive
        raise RuntimeError("failed to capture the harness-mem CLI parser")
    return captured["parser"]


def _subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction[argparse.ArgumentParser]:
    """Return the (single) subparsers action attached to ``parser``."""
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    raise RuntimeError("no subparsers action found on parser")  # pragma: no cover


def _discover_installers() -> list[str]:
    """Collect every ``install-*-hook`` child under the ``integration`` parent.

    This is the generic discovery that makes the boundary check cover every
    registered installer subcommand (Req 7.4) rather than a hard-coded list.
    """
    parser = _build_cli_parser()
    top_choices = cast(
        "dict[str, argparse.ArgumentParser]", _subparsers_action(parser).choices
    )
    integration_parser = top_choices["integration"]
    integ_choices = cast(
        "dict[str, argparse.ArgumentParser]",
        _subparsers_action(integration_parser).choices,
    )
    return sorted(name for name in integ_choices if _INSTALLER_NAME.match(name))


INSTALLERS = _discover_installers()


# ---------------------------------------------------------------------------
# Generic install + hook-file location (no hard-coded per-IDE paths, Req 7.7).
# ---------------------------------------------------------------------------


def _run_installer(
    installer_name: str,
    project_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    force: bool = False,
) -> int:
    """Invoke an installer through the real CLI dispatch; return its exit code."""
    argv = [
        "harness-mem",
        "integration",
        installer_name,
        "--project-root",
        str(project_root),
    ]
    if force:
        argv.append("--force")
    monkeypatch.setattr(sys, "argv", argv)
    return cli.main()


def _locate_generated_hook(project_root: Path) -> Path:
    """Find the single hook file an installer produced under a fresh root.

    Deriving the path by scanning the (otherwise empty) project root keeps the
    test independent of each IDE's specific hook directory layout (Req 7.5/7.7).
    """
    files = [p for p in project_root.rglob("*") if p.is_file()]
    assert len(files) == 1, f"expected exactly one generated hook file, got {files}"
    return files[0]


@pytest.fixture(params=INSTALLERS)
def installer_name(request: pytest.FixtureRequest) -> str:
    """Parametrize across every discovered installer subcommand (Req 7.4)."""
    return cast(str, request.param)


@pytest.fixture
def generated_hook(
    installer_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Install one hook into a fresh tmp project root and return its path."""
    project_root = tmp_path / "project"
    project_root.mkdir()
    rc = _run_installer(installer_name, project_root, monkeypatch)
    assert rc == 0
    return _locate_generated_hook(project_root)


# ---------------------------------------------------------------------------
# Discovery sanity guards (prevent silent empty parametrization).
# ---------------------------------------------------------------------------


def test_discovery_finds_installers() -> None:
    assert INSTALLERS, "argparse introspection discovered no install-*-hook subcommands"


def test_discovery_includes_known_installers() -> None:
    # Lower-bound sanity check; discovery still lights up any future installer.
    assert {"install-cursor-hook", "install-claude-hook"} <= set(INSTALLERS)


# ---------------------------------------------------------------------------
# Property 2 — Hook boundary inviolability (Req 5.3, 6.3, 7.1, 7.2, 7.3).
# **Validates: Requirements 7.1, 7.2, 7.3, 7.6, 7.7**
# ---------------------------------------------------------------------------


def test_hook_invokes_host_entry(generated_hook: Path) -> None:
    """Req 7.1, 7.2: the rendered body invokes the v2.4.1 host entry."""
    body = generated_hook.read_text(encoding="utf-8")
    assert _REQUIRED_HOST_ENTRY in body


def test_hook_has_no_console_script_invocation(generated_hook: Path) -> None:
    """Req 7.3 (Property 2): no non-comment line invokes ``harness-mem``."""
    body = generated_hook.read_text(encoding="utf-8")
    offenders = [
        line for line in body.splitlines() if _FORBIDDEN_INVOCATION.search(line)
    ]
    assert offenders == [], f"forbidden console-script invocation(s): {offenders}"


def test_hook_marks_source_ide_hook(generated_hook: Path) -> None:
    """Req 7.6: the invocation tags the job as an IDE hook."""
    body = generated_hook.read_text(encoding="utf-8")
    assert "--source ide_hook" in body


def test_hook_source_values_are_valid_trigger_sources(generated_hook: Path) -> None:
    """Req 7.7: every ``--source`` value is a member of the Trigger_Source set."""
    body = generated_hook.read_text(encoding="utf-8")
    values = _SOURCE_VALUE.findall(body)
    assert values, "expected at least one --source argument in the hook body"
    valid = set(_VALID_SOURCES)
    assert valid == {"user", "agent", "ide_hook", "scheduler"}  # guard against drift
    for value in values:
        assert value in valid, f"--source {value!r} is outside Trigger_Source {valid}"


# ---------------------------------------------------------------------------
# Property 4 — Force-flag symmetry (Req 5.7, 6.7).
# **Validates: Requirements 5.7, 6.7**
# ---------------------------------------------------------------------------


def test_force_flag_symmetry(
    installer_name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()

    # Seed an existing hook via a first successful install.
    assert _run_installer(installer_name, project_root, monkeypatch) == 0
    hook = _locate_generated_hook(project_root)

    # (a) No --force against an existing file: exit non-zero, bytes unchanged.
    before = hook.read_bytes()
    rc = _run_installer(installer_name, project_root, monkeypatch)
    assert rc != 0
    assert hook.read_bytes() == before

    # (b) With --force: exit 0 and the file is a freshly-rendered template,
    # i.e. stale content is gone and the boundary markers are present.
    hook.write_text("STALE-SENTINEL\n", encoding="utf-8")
    rc = _run_installer(installer_name, project_root, monkeypatch, force=True)
    assert rc == 0
    body = hook.read_text(encoding="utf-8")
    assert "STALE-SENTINEL" not in body
    assert _REQUIRED_HOST_ENTRY in body
    assert "--source ide_hook" in body
