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
    OPTIONAL_COMMAND_GROUPS,
    SKILL_GOVERNANCE_ACTIONS,
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

    assert (
        "{init,quickstart,qs,doctor,skill-governance,maintenance,config,integration}"
        in out
    )
    assert " import " not in out
    assert " purge " not in out
    assert "skill-governance" in out


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


def test_skill_governance_help_paths_succeed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    paths = [
        ["skill-governance", "--help"],
        ["skill-governance", "list-candidates", "--help"],
        ["skill-governance", "search", "--help"],
        ["skill-governance", "suggest", "--help"],
        ["skill-governance", "confirm", "--help"],
        ["skill-governance", "reject", "--help"],
        ["skill-governance", "record-result", "--help"],
    ]
    for path in paths:
        _assert_help_exit(path)
        assert "skill-governance" in capsys.readouterr().out


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


def test_skill_governance_dispatch_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []

    async def fake_list(project: str, *, status: str | None = None) -> int:
        calls.append(("list", (project,), {"status": status}))
        return 0

    async def fake_search(project: str, query: str, limit: int = 10) -> int:
        calls.append(("search", (project, query, limit), {}))
        return 0

    async def fake_suggest(
        project: str,
        activation_condition: str,
        steps: list[str],
        termination_condition: str,
        *,
        success_examples: list[str] | None = None,
        source_session_id: str = "",
        source: str = "",
        confidence: float = 0.7,
    ) -> int:
        calls.append(
            (
                "suggest",
                (project, activation_condition, tuple(steps), termination_condition),
                {
                    "success_examples": tuple(success_examples or []),
                    "source_session_id": source_session_id,
                    "source": source,
                    "confidence": confidence,
                },
            )
        )
        return 0

    async def fake_confirm(candidate_id: str) -> int:
        calls.append(("confirm", (candidate_id,), {}))
        return 0

    async def fake_reject(candidate_id: str) -> int:
        calls.append(("reject", (candidate_id,), {}))
        return 0

    async def fake_record(skill_id: str, success: bool) -> int:
        calls.append(("record", (skill_id, success), {}))
        return 0

    monkeypatch.setattr(cli, "cmd_list_procedural_candidates", fake_list)
    monkeypatch.setattr(cli, "cmd_search_skills", fake_search)
    monkeypatch.setattr(cli, "cmd_suggest_procedural", fake_suggest)
    monkeypatch.setattr(cli, "cmd_confirm_procedural", fake_confirm)
    monkeypatch.setattr(cli, "cmd_reject_procedural", fake_reject)
    monkeypatch.setattr(cli, "cmd_record_skill_result", fake_record)

    assert (
        cli.main(["skill-governance", "list-candidates", "-p", "demo", "--status", "rejected"])
        == 0
    )
    assert (
        cli.main(["skill-governance", "search", "-p", "demo", "--query", "release", "--limit", "3"])
        == 0
    )
    assert (
        cli.main(
            [
                "skill-governance",
                "suggest",
                "-p",
                "demo",
                "--activation-condition",
                "A workflow repeats",
                "--step",
                "Audit active skills",
                "--step",
                "Propose on-demand skills",
                "--termination-condition",
                "Activation map is reviewed",
                "--success-example",
                "Removed noisy always-on skills",
                "--source-session-id",
                "session-1",
                "--source",
                "operator",
                "--confidence",
                "0.8",
            ]
        )
        == 0
    )
    assert cli.main(["skill-governance", "confirm", "candidate-1"]) == 0
    assert cli.main(["skill-governance", "reject", "candidate-2"]) == 0
    assert cli.main(["skill-governance", "record-result", "skill-1", "--failure"]) == 0

    assert calls == [
        ("list", ("demo",), {"status": "rejected"}),
        ("search", ("demo", "release", 3), {}),
        (
            "suggest",
            (
                "demo",
                "A workflow repeats",
                ("Audit active skills", "Propose on-demand skills"),
                "Activation map is reviewed",
            ),
            {
                "success_examples": ("Removed noisy always-on skills",),
                "source_session_id": "session-1",
                "source": "operator",
                "confidence": 0.8,
            },
        ),
        ("confirm", ("candidate-1",), {}),
        ("reject", ("candidate-2",), {}),
        ("record", ("skill-1", False), {}),
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
    assert "skill-governance" in CLI_COMMANDS
    assert "suggest" in SKILL_GOVERNANCE_ACTIONS
    assert "confirm" in SKILL_GOVERNANCE_ACTIONS
    assert "record-result" in SKILL_GOVERNANCE_ACTIONS
    assert "import" in MAINTENANCE_ACTIONS
    assert "purge" in MAINTENANCE_ACTIONS
    assert "assign-memory-types" not in MAINTENANCE_ACTIONS
    assert "rebuild-vector-index" in MAINTENANCE_ACTIONS
    assert "migrate-store-v2" in MAINTENANCE_ACTIONS
    assert "product-doc" not in MAINTENANCE_ACTIONS
    assert "product-doc" not in COMMAND_PROFILES
    assert "product-doc" not in OPTIONAL_COMMAND_GROUPS
    assert "bench" not in MAINTENANCE_ACTIONS
    assert "cache" not in MAINTENANCE_ACTIONS

    bash = completion_bash()
    zsh = completion_zsh()
    fish = completion_fish()

    assert (
        'compgen -W "init quickstart doctor skill-governance maintenance '
        'config integration qs"'
    ) in bash
    assert (
        "commands=(init quickstart doctor skill-governance maintenance "
        "config integration qs)"
    ) in zsh
    assert (
        "complete -c harness-mem -n '__fish_use_subcommand' "
        "-a 'init quickstart doctor skill-governance maintenance config integration qs'"
    ) in fish

    for script in (bash, zsh, fish):
        assert "import" in script
        assert "purge" in script
        assert "skill-governance" in script
        assert "record-result" in script
        assert "labs" not in script
        assert "product-doc" not in script
        assert "rebuild-vector-index" in script
        assert "migrate-store-v2" in script
        assert "wiki-bridge" not in script
        assert "causal" not in script
        assert "--source" in script or "-l source" in script
        assert "--before" in script or "-l before" in script
        assert "--category" in script or "-l category" in script
        assert "--stale-only" in script or "-l stale-only" in script
        assert "--apply" in script or "-l apply" in script
