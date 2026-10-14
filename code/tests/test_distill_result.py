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
    assert result["organization_status"] == "partial"
    assert {row["reason"] for row in result["not_written"]} == {
        "证据或长期价值不足", "保留为未完成事项"
    }


@pytest.mark.parametrize("disposition", ["defer", "handoff", "conflict"])
def test_unresolved_point_is_partial_even_without_explicit_work_list(disposition) -> None:
    result = project_distill_result([{"disposition": disposition}], {})
    assert result["organization_status"] == "partial"
    assert result["knowledge_changes"] == []


def test_pending_work_does_not_hide_successfully_saved_knowledge() -> None:
    result = project_distill_result(
        [{"disposition": "add", "canonical_truth_ids": ["current"]}],
        {"current": {"module_path": ["cache"], "title": "Current cache", "statement": "Keep valid cache."}},
        unfinished_work=["Check timeout behavior"],
    )
    assert result["organization_status"] == "partial"
    assert result["knowledge_changes"][0]["statement"] == "Keep valid cache."
    assert result["unfinished_work"] == ["Check timeout behavior"]


def test_compact_completion_keeps_partial_saved_results_and_note_proof() -> None:
    from harness_mem.mcp.distill_handlers import _compact_finalize_result

    saved = project_distill_result(
        [{"disposition": "add", "canonical_truth_ids": ["current"]}],
        {"current": {"module_path": ["cache"], "title": "Current cache", "statement": "Keep valid cache."}},
        unfinished_work=["Check timeout behavior"],
    )
    result = _compact_finalize_result({
        "success": True, "distill_job_id": "job", "distill_status": "completed", **saved,
        "session_summary": {"session_id": "session", "unfinished_work": saved["unfinished_work"]},
        "note": {"path": "revision.md", "latest_path": "latest.md", "sha256": "digest", "exists": True},
        "promotion": {"points": ["internal detail"]}, "answer_packet": {"point_results": ["duplicate"]},
    })
    assert all(result[key] == value for key, value in saved.items())
    assert result["organization_status"] == "partial"
    assert result["session_id"] == "session"
    assert result["note"] == {"path": "revision.md", "latest_path": "latest.md", "sha256": "digest"}
    assert "promotion" not in result and "answer_packet" not in result


@pytest.mark.parametrize("success,status", [(False, "reviewing"), (False, "completed"), (True, "retryable")])
def test_compact_finalization_preserves_failure_and_unfinished_state(success, status) -> None:
    from harness_mem.mcp.distill_handlers import _compact_finalize_result

    result = {"success": success, "distill_status": status, "distill_job_id": "job",
              "error": "Missing proof", "reason_codes": ["proof_missing"],
              "unfinished_work": ["Retry verification"], "next_step": "prepare_session_distill"}
    assert _compact_finalize_result(result) is result


def test_compact_saved_result_keeps_actionable_cleanup_failure() -> None:
    from harness_mem.mcp.distill_handlers import _compact_finalize_result

    cleanup = {"status": "partial_failure", "receipt_id": "receipt", "reason_codes": ["cleanup_failed"]}
    result = _compact_finalize_result({
        "success": True, "distill_status": "completed", "source_cleanup": cleanup,
        "organization_status": "partial", "knowledge_changes": [], "unfinished_work": ["Retry cleanup"],
    })
    assert result["source_cleanup"] == cleanup and result["unfinished_work"] == ["Retry cleanup"]


@pytest.mark.parametrize("disposition", ["confirm", "no_write", "reject"])
def test_decided_no_write_without_pending_work_is_completed(disposition) -> None:
    assert project_distill_result([{"disposition": disposition}], {})["organization_status"] == "completed"


def test_preserved_handoff_reason_is_partial_without_points() -> None:
    result = project_distill_result([], {}, empty_reasons=["保留为未完成事项"])
    assert result["organization_status"] == "partial"


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
    "harness_mem/capture_policy.py",
    "harness_mem/config/merge.py",
    "harness_mem/adapters/codex/adapter.py",
    "harness_mem/adapters/codex/archive_adapter.py",
    "harness_mem/rust_core.py",
    "harness_mem/mcp/distill_projection.py",
    "harness_mem/mcp/read_search_handlers.py",
    "harness_mem/mcp/read_projection.py",
    "harness_mem/read_knowledge.py",
    "harness_mem/storage/knowledge_store.py",
    "code/plugins/harness-mem/commands/hm/hm.md",
    "code/tools/hm-distill/SKILL.md",
    "code/tools/hm-distill/references/distillation-rules.md",
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
