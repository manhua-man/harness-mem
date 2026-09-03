"""CLI entry point for harness-mem.

The CLI is an operator maintenance console. Daily AI memory workflows are
available through MCP tools and repo-local IDE commands / skills instead of
terminal subcommands.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from harness_mem import __version__
from harness_mem.commands import (
    cmd_config_get,
    cmd_config_list,
    cmd_config_set,
    cmd_config_validate,
    cmd_doctor,
    cmd_export_json_snapshot,
    cmd_import,
    cmd_install_hook_suite,
    cmd_list_commands,
    cmd_migrate_store_v2,
    cmd_purge,
    cmd_erase,
    cmd_reset_runtime,
    cmd_quickstart,
    cmd_state_audit,
    cmd_sync_commands,
    cmd_transcript_evidence,
)
from harness_mem.commands.integration_cmds import SUPPORTED_HOOK_CLIENTS
from harness_mem.transcript_evidence import EVIDENCE_CLIENTS
from harness_mem.commands.support import DEFAULT_DATA_DIR

# Test compatibility: tests monkeypatch these via cli module.
from harness_mem.adapters.codex.adapter import CodexAdapter  # noqa: F401

__all__ = [
    "main",
    "cmd_config_get",
    "cmd_config_set",
    "cmd_config_list",
    "cmd_config_validate",
    "cmd_doctor",
    "cmd_export_json_snapshot",
    "cmd_import",
    "cmd_install_hook_suite",
    "cmd_list_commands",
    "cmd_migrate_store_v2",
    "cmd_purge",
    "cmd_quickstart",
    "cmd_state_audit",
    "cmd_sync_commands",
    "cmd_transcript_evidence",
]


def _add_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--project", help="Project name")


def _add_required_project_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-p", "--project", required=True, help="Project name")


def _add_dry_apply_group(parser: argparse.ArgumentParser) -> None:
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Preview changes without writing (default)",
    )
    apply_group.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Commit changes to disk",
    )


def main(argv: list[str] | None = None):
    """Run the maintenance-only CLI surface."""
    args_list = list(sys.argv[1:] if argv is None else argv)

    # Handle --completion before full argument parsing.
    if "--completion" in args_list or any(
        arg.startswith("--completion=") for arg in args_list
    ):
        from harness_mem.shell_completion import print_completion

        for idx, arg in enumerate(args_list):
            if arg.startswith("--completion="):
                shell = arg.split("=", 1)[1]
                print_completion(shell)
                return 0
            if arg == "--completion":
                if idx + 1 < len(args_list):
                    print_completion(args_list[idx + 1])
                    return 0
        print("--completion requires a shell argument: bash, zsh, or fish", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(
        prog="harness-mem",
        description=(
            "Local harness-mem maintenance console. Daily AI memory workflows "
            "use IDE commands, repo skills, or agent workflows instead of CLI "
            "subcommands."
        ),
    )
    parser.add_argument("--version", action="version", version=f"harness-mem {__version__}")
    sub = parser.add_subparsers(dest="command")

    init = sub.add_parser("init", help="Initialize the local data directory")
    init.set_defaults(command_name="init")

    quickstart = sub.add_parser(
        "quickstart",
        aliases=["qs"],
        help="Install the current app's global memory entry",
    )
    quickstart.add_argument(
        "-c",
        "--client",
        choices=["auto", *SUPPORTED_HOOK_CLIENTS],
        default="auto",
    )
    quickstart.set_defaults(command_name="quickstart")

    doctor = sub.add_parser("doctor", help="Inspect local setup and suggest repairs")
    _add_project_arg(doctor)
    doctor.set_defaults(command_name="doctor")

    maintenance = sub.add_parser("maintenance", help="Explicit operator maintenance utilities")
    maintenance.set_defaults(command_name="maintenance")
    maintenance_sub = maintenance.add_subparsers(dest="maintenance_action")

    rebuild_vector_index = maintenance_sub.add_parser(
        "rebuild-vector-index",
        help="Rebuild the vector index",
    )
    _add_project_arg(rebuild_vector_index)
    rebuild_vector_index.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Embedding encode batch size (default: 32)",
    )

    rebuild_verbatim_index = maintenance_sub.add_parser(
        "rebuild-verbatim-index",
        help="Rebuild the verbatim exact index",
    )
    _add_project_arg(rebuild_verbatim_index)

    migrate_store_v2 = maintenance_sub.add_parser(
        "migrate-store-v2",
        help="Migrate side-by-side canonical store data",
    )
    _add_project_arg(migrate_store_v2)
    _add_dry_apply_group(migrate_store_v2)
    migrate_store_v2.add_argument(
        "--export-rollback",
        help="Export Storage v2 canonical rows as v3-compatible JSON blobs",
    )

    export_json_snapshot = maintenance_sub.add_parser(
        "export-json-snapshot",
        help="Export a human-readable JSON snapshot",
    )
    _add_project_arg(export_json_snapshot)
    _add_dry_apply_group(export_json_snapshot)
    export_json_snapshot.add_argument(
        "--export-dir",
        required=True,
        help="Write human-readable JSON blobs here",
    )

    state_audit = maintenance_sub.add_parser(
        "state-audit",
        help="Inspect the local state audit ledger",
    )
    _add_project_arg(state_audit)

    migrate_legacy_accepted = maintenance_sub.add_parser(
        "migrate-legacy-accepted",
        help="Preview or move literal accepted rows to pending/historical governance",
    )
    _add_project_arg(migrate_legacy_accepted)
    _add_dry_apply_group(migrate_legacy_accepted)

    archive_distill = maintenance_sub.add_parser(
        "archive-distill",
        help="Inventory or process Codex archived sessions by detected project",
    )
    archive_distill.add_argument(
        "--project-root",
        help="Control project whose archive_distill policy is used (default: cwd)",
    )
    archive_distill.add_argument(
        "--archive-dir",
        help="Override the Codex archived_sessions directory",
    )
    archive_distill.add_argument(
        "--json",
        action="store_true",
        help="Emit the full structured inventory or batch report",
    )
    archive_distill.add_argument(
        "--verify",
        action="store_true",
        help="Read back jobs, Notes, ledger, cleanup, and promoted truth in one run",
    )
    archive_distill.add_argument(
        "--batch-size",
        type=int,
        help="Override this run's batch size without changing project defaults",
    )
    archive_distill.add_argument(
        "--daily-limit",
        type=int,
        help="Override this run's daily attempt limit without changing project defaults",
    )
    archive_distill.add_argument(
        "--repair-only",
        action="store_true",
        help="Reverify historical completed partial receipts without selecting archives",
    )
    _add_dry_apply_group(archive_distill)

    import_cmd = maintenance_sub.add_parser(
        "import",
        help="Preview or import memory drafts into the candidate layer",
    )
    import_cmd.add_argument("--source", required=True, help="Path to JSON draft")
    _add_project_arg(import_cmd)
    _add_dry_apply_group(import_cmd)

    purge = maintenance_sub.add_parser(
        "purge",
        help="Preview or soft-delete observations or structured memory",
    )
    _add_project_arg(purge)
    purge.add_argument("--before", required=True, help="YYYY-MM-DD")
    purge.add_argument(
        "--category",
        choices=["observations", "structured", "all"],
        default="all",
    )
    purge.add_argument(
        "--stale-only",
        action="store_true",
        help="Only include never-accessed or stale entries",
    )
    _add_dry_apply_group(purge)

    erase = maintenance_sub.add_parser(
        "erase",
        help="Preview or irreversibly erase transcript and all derived local data",
    )
    _add_project_arg(erase)
    erase.add_argument("--session-id")
    erase.add_argument("--source-id")
    erase.add_argument("--before", help="YYYY-MM-DD")
    erase.add_argument("--reason", default="user_requested_erasure")
    _add_dry_apply_group(erase)

    reset_runtime = maintenance_sub.add_parser(
        "reset-runtime",
        help="Preview or reset generated runtime data while preserving Codex archive sources",
    )
    reset_runtime.add_argument(
        "--archive-dir",
        help="Codex archived_sessions directory to preserve and use for redistill",
    )
    reset_runtime.add_argument(
        "--confirm-runtime-reset",
        action="store_true",
        help="Required with --apply because the runtime reset is irreversible",
    )
    _add_dry_apply_group(reset_runtime)

    config = sub.add_parser(
        "config",
        help="Manage harness-mem TOML configuration files",
        description=(
            "Manage the user-level and project-level harness-mem TOML config "
            "files. Dream auto-maintenance uses dream.auto.* keys; wake and "
            "dream hooks are installed explicitly under integration."
        ),
    )
    config.set_defaults(command_name="config")
    config_sub = config.add_subparsers(dest="config_action")

    config_get = config_sub.add_parser(
        "get", help="Read a single merged configuration value"
    )
    config_get.add_argument("key", help="Dotted key path, e.g. dream.auto.enabled")
    config_get.add_argument("--project-root", help="Project directory (default: cwd)")

    config_set = config_sub.add_parser(
        "set", help="Write a single configuration value to a Config_File"
    )
    config_set.add_argument("key", help="Dotted key path, e.g. dream.auto.enabled")
    config_set.add_argument("value", help="Literal value to write")
    config_set.add_argument(
        "--scope",
        choices=["user", "project"],
        required=True,
        help="Which Config_File to modify",
    )
    config_set.add_argument(
        "--confirm",
        action="store_true",
        help=(
            "Confirm a persistent policy that authorizes background model use "
            "or automatic source deletion"
        ),
    )
    config_set.add_argument("--project-root", help="Project directory (default: cwd)")

    config_list = config_sub.add_parser(
        "list", help="Print public policy keys with merged source labels"
    )
    config_list.add_argument("--project-root", help="Project directory (default: cwd)")
    config_list.add_argument(
        "--detail",
        choices=["runtime"],
        help="Include read-only effective runtime tuning and source labels",
    )

    config_validate = config_sub.add_parser(
        "validate", help="Validate that the resolved Config_File set parses and merges"
    )
    config_validate.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )

    integration = sub.add_parser(
        "integration",
        help="Inspect or repair supported IDE integrations",
        description=(
            "Repair project hooks, inspect transcript evidence, or synchronize "
            "the single host-native memory entry."
        ),
    )
    integration.set_defaults(command_name="integration")
    integration_sub = integration.add_subparsers(dest="integration_action")

    hooks = integration_sub.add_parser(
        "hooks",
        help="Repair or refresh one host's hook suite",
        description=(
            "Repair project hooks through the same idempotent suite installer "
            "used by MCP bootstrap. Normal projects do not need this command."
        ),
    )
    hooks_sub = hooks.add_subparsers(dest="hooks_action")
    hooks_sync = hooks_sub.add_parser("sync", help="Synchronize one hook suite")
    hooks_sync.add_argument(
        "--client",
        choices=["all", *SUPPORTED_HOOK_CLIENTS],
        required=True,
        help="Host whose project hooks should be repaired",
    )
    hooks_sync.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )
    hooks_sync.add_argument(
        "--force", action="store_true", help="Overwrite existing harness-mem hooks"
    )

    transcript_evidence = integration_sub.add_parser(
        "transcript-evidence",
        help="Report local transcript evidence for host adapters",
        description=(
            "Scan factual local host state for transcript evidence. This command "
            "does not imply ingest support; adapter availability is reported "
            "separately."
        ),
    )
    transcript_evidence.add_argument(
        "--client",
        choices=["all", *EVIDENCE_CLIENTS],
        default="all",
        help="Client to inspect (default: all evidence clients)",
    )
    transcript_evidence.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )

    commands = integration_sub.add_parser(
        "commands",
        help="List or sync the global host-native memory entry",
        description="Manage the single global memory entry without reinstalling harness-mem.",
    )
    commands_sub = commands.add_subparsers(dest="commands_action")

    commands_sub.add_parser("list", help="List the memory entry for each host")

    commands_sync = commands_sub.add_parser(
        "sync",
        help="Synchronize the single global memory entry",
    )
    commands_sync.add_argument(
        "--client", choices=["all", *SUPPORTED_HOOK_CLIENTS], default="all"
    )
    commands_sync.add_argument("--dry-run", action="store_true")

    args = parser.parse_args(args_list)
    command = getattr(args, "command_name", args.command)

    if command is None:
        parser.print_help()
        return 0

    if command == "init":
        DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Initialized at {DEFAULT_DATA_DIR}")
        return 0

    if command == "quickstart":
        return asyncio.run(cmd_quickstart(args.client))

    if command == "doctor":
        return asyncio.run(cmd_doctor(args.project))

    if command == "maintenance":
        if args.maintenance_action is None:
            maintenance.print_help()
            return 0
        if args.maintenance_action == "rebuild-vector-index":
            from harness_mem.commands.maintenance import cmd_rebuild_vector_index

            return asyncio.run(
                cmd_rebuild_vector_index(
                    args.project,
                    batch_size=args.batch_size,
                )
            )
        if args.maintenance_action == "rebuild-verbatim-index":
            from harness_mem.commands.maintenance import cmd_rebuild_verbatim_index

            return asyncio.run(cmd_rebuild_verbatim_index(args.project))
        if args.maintenance_action == "migrate-store-v2":
            return asyncio.run(
                cmd_migrate_store_v2(
                    args.project,
                    apply=not args.dry_run,
                    export_rollback=args.export_rollback,
                )
            )
        if args.maintenance_action == "export-json-snapshot":
            return asyncio.run(
                cmd_export_json_snapshot(
                    args.project,
                    args.export_dir,
                    apply=not args.dry_run,
                )
            )
        if args.maintenance_action == "state-audit":
            return asyncio.run(cmd_state_audit(args.project))
        if args.maintenance_action == "migrate-legacy-accepted":
            from harness_mem.commands.maintenance import cmd_migrate_legacy_accepted

            return asyncio.run(
                cmd_migrate_legacy_accepted(
                    args.project,
                    apply=not args.dry_run,
                )
            )
        if args.maintenance_action == "archive-distill":
            from pathlib import Path

            from harness_mem.commands.archive_distill import (
                print_archive_distill_result,
                run_archive_distill_batch,
            )

            control_root = Path(args.project_root or Path.cwd()).expanduser().resolve()
            result = asyncio.run(
                run_archive_distill_batch(
                    control_root=control_root,
                    apply=not args.dry_run,
                    archive_dir=(
                        Path(args.archive_dir).expanduser()
                        if args.archive_dir
                        else None
                    ),
                    verify=args.verify,
                    batch_size=args.batch_size,
                    daily_limit=args.daily_limit,
                    repair_only=args.repair_only,
                )
            )
            print_archive_distill_result(result, as_json=args.json)
            return 0 if result.get("success") else 1
        if args.maintenance_action == "import":
            return asyncio.run(
                cmd_import(args.source, args.project, dry_run=args.dry_run)
            )
        if args.maintenance_action == "purge":
            return asyncio.run(
                cmd_purge(
                    args.before,
                    args.category,
                    args.dry_run,
                    args.project,
                    stale_only=args.stale_only,
                )
            )
        if args.maintenance_action == "erase":
            if not args.project:
                maintenance.error("maintenance erase requires --project")
            return asyncio.run(
                cmd_erase(
                    args.project,
                    session_id=args.session_id,
                    source_id=args.source_id,
                    before_date=args.before,
                    apply=not args.dry_run,
                    reason=args.reason,
                )
            )
        if args.maintenance_action == "reset-runtime":
            return asyncio.run(
                cmd_reset_runtime(
                    archive_dir=args.archive_dir,
                    apply=not args.dry_run,
                    confirm_runtime_reset=args.confirm_runtime_reset,
                )
            )
        maintenance.error(f"Unknown maintenance action: {args.maintenance_action}")

    if command == "config":
        if args.config_action is None:
            config.print_help()
            return 0
        if args.config_action == "get":
            return cmd_config_get(args.key, args.project_root)
        if args.config_action == "set":
            return cmd_config_set(
                args.key,
                args.value,
                args.scope,
                args.project_root,
                confirm=args.confirm,
            )
        if args.config_action == "list":
            return cmd_config_list(args.project_root, detail=args.detail)
        if args.config_action == "validate":
            return cmd_config_validate(args.project_root)
        config.error(f"Unknown config action: {args.config_action}")

    if command == "integration":
        if args.integration_action is None:
            integration.print_help()
            return 0
        if args.integration_action == "hooks":
            if args.hooks_action is None:
                hooks.print_help()
                return 0
            if args.hooks_action == "sync":
                return cmd_install_hook_suite(
                    args.client,
                    args.project_root,
                    args.force,
                )
            hooks.error(f"Unknown hooks action: {args.hooks_action}")
        if args.integration_action == "transcript-evidence":
            return cmd_transcript_evidence(args.client, args.project_root)
        if args.integration_action == "commands":
            if args.commands_action is None:
                commands.print_help()
                return 0
            if args.commands_action == "list":
                return cmd_list_commands()
            if args.commands_action == "sync":
                return cmd_sync_commands(
                    client=args.client,
                    dry_run=args.dry_run,
                )
            commands.error(f"Unknown commands action: {args.commands_action}")
        integration.error(f"Unknown integration action: {args.integration_action}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
