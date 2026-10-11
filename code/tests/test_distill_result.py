"""Readable completion results must describe current rows, not proposed drafts."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from harness_mem.commands.distill_result import current_distill_result, project_distill_result
from harness_mem.commands.distill_result import distill_display_review, distill_unfinished_work


def test_current_results_exclude_superseded_and_foreign_material() -> None:
    points = [
        {"disposition": "add", "canonical_truth_ids": ["old"]},
        {"disposition": "replace", "canonical_truth_ids": ["new"],
         "replaced_truth_ids": ["old"]},
        {"disposition": "confirm", "canonical_truth_ids": ["foreign"]},
    ]
    entries = {"new": {"module_path": ["缓存"], "title": "保留有效缓存",
                       "statement": "缓存只保留已验证的当前条目。"}}
    result = project_distill_result(points, entries)
    assert result["knowledge_changes"] == [
        {"change": "replaced", "module": ["缓存"], "title": "保留有效缓存",
         "statement": "缓存只保留已验证的当前条目。"}
    ]
    assert result["removed_count"] == 1
    assert result["not_written"] == [{"reason": "已有相同知识", "count": 1}]


def test_result_preserves_plain_no_write_reasons_and_unfinished_work() -> None:
    result = project_distill_result(
        [{"disposition": "reject"}, {"disposition": "handoff"}], {},
        unfinished_work=["检查缓存超时行为", "检查缓存超时行为"],
    )
    assert result["knowledge_changes"] == []
    assert result["unfinished_work"] == ["检查缓存超时行为"]
    assert {row["reason"] for row in result["not_written"]} == {
        "证据或长期价值不足", "保留为未完成事项"
    }


@pytest.mark.parametrize("answer_status", ["ANSWERED", "PARTIAL"])
def test_deferred_display_cannot_claim_agent_success(answer_status) -> None:
    job = SimpleNamespace(
        completion_disposition="deferred",
        semantic_review={"final_outcome": "已验证并写入。", "unfinished_work": []},
        promotion_summary={"promoted": 0, "points": [{"disposition": "defer"}],
                           "answer_packet": {"answer_status": answer_status,
                                             "question": "继续验证审查偏好"}},
    )
    displayed = distill_display_review(job)
    assert "已验证并写入" not in displayed["final_outcome"]
    assert displayed["unfinished_work"] == ["继续处理：继续验证审查偏好"]
    assert displayed["last_turn_status"] == "unfinished"
    assert job.semantic_review["final_outcome"] == "已验证并写入。"


def test_handoff_display_deduplicates_agent_and_persisted_work() -> None:
    job = SimpleNamespace(semantic_review={"unfinished_work": ["核对证据"]},
                          promotion_summary={"unfinished_work": ["核对证据", "重新整理"]})
    assert distill_unfinished_work(job) == ["核对证据", "重新整理"]


@pytest.mark.parametrize("ids,replaced,current", [
    ([], [], []),
    (["missing"], [], []),
    (["new"], ["old"], ["new", "old"]),
])
def test_completion_refuses_missing_or_unremoved_current_rows(ids, replaced, current) -> None:
    entries = [SimpleNamespace(id=identity, to_dict=lambda: {}) for identity in current]
    store = SimpleNamespace(list_entries=AsyncMock(return_value=entries))
    backend = SimpleNamespace(structured_store=SimpleNamespace(knowledge_store=store))
    job = SimpleNamespace(project_name="project", promotion_summary={"points": [
        {"disposition": "replace", "canonical_truth_ids": ids, "replaced_truth_ids": replaced}
    ]})
    with pytest.raises(ValueError):
        asyncio.run(current_distill_result(backend, job))
    store.list_entries.assert_awaited_once_with("project")


@pytest.mark.parametrize("relative_path", [
    "harness_mem/commands/distill_result.py",
    "harness_mem/commands/distill_lifecycle.py",
    "harness_mem/commands/manual_distill.py",
    "harness_mem/commands/archive_distill.py",
    "harness_mem/storage/manual_batch_store.py",
    "harness_mem/commands/evidence_admission.py",
    "harness_mem/adapters/parser.py",
    "harness_mem/adapters/snapshot.py",
    "harness_mem/adapters/codex/adapter.py",
    "harness_mem/adapters/codex/archive_adapter.py",
    "harness_mem/rust_core.py",
    "harness_mem/mcp/distill_projection.py",
    "harness_mem/mcp/read_search_handlers.py",
    "harness_mem/mcp/read_projection.py",
    "harness_mem/read_knowledge.py",
    "harness_mem/storage/knowledge_store.py",
    "code/plugins/harness-mem/commands/hm/hm.md",
])
def test_readable_result_dependency_drift_invalidates_hook_evidence(monkeypatch, relative_path) -> None:
    from harness_mem.autonomous import worker

    target = Path(__file__).resolve().parents[2] / relative_path
    assert target in worker._RUNTIME_SOURCE_FILES
    before = worker.autonomous_runtime_fingerprint()
    read_bytes = Path.read_bytes

    def changed_bytes(path):
        value = read_bytes(path)
        return value + b"\nchanged-in-memory" if path == target else value

    monkeypatch.setattr(Path, "read_bytes", changed_bytes)
    assert worker.autonomous_runtime_fingerprint() != before
