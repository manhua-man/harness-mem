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
    COMMAND_PROFILES,
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
    assert "skill-governance" not in out


def test_removed_top_level_import_and_purge_are_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["import", "--help"], code=2)
    import_err = capsys.readouterr().err
    assert "invalid choice" in import_err

    _assert_help_exit(["purge", "--help"], code=2)
    purge_err = capsys.readouterr().err
    assert "invalid choice" in purge_err

    _assert_help_exit(["skill-governance", "--help"], code=2)
    skill_err = capsys.readouterr().err
    assert "invalid choice" in skill_err


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


def test_nested_maintenance_actions_are_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    nested_paths = [
        ["maintenance", "memory-types", "assign", "--help"],
        ["maintenance", "rebuild", "vector-index", "--help"],
        ["maintenance", "rebuild", "verbatim-index", "--help"],
        ["maintenance", "cache", "prepare-knowledge", "--help"],
        ["maintenance", "cache", "cleanup-generated", "--help"],
        ["maintenance", "migrate", "store-v2", "--help"],
        ["maintenance", "export", "json-snapshot", "--help"],
        ["maintenance", "audit", "state", "--help"],
        ["maintenance", "product-doc", "wiki-bridge", "rebuild", "--help"],
        ["maintenance", "bench", "causal", "--help"],
    ]
    for path in nested_paths:
        _assert_help_exit(path, code=2)
        assert "invalid choice" in capsys.readouterr().err


def test_removed_product_maintenance_actions_are_invalid(
    capsys: pytest.CaptureFixture[str],
) -> None:
    removed = [
        "assign-memory-types",
        "prepare-knowledge-cache",
        "cleanup-generated-cache",
        "rebuild-wiki-bridge",
        "causal-benchmark",
        "list-reflection-jobs",
        "get-reflection-job",
        "list-metabolism-runs",
    ]
    for action in removed:
        _assert_help_exit(["maintenance", action, "--help"], code=2)
        assert "invalid choice" in capsys.readouterr().err


def test_flat_operator_maintenance_help_paths_succeed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = [
        ["maintenance", "rebuild-vector-index", "--help"],
        ["maintenance", "rebuild-verbatim-index", "--help"],
        ["maintenance", "migrate-store-v2", "--help"],
        ["maintenance", "export-json-snapshot", "--help"],
        ["maintenance", "state-audit", "--help"],
    ]
    for path in paths:
        _assert_help_exit(path)
        assert "usage: harness-mem " + " ".join(path[:-1]) in capsys.readouterr().out


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


def test_flat_maintenance_dispatch_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def fake_migrate(
        project: str | None,
        *,
        apply: bool,
        export_rollback: str | None,
    ) -> int:
        calls.append(
            ("migrate", (project,), {"apply": apply, "export_rollback": export_rollback})
        )
        return 0

    async def fake_export(project: str | None, export_dir: str, *, apply: bool) -> int:
        calls.append(("export", (project, export_dir), {"apply": apply}))
        return 0

    async def fake_audit(project: str | None) -> int:
        calls.append(("audit", (project,), {}))
        return 0

    monkeypatch.setattr(cli, "cmd_migrate_store_v2", fake_migrate)
    monkeypatch.setattr(cli, "cmd_export_json_snapshot", fake_export)
    monkeypatch.setattr(cli, "cmd_state_audit", fake_audit)

    assert (
        cli.main(
            [
                "maintenance",
                "migrate-store-v2",
                "-p",
                "demo",
                "--apply",
                "--export-rollback",
                "rollback",
            ]
        )
        == 0
    )
    assert (
        cli.main(
            [
                "maintenance",
                "export-json-snapshot",
                "-p",
                "demo",
                "--export-dir",
                "snapshot",
            ]
        )
        == 0
    )
    assert cli.main(["maintenance", "state-audit", "-p", "demo"]) == 0

    assert calls == [
        ("migrate", ("demo",), {"apply": True, "export_rollback": "rollback"}),
        ("export", ("demo", "snapshot"), {"apply": False}),
        ("audit", ("demo",), {}),
    ]


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
    assert "skill-governance" not in CLI_COMMANDS
    assert "import" in MAINTENANCE_ACTIONS
    assert "purge" in MAINTENANCE_ACTIONS
    assert "assign-memory-types" not in MAINTENANCE_ACTIONS
    assert "rebuild-vector-index" in MAINTENANCE_ACTIONS
    assert "migrate-store-v2" in MAINTENANCE_ACTIONS
    assert "product-doc" not in MAINTENANCE_ACTIONS
    assert "metabolism-run" not in MAINTENANCE_ACTIONS
    assert COMMAND_PROFILES == ["daily"]
    assert "bench" not in MAINTENANCE_ACTIONS
    assert "cache" not in MAINTENANCE_ACTIONS

    bash = completion_bash()
    zsh = completion_zsh()
    fish = completion_fish()

    assert (
        'compgen -W "init quickstart doctor maintenance config integration qs"'
    ) in bash
    assert (
        "commands=(init quickstart doctor maintenance config integration qs)"
    ) in zsh
    assert (
        "complete -c harness-mem -n '__fish_use_subcommand' "
        "-a 'init quickstart doctor maintenance config integration qs'"
    ) in fish

    for script in (bash, zsh, fish):
        assert "import" in script
        assert "purge" in script
        assert "install-cursor-wake-hook" in script
        assert "install-claude-wake-hook" in script
        assert "install-cursor-suite" in script
        assert "install-claude-suite" in script
        assert "install-hook-suite" in script
        assert "skill-governance" not in script
        assert "record-result" not in script
        assert "labs" not in script
        assert "product-doc" not in script
        assert "commands enable" not in script
        assert "--include" not in script
        assert "maintenance full" not in script
        assert "triggers.after_agent" not in script
        assert "reflection dream preview metabolism" not in script
        assert "rebuild-vector-index" in script
        assert "migrate-store-v2" in script
        assert "wiki-bridge" not in script
        assert "causal" not in script
        assert "--source" in script or "-l source" in script
        assert "--before" in script or "-l before" in script
        assert "--category" in script or "-l category" in script
        assert "--stale-only" in script or "-l stale-only" in script
        assert "--apply" in script or "-l apply" in script
    assert "--client" in bash
    assert "--client" in zsh
    assert "-l client" in fish
