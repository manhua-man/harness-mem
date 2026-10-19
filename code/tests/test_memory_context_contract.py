"""Context compaction must not remove schema constraints or verification gates."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from harness_mem.mcp.tool_specs import PUBLIC_MCP_TOOL_NAMES, _SCHEMAS

ROOT = Path(__file__).resolve().parents[2]


def _without_descriptions(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _without_descriptions(item)
                for key, item in value.items() if key != "description"}
    if isinstance(value, list):
        return [_without_descriptions(item) for item in value]
    return value


def test_context_compaction_preserves_complete_input_contract() -> None:
    # Frozen before the 2026-10-15 annotation-only compaction. Types, names,
    # defaults, bounds, required fields and additionalProperties remain.
    # The operator subsequently authorized one bounded source_report evidence
    # type. Prove that removing ONLY those two explicit enum extensions yields
    # the exact original input contract; do not silently rebaseline its hash.
    contract = {name: _without_descriptions(_SCHEMAS[name]["input_schema"])
                for name in sorted(PUBLIC_MCP_TOOL_NAMES)}
    arguments = contract["govern_memory"]["properties"]["arguments"]["properties"]
    for values in (arguments["evidence_basis"]["enum"],
                   arguments["verification_refs"]["items"]["properties"]["kind"]["enum"]):
        assert values == ["repository", "user_statement", "transcript", "source_report"]
        values.remove("source_report")
    encoded = json.dumps(contract, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert len(contract) == 20
    assert hashlib.sha256(encoded.encode()).hexdigest() == (
        "ddfef75a834713c66b6777d5a019c896d477459fd6da56bb2b5c7b4f28211af8"
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
    assert "普通搜索" in text
    assert "同一 `batch_id`" in text


def test_compact_entry_reuses_context_without_capping_missing_reads() -> None:
    text = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    for guard in ("context_injection", "完整事实", "截断", "来源变化", "缺失答案",
                  "不以固定次数限制", "范围不得扩大", "原生会话", "完整来源"):
        assert guard in text


def test_complete_catalog_and_entry_context_have_bounded_text_size() -> None:
    tiktoken = pytest.importorskip("tiktoken")
    from harness_mem.mcp.server import TOOLS
    from harness_mem.mcp.tool_registry import list_tools_result

    encoding = tiktoken.get_encoding("o200k_base")
    # Include runtime annotations, surface and count, not just exported schemas.
    catalog = list_tools_result(TOOLS)
    assert catalog["tool_count"] == len(catalog["tools"]) == 20
    # Add the full authorized report contract and typed enum, not a content cut.
    assert len(encoding.encode(json.dumps(catalog, ensure_ascii=False))) <= 7400
    entry = (ROOT / "code/plugins/harness-mem/commands/hm/hm.md").read_text(encoding="utf-8")
    # The canonical entry already retains complete source/scope instructions.
    # Keep that guidance intact instead of trimming it to the stale 1k target.
    assert len(encoding.encode(entry)) <= 1200
