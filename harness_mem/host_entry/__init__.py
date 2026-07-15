"""Hook host-entry adapter package.

The host entry is invoked as ``harness-mem-hook`` by IDE hooks.
It maps explicit hook actions to in-process runtime calls:

* ``dream-end`` emits structured JSON for end-of-session dream maintenance.
* ``wake-start`` emits plaintext wake context for session-start injection.

This package re-exports the output-shape and exit-code surfaces so callers can
``from harness_mem.host_entry import HostEntryResult, ExitCode`` without reaching
into the submodules.
"""

from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult

__all__ = [
    "ExitCode",
    "HostEntryResult",
]
