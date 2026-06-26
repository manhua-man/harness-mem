from __future__ import annotations

from pathlib import Path

from harness_mem.integration.command_sync import (
    known_command_names,
    resolve_command_names,
    sync_slash_commands,
)


def _write_command_sources(source_dir: Path) -> None:
    source_dir.mkdir(parents=True)
    for command in known_command_names():
        (source_dir / f"{command}.md").write_text(
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
    )
    assert "mark" in resolve_command_names(profile="maintenance")
    assert "prd-sync" in resolve_command_names(profile="maintenance")
    assert "dream" not in resolve_command_names(profile="maintenance")
    assert resolve_command_names(profile="daily", include=["labs"])[-1] == "dream"


def test_sync_slash_commands_removes_commands_outside_selected_profile(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "dream.md").write_text("# old labs command\n", encoding="utf-8")

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
    )

    assert "dream" in result.removed_commands
    assert not (target_dir / "dream.md").exists()
    assert (target_dir / "status.md").read_text(encoding="utf-8") == "# /hm:status\n"


def test_sync_slash_commands_dry_run_does_not_mutate_target(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    _write_command_sources(source_dir)
    target_dir.mkdir()
    (target_dir / "dream.md").write_text("# old labs command\n", encoding="utf-8")

    result = sync_slash_commands(
        source_dir=source_dir,
        destination_dir=target_dir,
        profile="daily",
        dry_run=True,
    )

    assert result.dry_run is True
    assert "dream" in result.removed_commands
    assert (target_dir / "dream.md").exists()
    assert not (target_dir / "status.md").exists()
