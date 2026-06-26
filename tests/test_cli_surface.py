from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import harness_mem.cli as cli
import harness_mem.commands.import_bridge as import_command
from harness_mem.commands.import_bridge import cmd_import
from harness_mem.shell_completion import (
    CLI_COMMANDS,
    MAINTENANCE_ACTIONS,
    completion_bash,
    completion_fish,
    completion_zsh,
)


def _assert_help_exit(argv: list[str], code: int = 0) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == code


def test_cli_top_level_help_excludes_import_and_purge(capsys: pytest.CaptureFixture[str]) -> None:
    _assert_help_exit(["--help"])
    out = capsys.readouterr().out

    assert "{init,quickstart,qs,doctor,maintenance,config,integration}" in out
    assert " import " not in out
    assert " purge " not in out


def test_removed_top_level_import_and_purge_are_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["import", "--help"], code=2)
    import_err = capsys.readouterr().err
    assert "invalid choice" in import_err

    _assert_help_exit(["purge", "--help"], code=2)
    purge_err = capsys.readouterr().err
    assert "invalid choice" in purge_err


def test_maintenance_import_and_purge_help_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["maintenance", "import", "--help"])
    import_help = capsys.readouterr().out
    assert "harness-mem maintenance import" in import_help
    assert "--source" in import_help
    assert "--apply" in import_help

    _assert_help_exit(["maintenance", "purge", "--help"])
    purge_help = capsys.readouterr().out
    assert "harness-mem maintenance purge" in purge_help
    assert "--before" in purge_help
    assert "--stale-only" in purge_help


def test_maintenance_import_dispatch_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str | None, bool]] = []

    async def fake_import(source: str, project: str | None = None, *, dry_run: bool = False) -> int:
        calls.append((source, project, dry_run))
        return 0

    monkeypatch.setattr(cli, "cmd_import", fake_import)

    assert cli.main(["maintenance", "import", "--source", "drafts.json", "-p", "demo"]) == 0
    assert calls == [("drafts.json", "demo", True)]

    calls.clear()
    assert (
        cli.main(
            [
                "maintenance",
                "import",
                "--source",
                "drafts.json",
                "-p",
                "demo",
                "--apply",
            ]
        )
        == 0
    )
    assert calls == [("drafts.json", "demo", False)]


def test_maintenance_purge_dispatch_defaults_to_dry_run(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str, bool, str | None, bool]] = []

    async def fake_purge(
        before: str,
        category: str,
        dry_run: bool,
        project: str | None = None,
        *,
        stale_only: bool = False,
    ) -> int:
        calls.append((before, category, dry_run, project, stale_only))
        return 0

    monkeypatch.setattr(cli, "cmd_purge", fake_purge)

    assert (
        cli.main(
            [
                "maintenance",
                "purge",
                "--before",
                "2025-01-01",
                "-p",
                "demo",
                "--stale-only",
            ]
        )
        == 0
    )
    assert calls == [("2025-01-01", "all", True, "demo", True)]

    calls.clear()
    assert (
        cli.main(
            [
                "maintenance",
                "purge",
                "--before",
                "2025-01-01",
                "--category",
                "structured",
                "-p",
                "demo",
                "--apply",
            ]
        )
        == 0
    )
    assert calls == [("2025-01-01", "structured", False, "demo", False)]


def test_import_dry_run_previews_without_opening_backend(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "drafts.json"
    source.write_text(
        json.dumps(
            [
                {"content": "Keep durable truth behind review."},
                {
                    "source_entity": "CLI",
                    "target_entity": "maintenance",
                    "relation_type": "owns",
                },
            ]
        ),
        encoding="utf-8",
    )

    class FailingBackend:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("dry-run must not open the storage backend")

    monkeypatch.setattr(import_command, "LocalMemoryBackend", FailingBackend)

    assert asyncio.run(cmd_import(str(source), "demo", dry_run=True)) == 0
    out = capsys.readouterr().out
    assert "[DRY RUN] Would import 2 pending candidates" in out
    assert "1 Memory Entries" in out
    assert "1 Relation Facts" in out
    assert "No candidate layer writes were performed." in out
    assert "No durable truth was confirmed." in out


def test_completion_surface_moves_import_and_purge_under_maintenance() -> None:
    assert "import" not in CLI_COMMANDS
    assert "purge" not in CLI_COMMANDS
    assert "import" in MAINTENANCE_ACTIONS
    assert "purge" in MAINTENANCE_ACTIONS

    bash = completion_bash()
    zsh = completion_zsh()
    fish = completion_fish()

    assert 'compgen -W "init quickstart doctor maintenance config integration qs"' in bash
    assert "commands=(init quickstart doctor maintenance config integration qs)" in zsh
    assert (
        "complete -c harness-mem -n '__fish_use_subcommand' "
        "-a 'init quickstart doctor maintenance config integration qs'"
    ) in fish

    for script in (bash, zsh, fish):
        assert "import" in script
        assert "purge" in script
        assert "--source" in script or "-l source" in script
        assert "--before" in script or "-l before" in script
        assert "--category" in script or "-l category" in script
        assert "--stale-only" in script or "-l stale-only" in script
        assert "--apply" in script or "-l apply" in script
