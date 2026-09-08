"""Synchronize checked-in host entry mirrors from the canonical plugin command.

The host paths are intentionally different because each host discovers commands
in a different place. Their behavior is not separate, though: this script keeps
the checked-in project mirrors derived from the one plugin command source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Mapping

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "code/plugins/harness-mem/commands/hm/hm.md"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness_mem.integration.command_sync import render_primary_command  # noqa: E402

# These files are project-local discovery mirrors. The plugin command remains
# the source; only the two skill hosts need rendered skill front matter.
RAW_MIRRORS = (
    ".agents/workflows/hm.md",
    ".claude/commands/hm.md",
    ".cursor/commands/hm.md",
    ".opencode/commands/hm.md",
)
SKILL_MIRRORS = (
    ".agents/skills/hm/SKILL.md",
    ".grok/skills/hm/SKILL.md",
)


def expected_mirrors() -> Mapping[Path, str]:
    """Return every checked-in mirror and its canonical rendered content."""

    raw = SOURCE.read_text(encoding="utf-8")
    skill = render_primary_command(SOURCE, "codex")
    return {
        **{ROOT / path: raw for path in RAW_MIRRORS},
        **{ROOT / path: skill for path in SKILL_MIRRORS},
    }


def sync(*, check: bool = False) -> tuple[Path, ...]:
    """Write mirrors, or return stale paths when ``check`` is true."""

    stale: list[Path] = []
    for path, expected in expected_mirrors().items():
        actual = path.read_text(encoding="utf-8") if path.exists() else None
        if actual == expected:
            continue
        stale.append(path)
        if not check:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    return tuple(stale)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync project hm mirrors from the canonical plugin command."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only report stale mirrors and return a failure status",
    )
    args = parser.parse_args()
    stale = sync(check=args.check)
    if not stale:
        print("hm mirrors are synchronized")
        return 0
    for path in stale:
        print(path.relative_to(ROOT))
    if args.check:
        return 1
    print("hm mirrors synchronized")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
