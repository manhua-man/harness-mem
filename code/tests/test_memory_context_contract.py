"""Context compaction must not remove schema constraints or verification gates."""

from __future__ import annotations

import hashlib
import json
from typing import Any

import pytest

from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, _SCHEMAS


def _without_annotations(value: Any, *, field_map: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_annotations(item, field_map=key in {"properties", "$defs"} and not field_map)
            for key, item in value.items()
            if field_map or key not in {"description", "title"}
        }
    if isinstance(value, list):
        return [_without_annotations(item) for item in value]
    return value


def test_context_compaction_preserves_complete_input_contract() -> None:
    # Freeze the reviewed November contract with exact native evidence and
    # archive actions, typed manual judgments and multipart retrieval cursors.
    # A property named title stays in the contract, unlike a schema label.
    contract = {name: _without_annotations(_SCHEMAS[name]["input_schema"])
                for name in sorted(PUBLIC_MCP_TOOL_NAMES)}
    arguments = contract["govern_memory"]["properties"]["arguments"]["properties"]
    for values in (arguments["evidence_basis"]["enum"],
                   arguments["verification_refs"]["items"]["properties"]["kind"]["enum"]):
        assert values == ["repository", "user_statement", "transcript", "source_report"]
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert len(contract) == 20
    assert hashlib.sha256(encoded.encode()).hexdigest() == (
        "bf10c64f1d6abea9f5fd01aa967ba6a4ab8199bb5221461099fab1456a0a5e7f"
    )


def test_complete_catalog_context_has_bounded_text_size() -> None:
    tiktoken = pytest.importorskip("tiktoken")
    from harness_mem.mcp.server import TOOLS
    from harness_mem.mcp.tool_registry import list_tools_result

    encoding = tiktoken.get_encoding("o200k_base")
    # Include runtime annotations, surface and count, not just exported schemas.
    catalog = list_tools_result(TOOLS)
    assert catalog["tool_count"] == len(catalog["tools"]) == 20
    token_count = len(encoding.encode(json.dumps(catalog, ensure_ascii=False)))
    assert token_count <= 21_593
