"""Guard the malformed category path observed in a real Codex MCP call."""
from __future__ import annotations

import asyncio

import pytest

from harness_mem.mcp import governance_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


@pytest.mark.parametrize("topic_path", ["用户偏好/导出", {"module": "用户偏好"}, 7])
def test_govern_suggest_rejects_non_array_topic_before_candidate_write(
    tmp_path, monkeypatch, topic_path,
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    monkeypatch.setattr(governance_handlers, "_get_backend", lambda: backend)
    monkeypatch.setattr(governance_handlers, "_distill_candidate_id", lambda *_a, **_k: "native-codex-topic-path")
    try:
        result = governance_handlers.tool_govern_memory("suggest", {
            "kind": "memory", "project_name": "demo", "category": "preference",
            "content": "本测试项目的导出格式使用 TSV。", "source": "native user session",
            "canonical_title": "导出格式使用 TSV", "topic_path": topic_path,
            "assimilation_disposition": "add", "assimilation_reason": "Explicit durable preference",
        })
        assert result["success"] is False
        assert "topic_path" in result["error"] and "array" in result["error"]
        assert asyncio.run(backend.structured_store.knowledge_store.get_candidate("native-codex-topic-path")) is None
    finally:
        asyncio.run(backend.close())


def test_assimilation_keeps_whole_category_names() -> None:
    result = governance_handlers._assimilation_fields(
        assimilation_disposition="add", assimilation_reason="user statement",
        assimilation_target_ids=None, target_knowledge=None,
        canonical_title="导出格式使用 TSV", topic_path=["用户偏好", "导出"],
    )
    assert result["topic_path"] == ["用户偏好", "导出"]
