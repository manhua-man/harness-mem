from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_v31_docs_are_implemented_and_indexed() -> None:
    docs_readme = (REPO_ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    roadmap_status = (REPO_ROOT / "docs" / "roadmap-status.md").read_text(encoding="utf-8")
    roadmap_v31 = (REPO_ROOT / "docs" / "roadmap-v31.md").read_text(encoding="utf-8")

    assert "roadmap-v31.md" in docs_readme
    assert "Auto Dream Memory Maintenance" in docs_readme
    assert "已发布的 v3.1-v4.5.0" in docs_readme
    assert "| v3.1.0 | 已发布：Auto Dream Memory Maintenance |" in roadmap_status
    assert "| v3.1.x | 已发布：Auto Dream Memory Maintenance |" in roadmap_status
    assert "v3.4.4 已发布完整 v3.4.x" in roadmap_status
    assert "当前版本 v4.5.0 已完成剩余 v4.0.x、v4.1.x、v4.2.x、v4.3.x、v4.4 和 v4.5 runtime foundation" in roadmap_status
    assert "| Auto Dream | `/hm:dream` 读取 DreamRun 账本" in roadmap_status
    assert "| v3.1.x Auto Dream Memory Maintenance | 规划中，未实现 |" not in roadmap_status
    assert "| v3.1.x | Auto Dream Memory Maintenance" in roadmap_status
    assert "v3.1 的默认关闭 Auto Dream / DreamRun 账本 / handle-all / undo 面" in roadmap_status
    assert "v3.2 的" in roadmap_status
    assert "v3.3 的" in roadmap_status
    assert "v3.4.x 的" in roadmap_status
    assert "> 状态：已发布，当前版本 3.1.0。" in roadmap_v31
    assert "> 状态：规划中，未实现。" not in roadmap_v31
    assert "没有 `pending_review`。" in roadmap_v31
    assert "默认关闭。用户显式开启后才自动跑。" in roadmap_v31
