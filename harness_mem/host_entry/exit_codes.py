"""Process exit codes for the host entry (v2.4.1 Req 2.7, Req 5.6, design "ExitCode").

``SUCCESS`` covers both ``needs_distill`` / ``completed`` (the reflection
completed something useful) and ``skipped_default_off`` (the reflection was
correctly suppressed). ``REFLECTION_FAILED`` covers both ``failed`` (terminal)
and ``retryable`` (transient) — hook scripts branch on the JSON ``status`` field
to disambiguate. There is no exit code 1: stdlib argparse uses 2 for usage
errors, and we follow that convention rather than overloading 1.
"""

from __future__ import annotations

from enum import IntEnum

__all__ = ["ExitCode"]


class ExitCode(IntEnum):
    """Stable process exit codes emitted by the host entry."""

    SUCCESS = 0
    ARG_VALIDATION_ERROR = 2
    CONFIG_LOAD_ERROR = 3
    REFLECTION_FAILED = 4
