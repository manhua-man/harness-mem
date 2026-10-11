from __future__ import annotations

from datetime import datetime, timezone

from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.session_notes import render_session_note


def test_session_note_translates_internal_memory_and_audit_terms() -> None:
    completed_at = datetime.now(timezone.utc)
    job = SessionDistillJob(
        id="job-user-visible-note",
        idempotency_key="key-user-visible-note",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-user-visible-note",
        source_id="source-user-visible-note",
        source_revision="sha256:" + "a" * 64,
        status="completed",
        phase="done",
        completion_disposition="promoted",
        completed_at=completed_at,
        semantic_review={
            "session_summary": (
                "Stop Hook 已读取 2 条长期知识，但缺少 1 条 relation in truth."
            ),
            "final_user_request": "验证 outcome contract。",
            "final_outcome": (
                "job_bound_truth 和 sanitized_project_truth 都已通过。"
            ),
            "unfinished_work": [
                "解释 semantic memory、candidate 和 fail-closed。"
            ],
        },
        promotion_summary={
            "promoted": 1,
            "answer_packet": {
                "question": "验证 outcome contract 和 Stop Hook。",
                "answer_status": "ANSWERED",
                "core_conclusion": "promoted_items 可从 truth 读取。",
                "evidence_basis": ["user_statement"],
                "verified_at": completed_at.isoformat(),
                "promotion_status": "promoted",
                "destination_project": "demo",
                "promoted_items": [
                    {
                        "title": "Saved durable memory",
                        "fact": "The saved memory remains available.",
                    }
                ],
            },
        },
    )

    note = render_session_note(job)

    for internal_term in (
        "Stop Hook",
        "长期知识",
        "relation",
        "truth",
        "job_bound_truth",
        "sanitized_project_truth",
        "semantic memory",
        "outcome contract",
        "promoted_items",
        "fail-closed",
        "candidate",
    ):
        assert internal_term not in note
    assert "会话结束自动触发流程" in note
    assert "长期记忆" in note
    assert "关系记忆" in note
    assert "1 条关系记忆" in note
    assert "按原处理记录回查" in note
    assert "清理原文后按项目记忆回查" in note
    assert "结果验收" in note
    assert "写入的长期记忆列表" in note
    assert "安全性不明时停止操作" in note
    assert "待审记忆" in note
    assert "<!-- harness-mem audit:" in note


def test_partial_note_uses_runtime_evidence_and_preserved_work() -> None:
    job = SessionDistillJob(
        id="partial-job", idempotency_key="partial-key", project_name="demo",
        project_root="F:/demo", client="codex", session_id="partial-session",
        source_id="partial-source", source_revision="sha256:" + "a" * 64,
        status="completed", completion_disposition="deferred",
        semantic_review={"session_summary": "Organized future audit preferences.",
                         "final_outcome": "已验证全部内容。", "unfinished_work": []},
        promotion_summary={"promoted": 0, "deferred": 1,
                           "points": [{"disposition": "defer"}],
                           "unfinished_work": ["继续验证未来审查必须逐项列出的偏好。"],
                           "answer_packet": {"answer_status": "PARTIAL",
                                             "core_conclusion": "证据不完整，本次未写入。"}},
    )
    note = render_session_note(job)
    assert "已验证全部内容" not in note
    assert "证据不完整，本次未写入。" in note
    assert "继续验证未来审查必须逐项列出的偏好。" in note
    assert "无需长期记忆" not in note
    assert "## 未完成工作\n\n- 无。" not in note


def test_rejected_point_does_not_invent_pending_work_beside_a_saved_point() -> None:
    job = SessionDistillJob(
        id="mixed-job", idempotency_key="mixed-key", project_name="demo",
        project_root="F:/demo", client="codex", session_id="mixed-session",
        source_id="mixed-source", source_revision="sha256:" + "a" * 64,
        status="completed", completion_disposition="promoted",
        semantic_review={"session_summary": "Organized saved and rejected facts.",
                         "final_outcome": "Everything is verified.", "unfinished_work": []},
        promotion_summary={"promoted": 1, "rejected": 1,
                           "points": [{"disposition": "add"}, {"disposition": "reject"}],
                           "answer_packet": {"answer_status": "PARTIAL",
                                             "core_conclusion": "One fact was saved; the other was rejected."}},
    )
    note = render_session_note(job)
    assert "Everything is verified." not in note
    assert "- 结果：部分内容写入长期记忆" in note
    assert "仍需处理" not in note
    assert "## 未完成工作\n\n- 无。" in note
