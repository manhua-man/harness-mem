"""One explicit seven-host contract shared by cross-surface tests."""

from __future__ import annotations

from typing import NamedTuple


class HostContract(NamedTuple):
    name: str
    capture_mode: str
    native_cleanup_mode: str


HOST_CONTRACTS = (
    HostContract("claude-code", "file", "file"),
    HostContract("codex", "file", "file"),
    HostContract("cursor", "file", "file"),
    HostContract("grok", "file", "file"),
    HostContract("hermes", "mixed", "source_dependent"),
    HostContract("opencode", "shared_container", "unsupported"),
    HostContract("antigravity", "mixed", "source_dependent"),
)

HOST_NAMES = tuple(contract.name for contract in HOST_CONTRACTS)
HOST_CAPABILITY_CASES = tuple(
    (contract.name, contract.capture_mode, contract.native_cleanup_mode)
    for contract in HOST_CONTRACTS
)
