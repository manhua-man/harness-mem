"""Process exit codes for the hook host entry.

``SUCCESS`` covers completed and skipped hook actions. ``HOOK_FAILED`` is used
when a dream maintenance tick fails after argument and config validation. There
is no exit code 1: stdlib argparse uses 2 for usage errors, and we follow that
convention rather than overloading 1.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["ExitCode"]


class ExitCode(IntEnum):
    """Stable process exit codes emitted by the host entry."""

    SUCCESS = 0
    ARG_VALIDATION_ERROR = 2
    CONFIG_LOAD_ERROR = 3
    HOOK_FAILED = 4
