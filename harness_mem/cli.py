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
    cmd_assign_memory_types,
    cmd_correct,
    cmd_confirm_procedural,
    cmd_confirm_rule,
    cmd_confirm_supersede,
    cmd_confirmed_rules,
    cmd_doctor,
    cmd_handoff,
    cmd_import,
    cmd_ingest,
    cmd_list_candidates,
    cmd_profile,
    cmd_profile_edit,
    cmd_purge,
    cmd_quickstart,
    cmd_record_skill_result,
    cmd_reject_procedural,
    cmd_reject_rule,
    cmd_reject_supersede,
    cmd_search,
    cmd_search_raw,
    cmd_search_skills,
    cmd_show,
    cmd_status,
    cmd_suggest_procedural,
    cmd_suggest_supersede,
    cmd_timeline,
    cmd_trace_relations,
    cmd_use,
    cmd_wake_up,
)
from harness_mem.commands.support import DEFAULT_DATA_DIR

# Test compatibility: tests monkeypatch these via cli module.
from harness_mem.adapters.codex.adapter import CodexAdapter  # noqa: F401

__all__ = [
    "main",
    "cmd_assign_memory_types",
    "cmd_correct",
    "cmd_confirm_procedural",
    "cmd_confirm_rule",
    "cmd_confirm_supersede",
    "cmd_confirmed_rules",
    "cmd_doctor",
    "cmd_handoff",
    "cmd_import",
    "cmd_ingest",
    "cmd_list_candidates",
    "cmd_profile",
    "cmd_profile_edit",
    "cmd_purge",
    "cmd_quickstart",
    "cmd_record_skill_result",
    "cmd_reject_procedural",
    "cmd_reject_rule",
    "cmd_reject_supersede",
    "cmd_search",
    "cmd_search_raw",
    "cmd_search_skills",
    "cmd_show",
    "cmd_status",
    "cmd_suggest_procedural",
    "cmd_suggest_supersede",
    "cmd_timeline",
    "cmd_trace_relations",
    "cmd_use",
    "cmd_wake_up",
]


def main():
    """Run the maintenance-only CLI surface."""
    # Handle --completion before full argument parsing.
    if "--completion" in sys.argv:
        from harness_mem.shell_completion import print_completion

        for arg in sys.argv[1:]:
            if arg.startswith("--completion="):
                shell = arg.split("=", 1)[1]
                print_completion(shell)
                return 0
            if arg == "--completion":
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    print_completion(sys.argv[idx + 1])
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
    doctor.add_argument("-p", "--project")
    doctor.set_defaults(command_name="doctor")

    import_cmd = sub.add_parser(
        "import",
        help="Import memory drafts from AI skills into the candidate layer",
    )
    import_cmd.add_argument("file", help="Path to legacy or AI-generated JSON draft")
    import_cmd.add_argument("-p", "--project")
    import_cmd.set_defaults(command_name="import")

    purge = sub.add_parser("purge", help="Soft-delete observations or structured memory")
    purge.add_argument("-p", "--project")
    purge.add_argument("--before", required=True, help="YYYY-MM-DD")
    purge.add_argument("--category", choices=["observations", "structured", "all"], default="all")
    purge.add_argument("--dry-run", action="store_true")
    purge.add_argument("--stale-only", action="store_true", help="Only include never-accessed or stale entries")
    purge.set_defaults(command_name="purge")

    maintenance = sub.add_parser("maintenance", help="One-shot maintenance utilities")
    maintenance.add_argument(
        "action",
        choices=["assign-memory-types", "rebuild-vector-index", "rebuild-verbatim-index"],
        help="Maintenance action to run",
    )
    maintenance.add_argument("-p", "--project", help="Project name")
    apply_group = maintenance.add_mutually_exclusive_group()
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
    maintenance.set_defaults(command_name="maintenance")

    args = parser.parse_args()
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

    if command == "import":
        return asyncio.run(cmd_import(args.file, args.project))

    if command == "purge":
        return asyncio.run(
            cmd_purge(args.before, args.category, args.dry_run, args.project, stale_only=args.stale_only)
        )

    if command == "maintenance":
        if args.action == "assign-memory-types":
            return asyncio.run(cmd_assign_memory_types(args.project, apply=not args.dry_run))
        if args.action == "rebuild-vector-index":
            from harness_mem.commands.maintenance import cmd_rebuild_vector_index

            return asyncio.run(cmd_rebuild_vector_index(args.project))
        if args.action == "rebuild-verbatim-index":
            from harness_mem.commands.maintenance import cmd_rebuild_verbatim_index

            return asyncio.run(cmd_rebuild_verbatim_index(args.project))
        parser.error(f"Unknown maintenance action: {args.action}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
