"""CLI entry point for harness-mem."""

from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

from harness_mem import __version__
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile
from harness_mem.cli_commands import (
    cmd_correct,
    cmd_confirm_rule,
    cmd_reject_rule,
    cmd_list_candidates,
    cmd_confirmed_rules,
    cmd_handoff,
)


DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"


def main():
    parser = argparse.ArgumentParser(prog="harness-mem")
    parser.add_argument("--version", action="version", version=f"harness-mem {__version__}")
    sub = parser.add_subparsers(dest="command")

    # init
    sub.add_parser("init", help="Initialize harness-mem data directory")

    # ingest
    ingest = sub.add_parser("ingest", help="Ingest Claude Code or Codex sessions")
    ingest.add_argument(
        "client",
        nargs="?",
        default="claude-code",
        choices=["claude-code", "codex"],
        help="Session source adapter (default: claude-code)",
    )
    ingest.add_argument("--project", help="Project name (required for claude-code)")
    ingest.add_argument("--limit", type=int, default=10, help="Max sessions to ingest")

    # wake-up
    wake_up = sub.add_parser("wake-up", help="Generate wake-up context")
    wake_up.add_argument("--project", required=True, help="Project name")

    # search
    search = sub.add_parser("search", help="Search memory")
    search.add_argument("--project", required=True, help="Project name")
    search.add_argument("--query", required=True, help="Search query")

    # timeline
    timeline = sub.add_parser("timeline", help="Show observation timeline")
    timeline.add_argument("--project", required=True, help="Project name")
    timeline.add_argument("--limit", type=int, default=50, help="Max results")

    # show
    show = sub.add_parser("show", help="Show a specific observation")
    show.add_argument("--project", required=True, help="Project name")
    show.add_argument("--id", required=True, dest="observation_id", help="Observation ID")

    # status
    status = sub.add_parser("status", help="Show memory status")
    status.add_argument("--project", help="Project name")

    # profile
    profile_cmd = sub.add_parser("profile", help="Show project profile")
    profile_cmd.add_argument("--project", required=True, help="Project name")

    # correct
    correct_cmd = sub.add_parser("correct", help="Create a rule candidate from a correction")
    correct_cmd.add_argument("--session-id", required=True, dest="session_id", help="Session ID")
    correct_cmd.add_argument("--project", required=True, help="Project name")
    correct_cmd.add_argument("--pattern", required=True, help="Rule pattern")
    correct_cmd.add_argument("--trigger", required=True, help="Trigger scenario")

    # confirm-rule
    confirm_cmd = sub.add_parser("confirm-rule", help="Confirm a rule candidate")
    confirm_cmd.add_argument("--rule-id", required=True, dest="rule_id", help="Rule candidate ID")

    # reject-rule
    reject_cmd = sub.add_parser("reject-rule", help="Reject a rule candidate")
    reject_cmd.add_argument("--rule-id", required=True, dest="rule_id", help="Rule candidate ID")

    # list-candidates
    list_cand_cmd = sub.add_parser("list-candidates", help="List rule candidates")
    list_cand_cmd.add_argument("--project", required=True, help="Project name")
    list_cand_cmd.add_argument("--status", help="Filter by status (pending/accepted/rejected)")

    # confirmed-rules
    confirmed_cmd = sub.add_parser("confirmed-rules", help="List confirmed rules")
    confirmed_cmd.add_argument("--project", required=True, help="Project name")

    # handoff
    handoff_cmd = sub.add_parser("handoff", help="Create or update a task handoff")
    handoff_cmd.add_argument("--project", required=True, help="Project name")
    handoff_cmd.add_argument("--task-id", required=True, dest="task_id", help="Task ID")
    handoff_cmd.add_argument("--summary", required=True, help="Task summary")
    handoff_cmd.add_argument("--status", default="in_progress", help="Task status")
    handoff_cmd.add_argument("--next-step", dest="next_steps", action="append", default=[], help="Next step (can repeat)")
    handoff_cmd.add_argument("--blocker", dest="blockers", action="append", default=[], help="Blocker (can repeat)")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0

    if args.command == "init":
        DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)
        print(f"Initialized at {DEFAULT_DATA_DIR}")
        return 0

    if args.command == "status":
        if not DEFAULT_DATA_DIR.exists():
            print("Not initialized. Run: harness-mem init")
            return 1
        return asyncio.run(cmd_status(args.project))

    if args.command == "wake-up":
        return asyncio.run(cmd_wake_up(args.project))

    if args.command == "search":
        return asyncio.run(cmd_search(args.project, args.query))

    if args.command == "timeline":
        return asyncio.run(cmd_timeline(args.project, args.limit))

    if args.command == "show":
        return asyncio.run(cmd_show(args.project, args.observation_id))

    if args.command == "ingest":
        return asyncio.run(cmd_ingest(args.client, args.project, args.limit))

    if args.command == "profile":
        return asyncio.run(cmd_profile(args.project))

    if args.command == "correct":
        return asyncio.run(cmd_correct(args.session_id, args.project, args.pattern, args.trigger))

    if args.command == "confirm-rule":
        return asyncio.run(cmd_confirm_rule(args.rule_id))

    if args.command == "reject-rule":
        return asyncio.run(cmd_reject_rule(args.rule_id))

    if args.command == "list-candidates":
        return asyncio.run(cmd_list_candidates(args.project, args.status))

    if args.command == "confirmed-rules":
        return asyncio.run(cmd_confirmed_rules(args.project))

    if args.command == "handoff":
        return asyncio.run(cmd_handoff(
            args.project, args.task_id, args.summary,
            status=args.status, next_steps=args.next_steps, blockers=args.blockers
        ))

    return 0


async def _status_project_async(backend: LocalMemoryBackend, project_name: str):
    """Show status for a specific project."""
    all_obs = await backend.verbatim_store.list(limit=10000)
    project_obs = [
        o for o in all_obs
        if o.metadata.get("project_name") == project_name
        or project_name in (getattr(o, "session_id", "") or "")
    ]
    entries = await backend.structured_store.list_memory_entries(project_name, limit=1000)
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=10)
    rules = await backend.structured_store.list_confirmed_rules(project_name)

    print(f"Project: {project_name}")
    print(f"  Observations: {len(project_obs)}")
    print(f"  Memory entries: {len(entries)}")
    print(f"  Task handoffs: {len(handoffs)}")
    print(f"  Confirmed rules: {len(rules)}")


async def cmd_status(project_name: str | None = None) -> int:
    """Show backend status, optionally scoped to a project."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        if project_name:
            await _status_project_async(backend, project_name)
        else:
            print("harness-mem is ready")
            print(f"Data directory: {DEFAULT_DATA_DIR}")
    finally:
        await backend.close()
    return 0


async def cmd_wake_up(project_name: str) -> int:
    """Generate wake-up context for a project."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    try:
        # Load project profile
        profile = await profile_store.get(project_name)
        if profile:
            print(f"# Project Profile: {profile.project_name}")
            print(f"Description: {profile.description}")
            print(f"Stacks: {', '.join(profile.stacks)}")
            if profile.key_files:
                print(f"Key files:")
                for f in profile.key_files[:5]:
                    print(f"  - {f}")
            print()

        # Load latest handoffs
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
        if handoffs:
            print("# Recent Tasks")
            for h in handoffs:
                print(f"## [{h.status}] {h.summary}")
                if h.next_steps:
                    print(f"  Next: {h.next_steps[0]}")
                if h.blockers:
                    print(f"  Blockers: {', '.join(h.blockers)}")
            print()

        # Load confirmed rules
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        if rules:
            print(f"# Rules ({len(rules)} confirmed)")
            for r in rules[:5]:
                print(f"- **{r.trigger}**: {r.pattern[:80]}")
            print()

        # Load recent memory entries
        entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
        if entries:
            print(f"# Memory ({len(entries)} recent)")
            for e in entries:
                print(f"- [{e.category}] {e.content[:100]}")
            print()
    finally:
        await backend.close()
    return 0


async def cmd_search(project_name: str, query: str) -> int:
    """Search memory for a project."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        print(f"# Search: {query}")
        print()

        entries = await backend.structured_store.search_memory_entries(query, project_name, limit=10)
        if entries:
            print(f"## Memory Entries ({len(entries)} results)")
            for e in entries:
                print(f"- [{e.category}] {e.content[:150]}")
            print()

        obs_list = await backend.verbatim_store.search(query, limit=50)
        obs_list = [
            o for o in obs_list
            if o.metadata.get("project_name") == project_name
            or project_name in (getattr(o, "session_id", "") or "")
        ][:10]
        if obs_list:
            print(f"## Observations ({len(obs_list)} results)")
            for o in obs_list:
                preview = o.raw_content[:200].replace("\n", " ")
                print(f"- [{o.session_id}] {preview}")
            print()
    finally:
        await backend.close()
    return 0


async def cmd_timeline(project_name: str, limit: int = 50) -> int:
    """Show timeline of observations."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        obs_list = await backend.verbatim_store.timeline(limit=limit * 5)
        obs_list = [
            o for o in obs_list
            if o.metadata.get("project_name") == project_name
            or project_name in (getattr(o, "session_id", "") or "")
        ][:limit]
        print(f"# Timeline ({len(obs_list)} observations)")
        for o in obs_list:
            ts = o.timestamp.strftime("%Y-%m-%d %H:%M") if o.timestamp else "?"
            preview = o.raw_content[:100].replace("\n", " ")
            print(f"- {ts} [{o.session_id}] {preview}")
        print()
    finally:
        await backend.close()
    return 0


async def cmd_show(project_name: str, observation_id: str) -> int:
    """Show a specific observation."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        obs = await backend.verbatim_store.get(observation_id)
        if not obs:
            print(f"Observation not found: {observation_id}")
            return 1

        print(f"# Observation: {obs.id}")
        print(f"Session: {obs.session_id}")
        print(f"Client: {obs.client}")
        print(f"Type: {obs.content_type}")
        print(f"Timestamp: {obs.timestamp}")
        print(f"Tags: {', '.join(obs.tags)}")
        print()
        print(obs.raw_content)
    finally:
        await backend.close()
    return 0


async def cmd_ingest(client: str, project_name: str | None = None, limit: int = 10) -> int:
    """Ingest sessions for a supported client."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        if client == "claude-code":
            if not project_name:
                print("Claude Code ingest requires --project <project-name>.")
                return 1

            adapter = ClaudeCodeAdapter(backend)
            print(f"Ingesting {client} sessions for project: {project_name}")
            result = await adapter.ingest_project(project_name, limit=limit, min_size_kb=0)

            if result["sessions_found"] == 0:
                print(f"No {client} sessions found for project: {project_name}")
                return 1

            print(f"Sessions found: {result['sessions_found']}")
            print(f"Ingested: {result['ingested']} sessions")
            if result["errors"] > 0:
                print(f"Errors: {result['errors']}")

            # Auto-detect project profile if not exists
            profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
            existing = await profile_store.get(project_name)
            if not existing:
                sessions_dir = Path.home() / ".claude" / "projects"
                project_path = sessions_dir / project_name
                if project_path.exists():
                    profile = build_project_profile(project_path, project_name)
                    await profile_store.save(profile)
                    print(f"Auto-detected profile: {', '.join(profile.stacks)}")
                else:
                    # Try fixtures
                    repo_root = Path(__file__).resolve().parent.parent.parent
                    fixture_path = repo_root / "fixtures" / project_name
                    if fixture_path.exists():
                        profile = build_project_profile(fixture_path, project_name)
                        await profile_store.save(profile)
                        print(f"Auto-detected profile from fixture: {', '.join(profile.stacks)}")
            return 0

        adapter = CodexAdapter(backend)
        print(f"Ingesting {client} sessions")
        result = await adapter.ingest(limit=limit, min_size_kb=0)
        if result["sessions_found"] == 0:
            print(f"No {client} sessions found.")
            return 1

        print(f"Sessions found: {result['sessions_found']}")
        print(f"Ingested: {result['ingested']} sessions")
        if result["errors"] > 0:
            print(f"Errors: {result['errors']}")
    finally:
        await backend.close()
    return 0


async def cmd_profile(project_name: str) -> int:
    """Show project profile."""
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    profile = await profile_store.get(project_name)
    if not profile:
        print(f"No profile found for: {project_name}")
        return 1
    print(f"Project: {profile.project_name}")
    print(f"Description: {profile.description}")
    print(f"Stacks: {', '.join(profile.stacks)}")
    print(f"Key files ({len(profile.key_files)}):")
    for f in profile.key_files:
        print(f"  - {f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
