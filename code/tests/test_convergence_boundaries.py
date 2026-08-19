from __future__ import annotations

from pathlib import Path

from harness_mem.config.merge import PUBLIC_CONFIG_KEY_PATHS
from harness_mem.mcp.tool_handlers import build_tool_handlers
from harness_mem.mcp.tool_specs import (
    PUBLIC_MCP_TOOL_NAMES,
    TOOL_CLUSTERS,
    _SCHEMAS,
)
from harness_mem.version import legacy_storage_support_policy


def test_0_9_x_public_mcp_contract_is_exactly_27_tools() -> None:
    expected = set(PUBLIC_MCP_TOOL_NAMES)
    assert len(expected) == 27
    assert set(_SCHEMAS) == expected
    assert set(TOOL_CLUSTERS) == expected
    assert set(build_tool_handlers()) == expected


def test_processed_cleanup_and_privacy_erase_keep_distinct_owners() -> None:
    root = Path(__file__).resolve().parents[2]
    processed = (root / "harness_mem" / "processed_source_cleanup.py").read_text(
        encoding="utf-8"
    )
    privacy = (root / "harness_mem" / "data_lifecycle.py").read_text(
        encoding="utf-8"
    )
    finalize = (root / "harness_mem" / "mcp" / "distill_handlers.py").read_text(
        encoding="utf-8"
    )
    erase_cli = (root / "harness_mem" / "commands" / "purge.py").read_text(
        encoding="utf-8"
    )

    assert "hard_delete(" not in processed
    assert "cleanup_processed_source(" not in privacy
    assert "cleanup_processed_source(" in finalize
    assert "hard_delete(" in erase_cli
    assert 'native_source_mode="erase"' in erase_cli
    assert [key for key in PUBLIC_CONFIG_KEY_PATHS if "delete" in key] == [
        "distill.delete_source_after_complete"
    ]


def test_legacy_storage_reader_exit_policy_has_dual_removal_gate() -> None:
    policy = legacy_storage_support_policy()

    assert policy == {
        "deprecated_since": "0.9.6",
        "deprecated_on": "2026-07-30",
        "supported_through": "0.9.x",
        "earliest_removal_version": "1.0.0",
        "earliest_removal_date": "2027-01-31",
    }
