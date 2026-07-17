from __future__ import annotations

import harness_mem.mcp.distill_projection as distill_projection
from harness_mem.mcp.distill_projection import (
    build_distill_compact_outline,
    build_distill_semantic_outline,
    render_distill_exchange_windows,
)


def _long_session(exchange_count: int = 60) -> str:
    parts = ["# Session\n"]
    for index in range(1, exchange_count + 1):
        user = (
            f"routine request {index} "
            + "inspect implementation details and keep the result concise " * 6
        )
        outcome = (
            f"routine outcome {index} "
            + "verified the requested path and recorded the result " * 7
        )
        if index == 19:
            user = (
                "Storage migration v0.8.24 checksum conflict requires rollback. "
                "PRIVATE-PROOF-ALPHA must remain available for raw verification."
            )
            outcome = (
                "Migration failed before activation; canonical data was preserved "
                "and rollback remains required. PRIVATE-PROOF-OMEGA"
            )
        if index == exchange_count:
            user = "Finish the iteration without hiding unfinished work."
            outcome = "Blocked by the remaining security review; work is unfinished."
        parts.extend(
            [
                f"## Turn {index * 3 - 2} (user-{index})\n\nUser: {user}\n\n",
                f"## Turn {index * 3 - 1} (assistant-{index})\n\nAssistant: progress {index}\n\n",
                f"## Turn {index * 3} (assistant-final-{index})\n\nAssistant: {outcome}\n\n",
                'Tool: wait -> {"cell_id":"1"}\n\n',
                'Tool: pytest -> {"status":"passed"}\n\n',
            ]
        )
    return "".join(parts)


def test_compact_outline_covers_every_exchange_within_soft_budget() -> None:
    source = _long_session()
    compact, summary = build_distill_compact_outline(source, budget_tokens=3000)
    full, _full_summary = build_distill_semantic_outline(source)

    assert summary["projection"] == "exchange-outline-v2"
    assert summary["budget_state"] == "within_budget"
    assert summary["output_tokens"] <= 3000
    assert summary["exchange_count"] == 60
    assert compact.count("## E") == 60
    assert "s=VMPFC" in compact
    assert "PRIVATE-PROOF-ALPHA" in compact
    assert "PRIVATE-PROOF-OMEGA" in compact
    assert "s=PU" in compact
    assert "work is unfinished" in compact
    assert len(compact) < len(full)


def test_semantic_window_restores_complete_selected_exchange() -> None:
    source = _long_session()
    windows = render_distill_exchange_windows(source, [19])

    assert len(windows) == 1
    assert windows[0]["exchange_index"] == 19
    assert "PRIVATE-PROOF-ALPHA" in windows[0]["content"]
    assert "PRIVATE-PROOF-OMEGA" in windows[0]["content"]
    assert "migration_storage" in windows[0]["risk_flags"]


def test_compact_outline_preserves_evidence_anchors_with_fallback_counter(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        distill_projection,
        "_count_tokens",
        lambda value: len(value) // 4,
    )

    compact, summary = build_distill_compact_outline(
        _long_session(),
        budget_tokens=3000,
    )

    assert summary["budget_state"] == "within_budget"
    assert "PRIVATE-PROOF-ALPHA" in compact
    assert "PRIVATE-PROOF-OMEGA" in compact


def test_compact_outline_expands_instead_of_silently_dropping_coverage() -> None:
    source = _long_session(exchange_count=120)
    compact, summary = build_distill_compact_outline(source, budget_tokens=256)

    assert summary["budget_state"] == "expanded_for_manifest"
    assert summary["budget_reason"]
    assert compact.count("## E") == 120


def test_compact_outline_keeps_dense_risk_session_within_daily_budget() -> None:
    parts = ["# Dense risk session\n"]
    for index in range(1, 48):
        parts.append(
            f"User: 检查版本发布、存储迁移、隐私删除、失败冲突和剩余工作 {index}。\n\n"
            "Assistant: 已验证 checksum、rollback、security、timeout、stale 和 TODO；"
            f"需要按证据继续处理第 {index} 项。" * 8
            + "\n\n"
        )

    compact, summary = build_distill_compact_outline(
        "".join(parts),
        budget_tokens=3000,
    )

    assert summary["exchange_count"] == 47
    assert summary["risk_exchange_count"] == 47
    assert summary["budget_state"] == "within_budget"
    assert summary["output_tokens"] <= 3000
    assert compact.count("## E") == 47
