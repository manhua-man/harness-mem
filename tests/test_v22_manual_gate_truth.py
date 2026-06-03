from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v22_docs_keep_manual_gate_open_while_packet_has_non_claude_gap() -> None:
    roadmap_v22x = (REPO_ROOT / "docs" / "roadmap-v22x.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    packet = (REPO_ROOT / "docs" / "v2-user-test-packet.md").read_text(encoding="utf-8")
    archived_tasks = (
        REPO_ROOT
        / "openspec"
        / "changes"
        / "archive"
        / "2026-05-25-v220-ai-ide-entry-loop"
        / "tasks.md"
    ).read_text(encoding="utf-8")

    assert "当前 gate 真值（2026-06-03）：" in packet
    assert "1 个 Claude Code client + 至少 1 个 non-Claude client" in packet
    assert "`2026-05-25` 的 Claude Code entry 已存在" in packet
    assert "Codex CLI 与 generic MCP 两条 non-Claude entry" in packet
    assert "## 2026-06-03 — Codex MCP smoke" in packet
    assert "## 2026-06-03 — Generic MCP JSON-RPC smoke" in packet
    assert "## 2026-06-03 — Generic MCP deeper workflow scenarios" in packet
    assert "## 2026-06-03 — Cursor runtime stack evidence" in packet
    assert "## 2026-06-03 — Cursor agent run-log evidence" in packet
    assert "generic MCP client 路径" in packet
    assert "HARNESS_MEM_DISABLE_EMBEDDINGS=1" in packet
    assert "auto_review_candidates(project_name=\\\"v22-generic-expanded\\\", apply=false)" in packet
    assert "S9 (`suggest_correction` one-shot supersede path)" in packet
    assert "Cursor runtime stack" in packet
    assert "agent exec startup" in packet
    assert "mcp-router" in packet
    assert "wake.json" in packet
    assert "f:\\huiben\\bazi-apps" in packet
    assert "mcp__harness-mem__search_memory" in packet
    assert "mcp__harness-mem__timeline" in packet
    assert "full 12-scenario matrix 已补齐" not in packet
    assert "OpenSpec `5.5` 手工 release gate 已完成" in roadmap_v22x
    assert "release gate 已闭环" in roadmap_v22x
    assert "不再阻塞 v2.2 闭环" in roadmap_v22x
    assert "agent exec startup" in roadmap_v22x
    assert "MCP cache" in roadmap_v22x
    assert "真实的 harness-mem MCP 调用 run log" in roadmap_v22x
    assert "S8 / S9 evidence" in roadmap_v22x
    assert "v2.2 runtime / contract 与 OpenSpec `5.5` 手工 release gate 已完成" in roadmap_v22x
    assert "v2.2.0 | 已完成（OpenSpec `5.5` gate 已过）" in roadmap_status
    assert "Claude Code gate entry" in roadmap_status
    assert "手工 release gate 已闭环" in roadmap_status
    assert "live stdio 的 S8 / S9 evidence" in roadmap_status
    assert "agent exec startup" in roadmap_status
    assert "工具 cache" in roadmap_status
    assert "真实的 Cursor agent run log" in roadmap_status
    assert "[x] 5.5 Manual v2.2 client test packet run with Claude Code plus at least one non-Claude client" in archived_tasks
