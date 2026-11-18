"""Context compaction must not remove schema constraints or verification gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, _SCHEMAS

ROOT = Path(__file__).resolve().parents[2]


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


@pytest.mark.parametrize("relative", [
    "code/plugins/harness-mem/commands/hm/hm.md",
    "code/tools/hm-distill/SKILL.md",
])
def test_both_manual_guides_reuse_only_fresh_verified_readback(relative: str) -> None:
    text = (ROOT / relative).read_text(encoding="utf-8")
    assert "readback_verified=true" in text
    assert "knowledge_changes" in text
    assert "新冲突" in text
    assert "普通检索" in text
    assert "同一 `batch_id`" in text


def test_compact_entry_reuses_context_without_capping_missing_reads() -> None:
    text = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    for guard in ("context_injection", "完整 `statement`", "截断", "源变", "缺答",
                  "不限必要检索次数", "明确范围不扩大", "完整读取原生来源", "逐项对照"):
        assert guard in text


def test_complete_catalog_and_entry_context_have_bounded_text_size() -> None:
    tiktoken = pytest.importorskip("tiktoken")
    from harness_mem.mcp.server import TOOLS
    from harness_mem.mcp.tool_registry import list_tools_result

    encoding = tiktoken.get_encoding("o200k_base")
    # Include runtime annotations, surface and count, not just exported schemas.
    catalog = list_tools_result(TOOLS)
    assert catalog["tool_count"] == len(catalog["tools"]) == 20
    entry = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    # November 2026 baseline after removing generated schema titles. Retain
    # the typed verification inputs and the full source guidance in the budget.
    measured = {
        "MCP catalog": (len(encoding.encode(json.dumps(catalog, ensure_ascii=False))), 21_593),
        "hm entry": (len(encoding.encode(entry)), 2_920),
    }
    over_budget = [f"{name}: {actual:,} > {limit:,} tokens"
                   for name, (actual, limit) in measured.items() if actual > limit]
    assert not over_budget, "\n".join(over_budget)
