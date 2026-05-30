"""CLI scope guard tests (v2.4.3 Task 7, Req 8.5 + v2.4.0 Req 10.2).

v2.4 keeps the ``harness-mem`` console script *maintenance-only*: it manages
configuration and installs IDE hooks, but it never exposes the business memory
loop (reflection / distill / ingest / wake) as a top-level subcommand. Those
flows run exclusively through MCP tools or ``python -m harness_mem.host_entry``.

This module re-asserts that boundary from the v2.4.3 vantage point:

* v2.4.0 Req 10.2 forbids a ``harness-mem reflection`` business subcommand.
* v2.4.3 Req 8.5 widens that to forbid ``distill``, ``ingest`` and ``wake`` as
  top-level ``harness-mem`` subcommands as well (maintenance-only CLI scope).

The registered subcommands are discovered by introspecting the live
``harness-mem`` argparse tree (mirroring ``tests/test_hook_boundary.py``)
rather than by grepping ``cli.py`` source, so the guard reflects what the CLI
actually wires up. Note that an ``import`` subcommand (importing AI-generated
memory drafts into the candidate layer) is an allowed maintenance command and
is deliberately *not* on the forbidden list — the forbidden token is
``ingest``, not ``import``.
"""

from __future__ import annotations

import argparse
import sys
from typing import Any, cast
from unittest import mock

from harness_mem import cli

# Business memory-loop verbs that must NOT exist as top-level ``harness-mem``
# subcommands in v2.4 (Req 8.5 maintenance-only scope; v2.4.0 Req 10.2 for
# ``reflection``). ``import`` is intentionally absent from this set: it is an
# allowed maintenance command, distinct from the forbidden ``ingest`` verb.
FORBIDDEN_BUSINESS_COMMANDS = frozenset({"reflection", "distill", "ingest", "wake"})


# ---------------------------------------------------------------------------
# Argparse-tree introspection (mirrors tests/test_hook_boundary.py): discover
# the registered top-level subcommands without grepping the source file.
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


def _discover_top_level_commands() -> set[str]:
    """Collect every registered top-level ``harness-mem`` subcommand name.

    Includes aliases (argparse records them as additional ``choices`` keys),
    which is exactly what we want: an alias of a forbidden command would also
    be a scope violation.
    """
    parser = _build_cli_parser()
    top_choices = cast(
        "dict[str, argparse.ArgumentParser]", _subparsers_action(parser).choices
    )
    return set(top_choices.keys())


TOP_LEVEL_COMMANDS = _discover_top_level_commands()


# ---------------------------------------------------------------------------
# Discovery sanity guard (prevent a silent empty/garbage introspection result).
# ---------------------------------------------------------------------------


def test_discovery_finds_known_maintenance_commands() -> None:
    """Sanity-check that introspection captured the real CLI surface."""
    # These maintenance commands are known to exist; if introspection returned
    # an empty/garbage set the forbidden-command guards below would pass
    # vacuously, so anchor on a couple of known-present commands.
    assert {"config", "integration"} <= TOP_LEVEL_COMMANDS


# ---------------------------------------------------------------------------
# Task 7.1 — v2.4.0 Req 10.2: no ``harness-mem reflection`` subcommand.
# ---------------------------------------------------------------------------


def test_no_reflection_subcommand() -> None:
    """Req 10.2 (v2.4.0): the business ``reflection`` verb is not a CLI command."""
    assert "reflection" not in TOP_LEVEL_COMMANDS, (
        "v2.4.0 Req 10.2 forbids a 'harness-mem reflection' business subcommand; "
        f"found top-level commands: {sorted(TOP_LEVEL_COMMANDS)}"
    )


# ---------------------------------------------------------------------------
# Task 7.2 — Req 8.5: no distill / ingest / wake business subcommands.
# ---------------------------------------------------------------------------


def test_no_business_subcommands() -> None:
    """Req 8.5: the CLI is maintenance-only; no business memory-loop verbs.

    ``import`` (importing AI drafts) is an allowed maintenance command and is
    deliberately not on the forbidden list. The forbidden verb is ``ingest``.
    """
    violations = sorted(FORBIDDEN_BUSINESS_COMMANDS & TOP_LEVEL_COMMANDS)
    assert violations == [], (
        "Req 8.5 (maintenance-only CLI scope) forbids business subcommands "
        f"{sorted(FORBIDDEN_BUSINESS_COMMANDS)} as top-level 'harness-mem' "
        f"commands; found violation(s): {violations}. Full top-level command "
        f"list: {sorted(TOP_LEVEL_COMMANDS)}"
    )
