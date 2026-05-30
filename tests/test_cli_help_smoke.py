"""Smoke tests for v2.4 maintenance-CLI ``--help`` discoverability (Task 6, Req 8).

These assert the operator-facing opt-in messaging required by Req 8.1 / 8.2 is
present in the argparse ``--help`` output. They run the parser **in-process** by
monkeypatching ``sys.argv`` and invoking :func:`harness_mem.cli.main`, capturing
the ``SystemExit`` argparse raises for ``--help`` and the stdout via ``capsys``.
No subprocess is spawned, so the tests are deterministic.

``COLUMNS`` is pinned wide so argparse does not wrap (and therefore never
hyphen-breaks tokens like ``harness-mem``), and the captured text is whitespace-
normalized + lowercased before substring assertions so the checks do not depend
on the terminal width or on the exact capitalization of the source strings.
"""

from __future__ import annotations

import sys

import pytest

from harness_mem.cli import main


def _help_text(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> str:
    """Invoke ``main()`` for an ``argv`` ending in ``--help``; return its stdout.

    Returns the captured stdout whitespace-normalized to single spaces and
    lowercased, so substring assertions are robust to line wrapping and case.
    """
    # Pin a wide terminal so argparse does not wrap the description text.
    monkeypatch.setenv("COLUMNS", "1000")
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    captured = capsys.readouterr()
    return " ".join(captured.out.split()).lower()


# ---- Req 8.1: parent --help states default-off + hook-alone-doesn't-enable --


@pytest.mark.parametrize("parent", ["config", "integration"])
def test_parent_help_states_default_off_and_opt_in(
    parent: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = _help_text(monkeypatch, capsys, ["harness-mem", parent, "--help"])
    # Default-off statement.
    assert "triggers default to 'off'" in text
    # Installing a hook alone does not enable reflection.
    assert "does not by itself enable reflection" in text


# ---- Req 8.2: installer --help points at the opt-in invocation -------------


@pytest.mark.parametrize(
    "subcommand", ["install-cursor-hook", "install-claude-hook"]
)
def test_installer_help_points_at_opt_in(
    subcommand: str,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = _help_text(
        monkeypatch, capsys, ["harness-mem", "integration", subcommand, "--help"]
    )
    assert (
        "after install, opt in via: harness-mem config set "
        "triggers.after_agent on --scope project" in text
    )
