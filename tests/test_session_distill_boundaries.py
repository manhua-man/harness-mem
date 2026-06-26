from __future__ import annotations

import sys
from pathlib import Path

SESSION_DISTILL_ROOT = Path(__file__).resolve().parents[1] / "tools" / "session-distill"
sys.path.insert(0, str(SESSION_DISTILL_ROOT))

from lib.distill_rules import map_candidate_readiness  # noqa: E402
from lib.guardrails import suggest_only_violations  # noqa: E402
from lib.harness_mem_export import build_suggest_calls  # noqa: E402
from lib.models import CandidateDraft, Packet, PacketAudit  # noqa: E402
from lib.review_policy import default_review_policy, plan_review  # noqa: E402
from lib.summary import default_distill_summary  # noqa: E402


def test_harness_mem_export_only_suggests_and_skips_local_drafts() -> None:
    packet = Packet(
        session_id="session-1",
        project_name="demo",
        audit=PacketAudit(coverage="high"),
    )
    drafts = [
        CandidateDraft(
            kind="memory_entry",
            category="decision",
            content="Use preview review before durable memory writes.",
            source_session_id="session-1",
            evidence=("turn-1",),
        ),
        CandidateDraft(
            kind="rule",
            content="Conflict candidates require manual review.",
            source_session_id="session-1",
            evidence=("turn-2",),
            readiness="needs-conflict-review",
        ),
        CandidateDraft(
            kind="memory_entry",
            content="A one-off local note should stay out of candidates.",
            source_session_id="session-1",
            readiness="local-only",
        ),
    ]

    calls = build_suggest_calls(drafts, packet)
    tool_names = [call.tool_name for call in calls]

    assert tool_names == ["suggest_memory_entry", "suggest_rule"]
    assert suggest_only_violations(tool_names) == []
    assert all(not name.startswith(("confirm_", "reject_", "replace_")) for name in tool_names)
    assert calls[1].arguments["blocked_reason"] == "conflict_review_required"
    assert calls[1].arguments["requires_manual_review"] is True


def test_readiness_mapping_blocks_partial_conflict_and_local_only() -> None:
    ready = CandidateDraft(
        kind="memory_entry",
        content="Stable reusable behavior.",
        source_session_id="session-1",
    )
    partial = map_candidate_readiness(ready, PacketAudit(coverage="partial"))

    assert partial.readiness == "needs-raw-review"
    assert partial.exportable is True
    assert partial.auto_apply_allowed is False
    assert partial.blocked_reason == "raw_review_required"

    conflict = map_candidate_readiness(
        CandidateDraft(
            kind="rule",
            content="Two sources disagree.",
            source_session_id="session-1",
            readiness="needs-conflict-review",
        ),
        PacketAudit(coverage="high"),
    )

    assert conflict.exportable is True
    assert conflict.requires_manual_review is True
    assert conflict.auto_apply_allowed is False
    assert conflict.blocked_reason == "conflict_review_required"

    local_only = map_candidate_readiness(
        CandidateDraft(
            kind="memory_entry",
            content="Local breadcrumb only.",
            source_session_id="session-1",
            readiness="local-only",
        ),
        PacketAudit(coverage="high"),
    )

    assert local_only.exportable is False
    assert local_only.auto_apply_allowed is False
    assert local_only.skip_reason == "local_only"


def test_default_review_policy_is_preview_only() -> None:
    policy = default_review_policy()
    packet = Packet(session_id="session-1", audit=PacketAudit(coverage="high"))
    drafts = [
        CandidateDraft(
            kind="memory_entry",
            content="Stable reusable behavior.",
            source_session_id="session-1",
        )
    ]

    review_plan = plan_review(drafts, packet, policy)

    assert policy.mode == "preview"
    assert policy.apply is False
    assert policy.preview_only is True
    assert review_plan.preview_only is True
    assert review_plan.decisions[0].auto_apply_allowed is True


def test_default_distill_summary_reports_review_boundaries() -> None:
    packet = Packet(
        session_id="session-1",
        project_name="demo",
        audit=PacketAudit(coverage="partial", compaction_events=1),
    )
    drafts = [
        CandidateDraft(
            kind="memory_entry",
            content="Ready after review.",
            source_session_id="session-1",
        ),
        CandidateDraft(
            kind="rule",
            content="Conflict needs a human.",
            source_session_id="session-1",
            readiness="needs-conflict-review",
        ),
        CandidateDraft(
            kind="memory_entry",
            content="Keep local.",
            source_session_id="session-1",
            readiness="local-only",
        ),
        CandidateDraft(
            kind="task_handoff",
            content="Ephemeral handoff.",
            source_session_id="session-1",
            readiness="ephemeral",
        ),
    ]
    review_plan = plan_review(drafts, packet, default_review_policy())

    summary = default_distill_summary(
        packet=packet,
        drafts=drafts,
        review_plan=review_plan,
    )

    assert "auto-review mode: preview" in summary
    assert "raw review required: yes" in summary
    assert "blocked/raw-review: 1" in summary
    assert "conflict-review: 1" in summary
    assert "local-only: 1" in summary
    assert "ephemeral: 1" in summary
    assert "manual review required: 1" in summary
    assert "no durable memory was confirmed" in summary
