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
    cmd_enable_command_profiles,
    cmd_export_json_snapshot,
    cmd_import,
    cmd_install_claude_hook,
    cmd_install_cursor_hook,
    cmd_confirm_procedural,
    cmd_list_command_profiles,
    cmd_list_procedural_candidates,
    cmd_migrate_store_v2,
    cmd_purge,
    cmd_quickstart,
    cmd_record_skill_result,
    cmd_reject_procedural,
    cmd_search_skills,
    cmd_state_audit,
    cmd_suggest_procedural,
    cmd_sync_commands,
)
from harness_mem.integration.command_sync import (
    VALID_COMMAND_PROFILES,
    VALID_OPTIONAL_GROUPS,
)
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
    "cmd_enable_command_profiles",
    "cmd_export_json_snapshot",
    "cmd_import",
    "cmd_install_cursor_hook",
    "cmd_install_claude_hook",
    "cmd_list_command_profiles",
    "cmd_list_procedural_candidates",
    "cmd_migrate_store_v2",
    "cmd_purge",
    "cmd_quickstart",
    "cmd_suggest_procedural",
    "cmd_confirm_procedural",
    "cmd_reject_procedural",
    "cmd_search_skills",
    "cmd_record_skill_result",
    "cmd_state_audit",
    "cmd_sync_commands",
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
        help="Initialize local state and perform first-time setup checks",
    )
    quickstart.add_argument("project", nargs="?", help="Project name")
    quickstart.add_argument(
        "-c",
        "--client",
        choices=["auto", "claude-code", "codex", "skip"],
        default="auto",
    )
    quickstart.add_argument("-n", "--limit", type=int, default=5)
    quickstart.set_defaults(command_name="quickstart")

    doctor = sub.add_parser("doctor", help="Inspect local setup and suggest repairs")
    _add_project_arg(doctor)
    doctor.set_defaults(command_name="doctor")

    skill_governance = sub.add_parser(
        "skill-governance",
        help="Dedicated operator workflow for procedural skill lifecycle review",
        description=(
            "Review and maintain procedural skill candidates outside the public "
            "memory MCP surface. This is an explicit operator workflow, not a "
            "Daily memory command."
        ),
    )
    skill_governance.set_defaults(command_name="skill-governance")
    skill_sub = skill_governance.add_subparsers(dest="skill_governance_action")

    skill_list = skill_sub.add_parser(
        "list-candidates",
        help="List procedural skill candidates for review",
    )
    _add_required_project_arg(skill_list)
    skill_list.add_argument(
        "--status",
        choices=["pending", "accepted", "rejected"],
        default="pending",
    )

    skill_search = skill_sub.add_parser(
        "search",
        help="Search confirmed procedural skills",
    )
    _add_required_project_arg(skill_search)
    skill_search.add_argument("--query", required=True, help="Task or workflow query")
    skill_search.add_argument("--limit", type=int, default=10)

    skill_suggest = skill_sub.add_parser(
        "suggest",
        help="Create a procedural skill candidate",
    )
    _add_required_project_arg(skill_suggest)
    skill_suggest.add_argument(
        "--activation-condition",
        required=True,
        help="When this skill should activate",
    )
    skill_suggest.add_argument(
        "--step",
        dest="steps",
        action="append",
        required=True,
        help="One procedural step; repeat for multiple steps",
    )
    skill_suggest.add_argument(
        "--termination-condition",
        required=True,
        help="When the skill workflow is complete",
    )
    skill_suggest.add_argument(
        "--success-example",
        dest="success_examples",
        action="append",
        default=[],
        help="Optional evidence of a successful run; repeat as needed",
    )
    skill_suggest.add_argument("--source-session-id", default="")
    skill_suggest.add_argument("--source", default="")
    skill_suggest.add_argument("--confidence", type=float, default=0.7)

    skill_confirm = skill_sub.add_parser(
        "confirm",
        help="Promote a procedural candidate to a confirmed skill",
    )
    skill_confirm.add_argument("candidate_id")

    skill_reject = skill_sub.add_parser(
        "reject",
        help="Reject a procedural skill candidate",
    )
    skill_reject.add_argument("candidate_id")

    skill_record = skill_sub.add_parser(
        "record-result",
        help="Record whether a confirmed skill helped in a real use",
    )
    skill_record.add_argument("skill_id")
    result_group = skill_record.add_mutually_exclusive_group(required=True)
    result_group.add_argument("--success", action="store_true")
    result_group.add_argument("--failure", action="store_true")

    maintenance = sub.add_parser("maintenance", help="Explicit operator maintenance utilities")
    maintenance.set_defaults(command_name="maintenance")
    maintenance_sub = maintenance.add_subparsers(dest="maintenance_action")

    rebuild_vector_index = maintenance_sub.add_parser(
        "rebuild-vector-index",
        help="Rebuild the vector index",
    )
    _add_project_arg(rebuild_vector_index)

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

    config = sub.add_parser(
        "config",
        help="Manage harness-mem TOML configuration files",
        description=(
            "Manage the user-level and project-level harness-mem TOML config "
            "files. Note: v2.4 triggers default to 'off'; installing an IDE "
            "hook does not by itself enable reflection. Opt in explicitly with "
            "'config set triggers.after_agent on --scope project'."
        ),
    )
    config.set_defaults(command_name="config")
    config_sub = config.add_subparsers(dest="config_action")

    config_get = config_sub.add_parser(
        "get", help="Read a single merged configuration value"
    )
    config_get.add_argument("key", help="Dotted key path, e.g. triggers.after_agent")
    config_get.add_argument("--project-root", help="Project directory (default: cwd)")

    config_set = config_sub.add_parser(
        "set", help="Write a single configuration value to a Config_File"
    )
    config_set.add_argument("key", help="Dotted key path, e.g. triggers.after_agent")
    config_set.add_argument("value", help="Literal value to write")
    config_set.add_argument(
        "--scope",
        choices=["user", "project"],
        required=True,
        help="Which Config_File to modify",
    )
    config_set.add_argument("--project-root", help="Project directory (default: cwd)")

    config_list = config_sub.add_parser(
        "list", help="Print every recognized key plus extras with source labels"
    )
    config_list.add_argument("--project-root", help="Project directory (default: cwd)")

    config_validate = config_sub.add_parser(
        "validate", help="Validate that the resolved Config_File set parses and merges"
    )
    config_validate.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )

    integration = sub.add_parser(
        "integration",
        help="Install IDE hooks that invoke the v2.4.1 host entry",
        description=(
            "Generate IDE hook scripts that invoke 'python -m "
            "harness_mem.host_entry'. Note: v2.4 triggers default to 'off'; "
            "installing a hook does not by itself enable reflection. Opt in "
            "explicitly with 'config set triggers.after_agent on --scope "
            "project'."
        ),
    )
    integration.set_defaults(command_name="integration")
    integration_sub = integration.add_subparsers(dest="integration_action")

    install_cursor = integration_sub.add_parser(
        "install-cursor-hook",
        help="Generate the Cursor after-agent hook script",
        description=(
            "Generate the Cursor after-agent hook at "
            "<project_root>/.cursor/hooks/after-agent.sh. After install, opt in "
            "via: harness-mem config set triggers.after_agent on --scope "
            "project"
        ),
    )
    install_cursor.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )
    install_cursor.add_argument(
        "--force", action="store_true", help="Overwrite an existing hook"
    )

    install_claude = integration_sub.add_parser(
        "install-claude-hook",
        help="Generate the Claude Code after-turn hook script",
        description=(
            "Generate the Claude Code after-turn hook at "
            "<project_root>/.claude/hooks/after-turn.sh. After install, opt in "
            "via: harness-mem config set triggers.after_agent on --scope "
            "project"
        ),
    )
    install_claude.add_argument(
        "--project-root", help="Project directory (default: cwd)"
    )
    install_claude.add_argument(
        "--force", action="store_true", help="Overwrite an existing hook"
    )

    commands = integration_sub.add_parser(
        "commands",
        help="List or sync Claude Code /hm:* slash command profiles",
        description=(
            "Manage Claude Code /hm:* command visibility without reinstalling "
            "the harness-mem runtime. Daily commands are the default; "
            "maintenance commands are explicit opt-in."
        ),
    )
    commands_sub = commands.add_subparsers(dest="commands_action")

    commands_sub.add_parser("list", help="List available command profiles")

    commands_sync = commands_sub.add_parser(
        "sync",
        help="Synchronize one command profile",
    )
    commands_sync.add_argument(
        "--profile",
        choices=VALID_COMMAND_PROFILES,
        default="daily",
        help="Command profile to sync (default: daily)",
    )
    commands_sync.add_argument(
        "--include",
        action="append",
        choices=VALID_OPTIONAL_GROUPS,
        default=[],
        help="Additional optional group to include; may be repeated",
    )
    commands_sync.add_argument("--source-dir", help="Slash command source directory")
    commands_sync.add_argument("--target-dir", help="Claude Code hm command directory")
    commands_sync.add_argument("--dry-run", action="store_true")

    commands_enable = commands_sub.add_parser(
        "enable",
        help="Enable optional command groups on top of Daily commands",
    )
    commands_enable.add_argument(
        "profiles",
        nargs="+",
        choices=(*VALID_OPTIONAL_GROUPS, "full"),
        help="Optional groups to enable",
    )
    commands_enable.add_argument("--source-dir", help="Slash command source directory")
    commands_enable.add_argument("--target-dir", help="Claude Code hm command directory")
    commands_enable.add_argument("--dry-run", action="store_true")

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
        return asyncio.run(cmd_quickstart(args.project, args.client, args.limit))

    if command == "doctor":
        return asyncio.run(cmd_doctor(args.project))

    if command == "skill-governance":
        if args.skill_governance_action is None:
            skill_governance.print_help()
            return 0
        if args.skill_governance_action == "list-candidates":
            return asyncio.run(
                cmd_list_procedural_candidates(args.project, status=args.status)
            )
        if args.skill_governance_action == "search":
            return asyncio.run(cmd_search_skills(args.project, args.query, args.limit))
        if args.skill_governance_action == "suggest":
            return asyncio.run(
                cmd_suggest_procedural(
                    args.project,
                    args.activation_condition,
                    args.steps,
                    args.termination_condition,
                    success_examples=args.success_examples,
                    source_session_id=args.source_session_id,
                    source=args.source,
                    confidence=args.confidence,
                )
            )
        if args.skill_governance_action == "confirm":
            return asyncio.run(cmd_confirm_procedural(args.candidate_id))
        if args.skill_governance_action == "reject":
            return asyncio.run(cmd_reject_procedural(args.candidate_id))
        if args.skill_governance_action == "record-result":
            return asyncio.run(
                cmd_record_skill_result(args.skill_id, success=args.success)
            )
        skill_governance.error(
            f"Unknown skill governance action: {args.skill_governance_action}"
        )

    if command == "maintenance":
        if args.maintenance_action is None:
            maintenance.print_help()
            return 0
        if args.maintenance_action == "rebuild-vector-index":
            from harness_mem.commands.maintenance import cmd_rebuild_vector_index

            return asyncio.run(cmd_rebuild_vector_index(args.project))
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
        maintenance.error(f"Unknown maintenance action: {args.maintenance_action}")

    if command == "config":
        if args.config_action is None:
            config.print_help()
            return 0
        if args.config_action == "get":
            return cmd_config_get(args.key, args.project_root)
        if args.config_action == "set":
            return cmd_config_set(args.key, args.value, args.scope, args.project_root)
        if args.config_action == "list":
            return cmd_config_list(args.project_root)
        if args.config_action == "validate":
            return cmd_config_validate(args.project_root)
        config.error(f"Unknown config action: {args.config_action}")

    if command == "integration":
        if args.integration_action is None:
            integration.print_help()
            return 0
        if args.integration_action == "install-cursor-hook":
            return cmd_install_cursor_hook(args.project_root, args.force)
        if args.integration_action == "install-claude-hook":
            return cmd_install_claude_hook(args.project_root, args.force)
        if args.integration_action == "commands":
            if args.commands_action is None:
                commands.print_help()
                return 0
            if args.commands_action == "list":
                return cmd_list_command_profiles()
            if args.commands_action == "sync":
                return cmd_sync_commands(
                    profile=args.profile,
                    include=args.include,
                    source_dir=args.source_dir,
                    target_dir=args.target_dir,
                    dry_run=args.dry_run,
                )
            if args.commands_action == "enable":
                return cmd_enable_command_profiles(
                    profiles=args.profiles,
                    source_dir=args.source_dir,
                    target_dir=args.target_dir,
                    dry_run=args.dry_run,
                )
            commands.error(f"Unknown commands action: {args.commands_action}")
        integration.error(f"Unknown integration action: {args.integration_action}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
