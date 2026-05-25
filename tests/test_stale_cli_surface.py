"""Stale CLI surface scan for v2.2 user-facing docs.

Question answered: "do README, AGENTS, and the harness-mem plugin
documentation accidentally tell users to run any of the daily CLI
subcommands that v2.0 removed?" The five removed daily commands are
``wake / search / timeline / candidates / distill`` (see
``openspec/specs/cli/spec.md`` — the only CLI surface left is
``init / quickstart / qs / doctor / import / purge / maintenance``).

This is a focused doc scan, not a global lint. It only opens files we
expect to read like a fresh user would — README, AGENTS, the plugin
README, the plugin slash command pages, and the two SKILL.md files an
agent activates. Roadmap, benchmark, and changelog docs deliberately
discuss removed commands as historical context and are not in scope.

Allowlisted lines describe v2.0 removal as a negative reference (e.g.
"v2.0 删除了 ``harness-mem distill`` CLI 子命令") rather than as user
instructions. Add to the ``ALLOWLIST`` mapping with the exact substring
when a new legitimate negative reference is introduced.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent

DEPRECATED_DAILY = re.compile(
    r"\bharness-mem\s+(wake|search|timeline|candidates|distill)\b"
)
"""The five daily CLI subcommands v2.0 removed. ``\\s+`` is intentional —
one or more whitespace characters between the binary and the subcommand
catches both ``harness-mem wake`` and ``harness-mem  wake``."""

ALLOWED_MAINTENANCE: frozenset[str] = frozenset(
    {"quickstart", "doctor", "purge", "maintenance", "import"}
)
"""Maintenance / install / cleanup CLI subcommands that are still part of
the supported surface and may legitimately appear in user docs."""

# Paths are repo-root-relative so the test reads as a list of "places a
# fresh user actually looks". Each entry must exist; a missing target is
# a regression in itself.
SCAN_TARGETS: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "plugins/harness-mem/README.md",
    "plugins/harness-mem/commands/hm/distill.md",
    "plugins/harness-mem/commands/hm/review.md",
    "plugins/harness-mem/commands/hm/search.md",
    "plugins/harness-mem/commands/hm/status.md",
    "plugins/harness-mem/commands/hm/wake.md",
    "plugins/harness-mem/skills/harness-mem/SKILL.md",
    "tools/session-distill/SKILL.md",
)

# Substrings that, when present on an offending line, mark the line as a
# legitimate negative reference rather than a user instruction. Match is
# substring-only so the allowlist survives small wording tweaks.
ALLOWLIST: dict[str, tuple[str, ...]] = {
    "AGENTS.md": (
        # Section "Distill 的边界 (v2.0)" describes what v2.0 removed.
        "v2.0 删除了 `harness-mem distill` CLI 子命令",
    ),
    "tools/session-distill/SKILL.md": (
        # "不做的事" section explicitly warns against this CLI path.
        "不要求普通用户手动跑 `harness-mem ingest` 或 `harness-mem distill`",
    ),
}
"""Per-file allowlist. Empty / absent entries mean the file must be fully
clean of the deprecated pattern."""


def _scan_file(path: Path, allowed_lines: tuple[str, ...]) -> list[str]:
    """Return offending findings for ``path``.

    Each finding is ``"{rel_path}:{line_no}: {line_text}"`` so a failure
    message reads like a grep result.
    """
    findings: list[str] = []
    rel = path.relative_to(REPO_ROOT).as_posix()
    text = path.read_text(encoding="utf-8")
    for line_no, line in enumerate(text.splitlines(), start=1):
        if not DEPRECATED_DAILY.search(line):
            continue
        if any(allowed in line for allowed in allowed_lines):
            continue
        findings.append(f"{rel}:{line_no}: {line.strip()}")
    return findings


@pytest.mark.parametrize("target", SCAN_TARGETS)
def test_no_stale_daily_cli_in_user_docs(target: str) -> None:
    """User-facing docs MUST NOT teach removed daily CLI subcommands.

    The check is per-file so a regression in one doc surfaces as one
    failure, not as a single mega-failure that hides which file broke.
    """
    path = REPO_ROOT / target
    assert path.exists(), f"scan target missing: {target}"

    allowed_lines = ALLOWLIST.get(target, ())
    findings = _scan_file(path, allowed_lines)
    assert not findings, (
        "Found removed daily CLI subcommand(s) presented as user "
        "instructions. v2.0 removed `harness-mem wake/search/timeline/"
        "candidates/distill`; user docs must point at /hm:* slash "
        "commands, the harness-mem skill, or natural-language prompts "
        "instead. Offending lines:\n  " + "\n  ".join(findings)
    )


def test_maintenance_commands_still_documented() -> None:
    """Sanity check the allowlist isn't accidentally over-broad.

    If we ever stop teaching ``harness-mem quickstart`` / ``doctor`` /
    ``purge`` / ``maintenance`` / ``import`` in the user-facing READMEs,
    the deprecated-CLI scan above could pass for the wrong reason — a
    doc that no longer mentions any CLI at all is also "clean". This
    asserts at least one maintenance command surfaces in the top-level
    README or the plugin README so a future doc shrink is noticed.
    """
    readmes = (
        REPO_ROOT / "README.md",
        REPO_ROOT / "plugins" / "harness-mem" / "README.md",
    )
    pattern = re.compile(
        r"\bharness-mem\s+(" + "|".join(sorted(ALLOWED_MAINTENANCE)) + r")\b"
    )
    mentioned: set[str] = set()
    for readme in readmes:
        text = readme.read_text(encoding="utf-8")
        for match in pattern.finditer(text):
            mentioned.add(match.group(1))
    assert mentioned, (
        "Neither README.md nor plugins/harness-mem/README.md mentions any "
        "maintenance CLI command (quickstart / doctor / purge / "
        "maintenance / import). The stale-CLI scan above could now pass "
        "for a doc that simply says nothing — restore the maintenance "
        "command examples in the user-facing README."
    )
