#!/usr/bin/env python3
"""Session Distiller maintenance CLI entry point."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

_SKILL_ROOT = Path(__file__).resolve().parent.parent
if str(_SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(_SKILL_ROOT))

from lib.cli import build_parser, dispatch_command  # noqa: E402


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return dispatch_command(args, parser)


if __name__ == "__main__":
    sys.exit(main())
