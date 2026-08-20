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
