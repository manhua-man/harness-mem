"""One explicit seven-host contract shared by cross-surface tests."""

from __future__ import annotations

from typing import NamedTuple


class HostContract(NamedTuple):
    name: str
    capture_mode: str
    native_cleanup_mode: str
    command_hint: str


HOST_CONTRACTS = (
    HostContract("claude-code", "file", "file", "/hm"),
    HostContract("codex", "file", "file", "$hm"),
    HostContract("cursor", "file", "file", "/hm"),
    HostContract("grok", "file", "file", "/hm"),
    HostContract("hermes", "mixed", "source_dependent", "/hm"),
    HostContract("opencode", "shared_container", "unsupported", "/hm"),
    HostContract("antigravity", "mixed", "source_dependent", "/hm"),
)

HOST_NAMES = tuple(contract.name for contract in HOST_CONTRACTS)
HOST_CAPABILITY_CASES = tuple(
    (contract.name, contract.capture_mode, contract.native_cleanup_mode)
    for contract in HOST_CONTRACTS
)
HOST_COMMAND_HINT_CASES = tuple(
    (contract.name, contract.command_hint) for contract in HOST_CONTRACTS
)
