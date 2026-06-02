from __future__ import annotations

from pathlib import Path

from harness_mem.config.merge import _RECOGNIZED_KEYS


REPO_ROOT = Path(__file__).resolve().parents[1]


def _text(relative: str) -> str:
    return (REPO_ROOT / relative).read_text(encoding="utf-8")


def test_v24_roadmap_matches_shipped_config_loader_scope() -> None:
    roadmap_v24 = _text("docs/roadmap-v24.md")

    for key_path, _attr, _allowed, _default in _RECOGNIZED_KEYS:
        assert key_path in roadmap_v24

    assert "`project_name`" not in roadmap_v24
    assert "active_project.txt" not in roadmap_v24
    assert "preserve unrecognized tables in extras" in roadmap_v24


def test_v24_roadmap_matches_single_reflection_job_model() -> None:
    roadmap_v24 = _text("docs/roadmap-v24.md")

    assert "`ReflectionJob` schema" in roadmap_v24
    assert "`ReflectionJob` / `ReviewJob` schema" not in roadmap_v24
    assert "`review` 只是 phase，不是单独 job 类型" in roadmap_v24
