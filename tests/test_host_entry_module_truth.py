from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_v24_roadmap_uses_shipped_host_entry_module() -> None:
    roadmap_v24 = _text("docs/roadmap-v24.md")

    assert "python -m harness_mem.host_entry" in roadmap_v24
    assert "--source ide_hook" in roadmap_v24
    assert "python -m harness_mem.host " not in roadmap_v24
    assert "harness_mem.<host_entry>" not in roadmap_v24
    assert "host_entry reflection_once" not in roadmap_v24
