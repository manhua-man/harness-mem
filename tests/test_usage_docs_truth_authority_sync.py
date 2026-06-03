from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_plugin_readme_points_to_release_truth_authorities() -> None:
    plugin_readme = (
        REPO_ROOT / "plugins" / "harness-mem" / "README.md"
    ).read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 [F:\\memory-lab\\harness-mem\\docs\\roadmap-status.md]" in plugin_readme
    assert "[F:\\memory-lab\\harness-mem\\CHANGELOG.md]" in plugin_readme
    assert "本文聚焦 plugin 安装、集成与日常 IDE 使用方式，不单独充当当前实现真值" in plugin_readme


def test_best_practices_points_to_release_truth_authorities() -> None:
    best_practices = (REPO_ROOT / "docs" / "best-practices.md").read_text(encoding="utf-8")

    assert "当前发版状态、已完成切片和未做边界以 [roadmap-status.md](./roadmap-status.md) 与" in best_practices
    assert "`CHANGELOG.md` 为准" in best_practices
    assert "本文聚焦使用建议与操作习惯，不单独充当当前实现真值" in best_practices
