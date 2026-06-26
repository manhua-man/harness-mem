from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.integration.command_sync import (
    known_command_names,
    resolve_command_names,
    source_path_for_command,
    sync_slash_commands,
)


def _write_command_sources(source_dir: Path) -> None:
    groups = {
        "daily": ("status", "wake", "search", "search-all", "distill", "review", "dream"),
        "maintenance": ("mark", "prune"),
    }
    for command in known_command_names():
        for group, commands in groups.items():
            if command in commands:
                command_dir = source_dir / group
                command_dir.mkdir(parents=True, exist_ok=True)
                break
        else:
            raise AssertionError(f"missing group for command {command}")
        (command_dir / f"{command}.md").write_text(
            f"# /hm:{command}\n",
            encoding="utf-8",
        )


def test_command_profiles_keep_daily_as_default_and_gate_optional_groups() -> None:
    assert resolve_command_names(profile="daily") == (
        "status",
        "wake",
        "search",
        "search-all",
        "distill",
        "review",
        "dream",
    )
    assert "mark" in resolve_command_names(profile="maintenance")
    assert "prune" in resolve_command_names(profile="maintenance")
    assert resolve_command_names(profile="full") == (
        "status",
        "wake",
        "search",
        "search-all",
        "distill",
        "review",
        "dream",
        "mark",
        "prune",
    )
    assert "dream" in resolve_command_names(profile="maintenance")
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="labs")
    with pytest.raises(ValueError, match="profile must be one of"):
        resolve_command_names(profile="product-doc")


def test_source_path_for_command_uses_profile_subdirectories(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    _write_command_sources(source_dir)

    assert source_path_for_command(source_dir, "status") == source_dir / "daily" / "status.md"
    assert (
        source_path_for_command(source_dir, "mark")
        == source_dir / "maintenance" / "mark.md"
    )
    assert source_path_for_command(source_dir, "dream") == source_dir / "daily" / "dream.md"


def test_sync_slash_commands_removes_commands_outside_selected_profile(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "review-kb.md").write_text("# old maintenance command\n", encoding="utf-8")
    (target_dir / "prd-sync.md").write_text("# old product-doc command\n", encoding="utf-8")

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
    )

    assert "review-kb" in result.removed_commands
    assert "prd-sync" in result.removed_commands
    assert not (target_dir / "review-kb.md").exists()
    assert not (target_dir / "prd-sync.md").exists()
    assert (target_dir / "status.md").read_text(encoding="utf-8") == "# /hm:status\n"
    assert not (target_dir / "daily").exists()


def test_sync_slash_commands_dry_run_does_not_mutate_target(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "review-kb.md").write_text("# old maintenance command\n", encoding="utf-8")
    (target_dir / "prd-sync.md").write_text("# old product-doc command\n", encoding="utf-8")

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
        dry_run=True,
    )

    assert result.dry_run is True
    assert "review-kb" in result.removed_commands
    assert "prd-sync" in result.removed_commands
    assert (target_dir / "review-kb.md").exists()
    assert (target_dir / "prd-sync.md").exists()
    assert not (target_dir / "status.md").exists()
