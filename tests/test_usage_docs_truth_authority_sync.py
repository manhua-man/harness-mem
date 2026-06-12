from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plugin_readme_points_to_release_truth_authorities() -> None:
    plugin_readme = (
        REPO_ROOT / "plugins" / "harness-mem" / "README.md"
    ).read_text(encoding="utf-8")

    assert "版本说明见 [CHANGELOG.md](../../CHANGELOG.md)" in plugin_readme
    assert "本文聚焦 plugin 安装、集成与日常 IDE 使用方式" in plugin_readme
    assert "docs/roadmap-status.md" not in plugin_readme
    assert "公开状态页" not in plugin_readme


def test_best_practices_points_to_release_truth_authorities() -> None:
    best_practices = (REPO_ROOT / "docs" / "best-practices.md").read_text(encoding="utf-8")

    assert "版本说明见 `CHANGELOG.md`" in best_practices
    assert "本文聚焦使用建议与操作习惯" in best_practices
    assert "roadmap-status.md" not in best_practices
