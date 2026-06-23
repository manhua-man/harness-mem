"""Host-entry adapter package for the v2.4.1 host-triggered reflection contract.

The host entry is invoked as ``python -m harness_mem.host_entry`` by IDE hooks,
cron jobs, and external schedulers. It is an *adapter* that maps a small CLI to a
single in-process call to v2.4.0 ``reflection_once`` and serializes the result as
a structured JSON document on stdout. All business logic stays in
``harness_mem.commands.reflection_jobs``.

This package re-exports the output-shape and exit-code surfaces so callers can
``from harness_mem.host_entry import HostEntryResult, ExitCode`` without reaching
into the submodules.
"""

from harness_mem.host_entry.exit_codes import ExitCode
from harness_mem.host_entry.output import HostEntryResult, parse_error_payload

__all__ = [
    "ExitCode",
    "HostEntryResult",
    "parse_error_payload",
]
