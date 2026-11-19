from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import harness_mem.cli as cli
import harness_mem.commands.import_bridge as import_command
from harness_mem.commands.import_bridge import cmd_import


def _assert_help_exit(argv: list[str], code: int = 0) -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(argv)
    assert exc.value.code == code


def test_cli_top_level_help_excludes_import_and_purge(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["--help"])
    out = capsys.readouterr().out

    assert "{init,quickstart,qs,doctor,maintenance,config,integration}" in out
    assert " import " not in out
    assert " purge " not in out
    assert "skill-governance" not in out


def test_quickstart_is_global_and_forwards_explicit_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["quickstart", "--help"])
    help_text = capsys.readouterr().out
    assert "--client" in help_text
    assert "--confirm" in help_text
    assert "--limit" not in help_text
    assert "project" not in help_text.lower()

    calls: list[tuple[str, bool]] = []

    def quickstart(client: str, *, confirm: bool) -> int:
        calls.append((client, confirm))
        return 0

    monkeypatch.setattr(cli, "cmd_quickstart", quickstart)
    assert cli.main(["quickstart", "--client", "codex"]) == 0
    assert cli.main(["quickstart", "--client", "codex", "--confirm"]) == 0
    assert calls == [("codex", False), ("codex", True)]


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


def test_integration_exposes_one_hook_repair_surface(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["integration", "--help"])
    integration_help = capsys.readouterr().out
    assert "{hooks,transcript-evidence}" in integration_help

    _assert_help_exit(["integration", "hooks", "sync", "--help"])
    hooks_help = capsys.readouterr().out
    assert "--client" in hooks_help
    assert "--project-root" in hooks_help
    assert "--force" in hooks_help

    retired = (
        "commands",
        "install-cursor-hook",
        "install-claude-hook",
        "install-cursor-wake-hook",
        "install-claude-wake-hook",
        "install-cursor-suite",
        "install-claude-suite",
    )
    for action in retired:
        _assert_help_exit(["integration", action, "--help"], code=2)
        assert "invalid choice" in capsys.readouterr().err


def test_integration_hook_sync_dispatches_one_suite_installer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool, str]] = []
    monkeypatch.setattr(
        cli,
        "cmd_install_hook_suite",
        lambda client, root, force, *, scope: calls.append((client, root, force, scope)) or 0,
    )

    assert (
        cli.main(
            [
                "integration",
                "hooks",
                "sync",
                "--client",
                "codex",
                "--project-root",
                str(tmp_path),
                "--force",
            ]
        )
        == 0
    )
    assert calls == [("codex", str(tmp_path), True, "project")]


def test_integration_hook_sync_dispatches_all_hosts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, bool, str]] = []
    monkeypatch.setattr(
        cli,
        "cmd_install_hook_suite",
        lambda client, root, force, *, scope: calls.append((client, root, force, scope)) or 0,
    )

    assert (
        cli.main(
            [
                "integration",
                "hooks",
                "sync",
                "--client",
                "all",
                "--scope",
                "user",
                "--project-root",
                str(tmp_path),
            ]
        )
        == 0
    )
    assert calls == [("all", str(tmp_path), False, "user")]


def test_maintenance_import_and_purge_help_succeeds(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _assert_help_exit(["maintenance", "import", "--help"])
    import_help = capsys.readouterr().out
    assert "python -m harness_mem.cli maintenance import" in import_help
    assert "--source" in import_help
    assert "--apply" in import_help

    _assert_help_exit(["maintenance", "purge", "--help"])
    purge_help = capsys.readouterr().out
    assert "python -m harness_mem.cli maintenance purge" in purge_help
    assert "--before" in purge_help
    assert "--stale-only" in purge_help

    _assert_help_exit(["maintenance", "reset-runtime", "--help"])
    reset_help = capsys.readouterr().out
    assert "--confirm-runtime-reset" in reset_help
    assert "--apply" in reset_help


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
        assert "usage: python -m harness_mem.cli " + " ".join(path[:-1]) in capsys.readouterr().out


def test_maintenance_import_dispatch_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str | None, bool]] = []

    async def fake_import(
        source: str, project: str | None = None, *, dry_run: bool = False
    ) -> int:
        calls.append((source, project, dry_run))
        return 0

    monkeypatch.setattr(cli, "cmd_import", fake_import)

    assert (
        cli.main(["maintenance", "import", "--source", "drafts.json", "-p", "demo"])
        == 0
    )
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


def test_maintenance_reset_runtime_requires_an_explicit_apply_confirmation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | None, bool, bool]] = []

    async def fake_reset_runtime(
        *,
        archive_dir: str | None,
        apply: bool,
        confirm_runtime_reset: bool,
    ) -> int:
        calls.append((archive_dir, apply, confirm_runtime_reset))
        return 0

    monkeypatch.setattr(cli, "cmd_reset_runtime", fake_reset_runtime)

    assert cli.main(["maintenance", "reset-runtime"]) == 0
    assert calls == [(None, False, False)]

    assert (
        cli.main(
            [
                "maintenance",
                "reset-runtime",
                "--archive-dir",
                "archives",
                "--apply",
                "--confirm-runtime-reset",
            ]
        )
        == 0
    )
    assert calls[-1] == ("archives", True, True)


def test_maintenance_purge_dispatch_defaults_to_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
            (
                "migrate",
                (project,),
                {"apply": apply, "export_rollback": export_rollback},
            )
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


def test_config_list_dispatches_runtime_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str | None, str | None]] = []

    def fake_config_list(
        project_root: str | None,
        *,
        detail: str | None = None,
    ) -> int:
        calls.append((project_root, detail))
        return 0

    monkeypatch.setattr(cli, "cmd_config_list", fake_config_list)

    assert (
        cli.main(
            [
                "config",
                "list",
                "--project-root",
                "demo",
                "--detail",
                "runtime",
            ]
        )
        == 0
    )
    assert calls == [("demo", "runtime")]


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
