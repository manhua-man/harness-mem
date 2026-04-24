"""CLI entry point for harness-mem."""

from __future__ import annotations
import argparse
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

from harness_mem import __version__
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.core.schemas.project_profile import ProjectProfile
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


def _ensure_data_dir() -> None:
    DEFAULT_DATA_DIR.mkdir(parents=True, exist_ok=True)


def _active_project_path() -> Path:
    return DEFAULT_DATA_DIR / "active_project.txt"


def _get_active_project() -> str | None:
    active_project_path = _active_project_path()
    if not active_project_path.exists():
        return None
    project = active_project_path.read_text(encoding="utf-8").strip()
    return project or None


def _set_active_project(project_name: str) -> None:
    _ensure_data_dir()
    _active_project_path().write_text(project_name.strip(), encoding="utf-8")


def _resolve_project_name(
    project_name: str | None,
    *,
    required: bool = True,
    action_label: str = "this command",
) -> str | None:
    resolved = project_name or os.environ.get("HARNESS_MEM_PROJECT") or _get_active_project()
    if required and not resolved and _can_prompt():
        resolved = _prompt_text("Project name")
        if resolved:
            _set_active_project(resolved)
    if required and not resolved:
        print(
            f"Project name required for {action_label}. Pass -p/--project or run: harness-mem use <project-name>"
        )
        return None
    return resolved


def _can_prompt() -> bool:
    try:
        return bool(sys.stdin and sys.stdin.isatty())
    except Exception:
        return False


def _prompt_text(
    label: str,
    default: str | None = None,
    *,
    allow_empty: bool = False,
    allow_clear: bool = False,
) -> str | None:
    if not _can_prompt():
        return default if allow_empty else None

    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
        if allow_clear and value == "!clear":
            return ""
        if value:
            return value
        if default is not None:
            return default
        if allow_empty:
            return ""
        print(f"{label} is required.")


def _prompt_list(label: str) -> list[str]:
    if not _can_prompt():
        return []

    print(f"{label} (one per line, blank to finish):")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            return values
        values.append(value)


def _project_roots(project_name: str) -> list[Path]:
    repo_root = Path(__file__).resolve().parent.parent
    cwd = Path.cwd()
    return [
        cwd,
        cwd / project_name,
        cwd.parent / project_name,
        repo_root.parent / "fixtures" / project_name,
    ]


def _find_project_root(project_name: str) -> Path | None:
    for candidate in _project_roots(project_name):
        if candidate.exists() and candidate.is_dir():
            return candidate
    return None


async def _ensure_project_profile(project_name: str) -> tuple[object | None, Path | None]:
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    existing = await profile_store.get(project_name)
    if existing:
        return existing, None

    root = _find_project_root(project_name)
    if root is None:
        return None, None

    profile = build_project_profile(root, project_name)
    await profile_store.save(profile)
    return profile, root


def _claude_session_count(project_name: str) -> int:
    return len(_recent_claude_sessions(project_name, limit=None))


def _codex_session_count() -> int:
    return len(_recent_codex_sessions(limit=None))


def _recent_claude_sessions(project_name: str, limit: int | None = 3) -> list[dict]:
    adapter = ClaudeCodeAdapter(None)  # type: ignore[arg-type]  # backend unused for session listing
    return adapter.list_project_sessions(project_name, min_size_kb=0, limit=limit)


def _recent_codex_sessions(limit: int | None = 3) -> list[dict]:
    adapter = CodexAdapter(None)  # type: ignore[arg-type]  # backend unused for session listing
    sessions = adapter.list_sessions(min_size_kb=0)
    if limit is None:
        return sessions
    return sessions[:limit]


def _session_identifier(session: dict) -> str:
    session_id = session.get("session_id")
    if session_id:
        return str(session_id)
    name = session.get("name")
    if name:
        return Path(str(name)).stem
    return "unknown-session"


def _format_session_summary(session: dict) -> str:
    session_id = _session_identifier(session)
    modified = session.get("mtime")
    if isinstance(modified, datetime):
        modified_text = modified.astimezone().strftime("%Y-%m-%d %H:%M")
    else:
        modified_text = "unknown time"
    size = session.get("size")
    if size:
        return f"- {session_id} ({modified_text}, {size})"
    return f"- {session_id} ({modified_text})"


def _print_recent_sessions(title: str, sessions: list[dict]) -> None:
    if not sessions:
        return
    print(title)
    for session in sessions:
        print(f"  {_format_session_summary(session)}")


def _codex_scope_note() -> str:
    return "Codex sessions are global across projects, not project-scoped, and need manual review before ingest."


def _profile_text(profile: object | None) -> str:
    if not profile:
        return ""
    description = getattr(profile, "description", "") or ""
    stacks = getattr(profile, "stacks", []) or []
    key_files = getattr(profile, "key_files", []) or []
    conventions = getattr(profile, "conventions", []) or []
    return description + " " + " ".join(stacks) + " " + " ".join(key_files) + " " + " ".join(conventions)


def _chars_to_tokens(chars: int) -> int:
    return round(chars / 4)


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _disclosure_level(tokens: int) -> str:
    if tokens < 500:
        return "L0"
    if tokens < 2000:
        return "L1"
    if tokens < 8000:
        return "L2"
    if tokens < 32000:
        return "L3"
    return "L4+"


def _wake_budget(profile: object | None, entries: list, rules: list, handoffs: list) -> tuple[int, str]:
    profile_tokens = _chars_to_tokens(len(_profile_text(profile)))
    entry_tokens = _chars_to_tokens(sum(len(e.content) for e in entries))
    rule_tokens = _chars_to_tokens(sum(len(r.pattern) + len(r.trigger) for r in rules))
    handoff_tokens = _chars_to_tokens(
        sum(len(h.summary) + sum(len(n) for n in h.next_steps) for h in handoffs)
    )
    total_tokens = profile_tokens + entry_tokens + rule_tokens + handoff_tokens
    return total_tokens, _disclosure_level(total_tokens)


def _memory_entry_source_label(entry) -> str:
    for tag in getattr(entry, "tags", []) or []:
        if tag.startswith("pattern-source:"):
            return tag.split(":", 1)[1]
    return getattr(entry, "category", "unknown")


def _suggested_next_step(
    *,
    project_name: str,
    observation_count: int,
    memory_entry_count: int,
    claude_sessions: list[dict],
    codex_sessions: list[dict],
) -> tuple[str, str]:
    if observation_count == 0:
        if claude_sessions:
            latest = _session_identifier(claude_sessions[0])
            return (
                f"harness-mem ingest claude-code -n {min(5, len(claude_sessions))}",
                f"Recent Claude Code sessions were found. Start by ingesting the newest session: {latest}.",
            )
        if codex_sessions:
            return (
                "Review recent Codex sessions before any codex ingest",
                f"{_codex_scope_note()} Only run `harness-mem ingest codex -p {project_name}` if the sessions shown above belong to this project.",
            )
        return (
            f"harness-mem ingest claude-code -p {project_name} -n 5",
            "No local sessions have been ingested yet.",
        )

    if memory_entry_count == 0 and claude_sessions:
        latest = _session_identifier(claude_sessions[0])
        return (
            "harness-mem ds",
            f"Recent Claude Code sessions are already in memory. Distill structured memory from the newest session: {latest}.",
        )

    if memory_entry_count == 0:
        return (
            "harness-mem search <query>",
            "Observations are searchable, but wake-up needs structured memory before it becomes useful.",
        )

    return (
        "harness-mem wake",
        "Structured memory is ready, so wake-up is the shortest path back into project context.",
    )


async def _project_state(project_name: str) -> dict[str, int]:
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        all_obs = await backend.verbatim_store.list(limit=10000)
        project_obs = [o for o in all_obs if o.metadata.get("project_name") == project_name]
        entries = await backend.structured_store.list_memory_entries(project_name, limit=1000)
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=100)
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        return {
            "observations": len(project_obs),
            "memory_entries": len(entries),
            "task_handoffs": len(handoffs),
            "confirmed_rules": len(rules),
        }
    finally:
        await backend.close()


def main():
    # Handle --completion before full argument parsing
    if "--completion" in sys.argv:
        from harness_mem.shell_completion import print_completion
        for arg in sys.argv[1:]:
            if arg.startswith("--completion="):
                shell = arg.split("=", 1)[1]
                print_completion(shell)
                return
            elif arg == "--completion":
                idx = sys.argv.index(arg)
                if idx + 1 < len(sys.argv):
                    print_completion(sys.argv[idx + 1])
                    return
        print("--completion requires a shell argument: bash, zsh, or fish", file=sys.stderr)
        return 1

    parser = argparse.ArgumentParser(prog="harness-mem")
    parser.add_argument("--version", action="version", version=f"harness-mem {__version__}")
    sub = parser.add_subparsers(dest="command")

    # init
    init_cmd = sub.add_parser("init", help="Initialize harness-mem data directory")
    init_cmd.set_defaults(command_name="init")

    # use
    use_cmd = sub.add_parser("use", help="Set or show the active project")
    use_cmd.add_argument("project", nargs="?", help="Project name")
    use_cmd.set_defaults(command_name="use")

    # quickstart
    quickstart_cmd = sub.add_parser("quickstart", aliases=["qs"], help="Initialize, pick a project, and try ingestion")
    quickstart_cmd.add_argument("project", nargs="?", help="Project name")
    quickstart_cmd.add_argument(
        "-c",
        "--client",
        choices=["auto", "claude-code", "codex", "skip"],
        default="auto",
        help="Which client to ingest during quickstart",
    )
    quickstart_cmd.add_argument("-n", "--limit", type=int, default=5, help="Max sessions to ingest during quickstart")
    quickstart_cmd.set_defaults(command_name="quickstart")

    # doctor
    doctor_cmd = sub.add_parser("doctor", help="Inspect local setup and suggest next steps")
    doctor_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    doctor_cmd.set_defaults(command_name="doctor")

    # ingest
    ingest = sub.add_parser("ingest", help="Ingest Claude Code or Codex sessions")
    ingest.set_defaults(command_name="ingest")
    ingest.add_argument(
        "client",
        nargs="?",
        default="claude-code",
        choices=["claude-code", "codex"],
        help="Session source adapter (default: claude-code)",
    )
    ingest.add_argument("-p", "--project", help="Project name (defaults to active project)")
    ingest.add_argument("-n", "--limit", type=int, default=10, help="Max sessions to ingest")
    ingest.add_argument(
        "--full-rescan",
        action="store_true",
        help="Ignore last-ingest cursor and ingest all sessions (default: incremental)"
    )

    # wake-up
    wake_up = sub.add_parser("wake-up", aliases=["wake"], help="Generate wake-up context")
    wake_up.set_defaults(command_name="wake-up")
    wake_up.add_argument("-p", "--project", help="Project name (defaults to active project)")

    # search
    search = sub.add_parser("search", help="Search memory")
    search.set_defaults(command_name="search")
    search.add_argument("query_arg", nargs="?", help="Search query")
    search.add_argument("-p", "--project", help="Project name (defaults to active project)")
    search.add_argument("-q", "--query", help="Search query")
    search.add_argument(
        "--mode",
        choices=["auto", "fts", "hybrid"],
        default="auto",
        help="Search mode (default: auto)",
    )

    # timeline
    timeline = sub.add_parser("timeline", aliases=["tl"], help="Show observation timeline")
    timeline.set_defaults(command_name="timeline")
    timeline.add_argument("limit_arg", nargs="?", type=int, help="Max results (default: 50)")
    timeline.add_argument("-p", "--project", help="Project name (defaults to active project)")
    timeline.add_argument("-n", "--limit", type=int, default=50, help="Max results (default: 50)")

    # show
    show = sub.add_parser("show", help="Show a specific observation")
    show.set_defaults(command_name="show")
    show.add_argument("observation_id_arg", nargs="?", help="Observation ID")
    show.add_argument("-p", "--project", help="Project name (optional)")
    show.add_argument("-i", "--id", dest="observation_id", help="Observation ID (legacy, use -o instead)")
    show.add_argument("-o", "--observation-id", dest="observation_id", help="Observation ID")

    # status
    status = sub.add_parser("status", aliases=["st"], help="Show memory status")
    status.set_defaults(command_name="status")
    status.add_argument("-p", "--project", help="Project name (defaults to active project)")

    # profile
    profile_cmd = sub.add_parser("profile", help="Show project profile")
    profile_cmd.set_defaults(command_name="profile")
    profile_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    profile_cmd.add_argument("--edit", action="store_true", help="Edit profile fields interactively")

    # distill
    distill_cmd = sub.add_parser("distill", aliases=["ds"], help="Extract structured memory from sessions")
    distill_cmd.set_defaults(command_name="distill")
    distill_cmd.add_argument("session_id_arg", nargs="?", help="Session ID (optional)")
    distill_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    distill_cmd.add_argument("-s", "--session-id", dest="session_id", help="Session ID (optional; distill all if omitted)")
    distill_cmd.add_argument("-c", "--category", dest="category", choices=["architecture", "convention", "api", "bug", "decision"], help="Filter entries by category")

    # correct
    correct_cmd = sub.add_parser("correct", help="Create a rule candidate from a correction (interactive)")
    correct_cmd.set_defaults(command_name="correct")
    correct_cmd.add_argument("session_id_arg", nargs="?", help="Session ID")
    correct_cmd.add_argument("-s", "--session-id", dest="session_id", help="Session ID")
    correct_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    correct_cmd.add_argument("-r", "--pattern", help="Rule pattern")
    correct_cmd.add_argument("-t", "--trigger", help="Trigger scenario")

    # confirm-rule
    confirm_cmd = sub.add_parser("confirm-rule", aliases=["confirm"], help="Confirm a rule candidate")
    confirm_cmd.set_defaults(command_name="confirm-rule")
    confirm_cmd.add_argument("rule_id_arg", nargs="?", help="Rule candidate ID")
    confirm_cmd.add_argument("-r", "--rule-id", dest="rule_id", help="Rule candidate ID")

    # reject-rule
    reject_cmd = sub.add_parser("reject-rule", aliases=["reject"], help="Reject a rule candidate")
    reject_cmd.set_defaults(command_name="reject-rule")
    reject_cmd.add_argument("rule_id_arg", nargs="?", help="Rule candidate ID")
    reject_cmd.add_argument("-r", "--rule-id", dest="rule_id", help="Rule candidate ID")

    # purge
    purge_cmd = sub.add_parser("purge", help="Soft-delete observations/structured memory")
    purge_cmd.set_defaults(command_name="purge")
    purge_cmd.add_argument("--before", required=True, help="Delete entries before this date (YYYY-MM-DD)")
    purge_cmd.add_argument("--category", choices=["observations", "structured", "all"], default="all", help="Category to purge")
    purge_cmd.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")

    # list-candidates
    list_cand_cmd = sub.add_parser("list-candidates", aliases=["candidates"], help="List rule candidates")
    list_cand_cmd.set_defaults(command_name="list-candidates")
    list_cand_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    list_cand_cmd.add_argument("--status", help="Filter by status (pending/accepted/rejected)")

    # confirmed-rules
    confirmed_cmd = sub.add_parser("confirmed-rules", aliases=["rules"], help="List confirmed rules")
    confirmed_cmd.set_defaults(command_name="confirmed-rules")
    confirmed_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")

    # handoff
    handoff_cmd = sub.add_parser("handoff", help="Create or update a task handoff (interactive)")
    handoff_cmd.set_defaults(command_name="handoff")
    handoff_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    handoff_cmd.add_argument("-t", "--task-id", dest="task_id", help="Task ID")
    handoff_cmd.add_argument("-s", "--summary", help="Task summary")
    handoff_cmd.add_argument("--status", default="in_progress", help="Task status")
    handoff_cmd.add_argument("-n", "--next-step", dest="next_steps", action="append", default=[], help="Next step (can repeat)")
    handoff_cmd.add_argument("-b", "--blocker", dest="blockers", action="append", default=[], help="Blocker (can repeat)")

    # api
    api_cmd = sub.add_parser("api", help="Start the REST API server")
    api_cmd.set_defaults(command_name="api")
    api_cmd.add_argument("-p", "--port", type=int, default=8000, help="Port to listen on (default: 8000)")
    api_cmd.add_argument("-H", "--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")

    args = parser.parse_args()
    command = getattr(args, "command_name", args.command)

    if command is None:
        parser.print_help()
        return 0

    if command == "init":
        _ensure_data_dir()
        print(f"Initialized at {DEFAULT_DATA_DIR}")
        return 0

    if command == "use":
        return cmd_use(args.project)

    if command == "quickstart":
        return asyncio.run(cmd_quickstart(args.project, args.client, args.limit))

    if command == "doctor":
        return asyncio.run(cmd_doctor(args.project))

    if command == "status":
        if not DEFAULT_DATA_DIR.exists():
            print("Not initialized. Run: harness-mem init")
            return 1
        return asyncio.run(cmd_status(args.project))

    if command == "wake-up":
        return asyncio.run(cmd_wake_up(args.project))

    if command == "search":
        query = args.query or args.query_arg
        if not query:
            print("No query provided. Try:")
            print("  harness-mem search \"your search terms\"")
            print("  harness-mem search --project <project> \"terms\"")
            return 1
        return asyncio.run(cmd_search(args.project, query, args.mode))

    if command == "timeline":
        limit = args.limit if args.limit is not None else (args.limit_arg or 50)
        return asyncio.run(cmd_timeline(args.project, limit))

    if command == "show":
        observation_id = args.observation_id or args.observation_id_arg
        if not observation_id:
            parser.error("show requires an observation id. Use `harness-mem show <id>` or `--id`.")
        return asyncio.run(cmd_show(args.project, observation_id))

    if command == "ingest":
        return asyncio.run(cmd_ingest(args.client, args.project, args.limit, args.full_rescan))

    if command == "profile":
        if getattr(args, 'edit', False):
            return asyncio.run(cmd_profile_edit(args.project))
        return asyncio.run(cmd_profile(args.project))

    if command == "distill":
        session_id = args.session_id or args.session_id_arg
        return asyncio.run(cmd_distill(args.project, session_id, category=getattr(args, 'category', None)))

    if command == "correct":
        session_id = args.session_id or args.session_id_arg
        if not session_id and _can_prompt():
            print("Interactive correct mode")
            session_id = _prompt_text("Session ID")
        pattern = args.pattern
        if not pattern and _can_prompt():
            pattern = _prompt_text("Rule pattern")
        trigger = args.trigger
        if not trigger and _can_prompt():
            trigger = _prompt_text("Trigger")
        if not session_id:
            parser.error("correct requires a session id. Use `harness-mem correct <session-id>` or `--session-id`.")
        if not pattern:
            parser.error("correct requires a pattern. Use `-r/--pattern` or run in an interactive terminal.")
        if not trigger:
            parser.error("correct requires a trigger. Use `-t/--trigger` or run in an interactive terminal.")
        project_name = _resolve_project_name(args.project, action_label="correct")
        if not project_name:
            return 1
        return asyncio.run(cmd_correct(session_id, project_name, pattern, trigger))

    if command == "confirm-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("confirm-rule requires a rule id. Use `harness-mem confirm-rule <id>` or `--rule-id`.")
        return asyncio.run(cmd_confirm_rule(rule_id))

    if command == "reject-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("reject-rule requires a rule id. Use `harness-mem reject-rule <id>` or `--rule-id`.")
        return asyncio.run(cmd_reject_rule(rule_id))

    if command == "purge":
        return asyncio.run(cmd_purge(args.before, args.category, args.dry_run))

    if command == "list-candidates":
        project_name = _resolve_project_name(args.project, action_label="list-candidates")
        if not project_name:
            return 1
        return asyncio.run(cmd_list_candidates(project_name, args.status))

    if command == "confirmed-rules":
        project_name = _resolve_project_name(args.project, action_label="confirmed-rules")
        if not project_name:
            return 1
        return asyncio.run(cmd_confirmed_rules(project_name))

    if command == "handoff":
        task_id = args.task_id
        summary = args.summary
        status = args.status
        next_steps = list(args.next_steps)
        blockers = list(args.blockers)
        if _can_prompt() and (not task_id or not summary):
            print("Interactive handoff mode")
            task_id = task_id or _prompt_text("Task ID")
            summary = summary or _prompt_text("Summary")
            status = _prompt_text("Status", default=status) or status
            if not next_steps:
                next_steps = _prompt_list("Next steps")
            if not blockers:
                blockers = _prompt_list("Blockers (optional)")
        if not task_id:
            parser.error("handoff requires a task id. Use `-t/--task-id` or run in an interactive terminal.")
        if not summary:
            parser.error("handoff requires a summary. Use `-s/--summary` or run in an interactive terminal.")
        project_name = _resolve_project_name(args.project, action_label="handoff")
        if not project_name:
            return 1
        return asyncio.run(cmd_handoff(
            project_name, task_id, summary,
            status=status, next_steps=next_steps, blockers=blockers
        ))

    if command == "api":
        import uvicorn
        from harness_mem.api.server import create_app
        app = create_app()
        print(f"Starting API server on {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    return 0


async def _status_project_async(backend: LocalMemoryBackend, project_name: str):
    """Show status for a specific project."""
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    all_obs = await backend.verbatim_store.list(limit=10000)
    project_obs = [
        o for o in all_obs
        if o.metadata.get("project_name") == project_name
        or project_name in (getattr(o, "session_id", "") or "")
    ]
    # actual wake-up limits
    entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    profile = await profile_store.get(project_name)

    print(f"Project: {project_name}")
    print(f"  Observations: {len(project_obs)}")
    print(f"  Memory entries: {len(entries)} (limited to 5 latest in wake-up)")
    print(f"  Task handoffs: {len(handoffs)} (limited to 3 latest in wake-up)")
    print(f"  Confirmed rules: {len(rules)}")

    # Token budget estimate
    profile_text = ""
    if profile:
        profile_text = (profile.description or "") + " " + " ".join(profile.stacks) + " " + " ".join(profile.key_files)
    entry_chars = sum(len(e.content) for e in entries)
    rule_chars = sum(len(r.pattern) + len(r.trigger) for r in rules)
    handoff_chars = sum(len(h.summary) + sum(len(n) for n in h.next_steps) for h in handoffs)
    total_tokens = round(len(profile_text) / 4) + round(entry_chars / 4) + round(rule_chars / 4) + round(handoff_chars / 4)
    if total_tokens < 500:
        level = "L0"
    elif total_tokens < 2000:
        level = "L1"
    elif total_tokens < 8000:
        level = "L2"
    elif total_tokens < 32000:
        level = "L3"
    else:
        level = "L4+"
    print(f"  Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")

    # Phase / Next step / Why
    if level in ("L3", "L4+"):
        print()
        print(f"📍 Phase: Budget Warning ({level})")
        print("→ Next: harness-mem purge --before <DATE> --category all --dry-run")
        print(f"   Why: Memory budget at {level}, archiving old data can help")
    elif len(project_obs) == 0:
        print()
        print("📍 Phase: Empty")
        print("→ Next: harness-mem ingest claude-code")
        print("   Why: No observations yet, ingest sessions to get started")
    else:
        print()
        print("📍 Phase: Healthy")
        print("→ Next: harness-mem wake")
        print("   Why: Memory is ready, wake-up is the shortest path to project context")


def cmd_use(project_name: str | None = None) -> int:
    """Set or show the active project."""
    if not project_name:
        current = _get_active_project()
        if current:
            print(f"Active project: {current}")
            return 0
        print("No active project set. Run: harness-mem use <project-name>")
        return 1

    _set_active_project(project_name)
    print(f"Active project set to: {project_name}")
    return 0


async def cmd_quickstart(
    project_name: str | None = None,
    client: str = "auto",
    limit: int = 5,
) -> int:
    """Initialize harness-mem and guide the user into their first ingest."""
    _ensure_data_dir()
    default_project = project_name or _get_active_project() or Path.cwd().name
    if not project_name and _can_prompt():
        project_name = _prompt_text("Project name", default=default_project)
    else:
        project_name = default_project

    project_name = _resolve_project_name(project_name, action_label="quickstart")
    if not project_name:
        return 1

    _set_active_project(project_name)
    print(f"Quickstart for project: {project_name}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")

    profile, source_root = await _ensure_project_profile(project_name)
    if profile and source_root:
        print(f"Profile detected from: {source_root}")
    elif profile:
        print("Profile already exists.")
    else:
        print("No local project profile detected yet.")

    claude_sessions = _recent_claude_sessions(project_name, limit=limit or 3)
    codex_sessions = _recent_codex_sessions(limit=limit or 3)
    claude_count = _claude_session_count(project_name)
    codex_count = _codex_session_count()
    print(f"Claude Code sessions: {claude_count}")
    print(f"Codex sessions (global): {codex_count}")
    _print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
    _print_recent_sessions("Recent Codex sessions (global):", codex_sessions)
    if codex_count:
        print(f"Note: {_codex_scope_note()}")

    selected_client = client
    if selected_client == "auto":
        if claude_count > 0:
            selected_client = "claude-code"
        else:
            selected_client = "skip"

    if selected_client == "claude-code" and claude_count == 0:
        print("No Claude Code sessions found for this project, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex" and codex_count == 0:
        print("No Codex sessions found, so ingest was skipped.")
        selected_client = "skip"
    elif selected_client == "codex":
        print(f"Note: {_codex_scope_note()}")

    if selected_client != "skip":
        ingest_result = await cmd_ingest(selected_client, project_name, limit)
        if ingest_result != 0:
            return ingest_result
    else:
        if client == "auto" and claude_count == 0 and codex_count > 0:
            print("Auto-ingest skipped for Codex because those sessions are not project-scoped.")
        print("Ingest skipped.")

    state = await _project_state(project_name)
    next_command, reason = _suggested_next_step(
        project_name=project_name,
        observation_count=state["observations"],
        memory_entry_count=state["memory_entries"],
        claude_sessions=claude_sessions,
        codex_sessions=codex_sessions,
    )

    print()
    print("📍 Phase: Quickstart Complete")
    print(f"→ Next: {next_command}")
    print(f"   Why: {reason}")
    print("Also useful:")
    print("  harness-mem doctor")
    return 0


async def cmd_doctor(project_name: str | None = None) -> int:
    """Inspect local setup and print actionable next steps."""
    resolved_project = _resolve_project_name(project_name, required=False, action_label="doctor")
    initialized = DEFAULT_DATA_DIR.exists()
    active_project = _get_active_project()

    print(f"harness-mem {__version__}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")
    print(f"Initialized: {'yes' if initialized else 'no'}")
    print(f"Active project: {active_project or '(none)'}")

    if not initialized:
        print("Suggested fix: run `harness-mem quickstart`.")
        return 1

    if resolved_project:
        claude_sessions = _recent_claude_sessions(resolved_project, limit=3)
        codex_sessions = _recent_codex_sessions(limit=3)
        print(f"Doctor project: {resolved_project}")
        print(f"Claude Code sessions: {_claude_session_count(resolved_project)}")
        print(f"Codex sessions (global): {_codex_session_count()}")
        _print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
        _print_recent_sessions("Recent Codex sessions (global):", codex_sessions)
        if codex_sessions:
            print(f"Note: {_codex_scope_note()}")

        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
        profile = await profile_store.get(resolved_project)
        print(f"Profile saved: {'yes' if profile else 'no'}")
        if profile and profile.stacks:
            print(f"Stacks detected: {', '.join(profile.stacks)}")

        backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        await backend.init()
        try:
            state = await _project_state(resolved_project)
            print(f"Observations: {state['observations']}")
            print(f"Memory entries: {state['memory_entries']}")
            print(f"Task handoffs: {state['task_handoffs']}")
            print(f"Confirmed rules: {state['confirmed_rules']}")

            # Budget estimate (same口径 as wake/profile/status)
            entries = await backend.structured_store.list_memory_entries(resolved_project, limit=5)
            handoffs = await backend.structured_store.get_latest_handoffs(resolved_project, limit=3)
            rules = await backend.structured_store.list_confirmed_rules(resolved_project)
            total_tokens, level = _wake_budget(profile, entries, rules, handoffs)
            print(f"Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")
            if level in ("L3", "L4+"):
                from datetime import datetime, timezone
                three_months_ago = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)).strftime("%Y-%m-%d")
                print(f"💡 Run: harness-mem purge --before {three_months_ago} --category all --dry-run")
                print("   to preview what can be archived.")

            next_command, reason = _suggested_next_step(
                project_name=resolved_project,
                observation_count=state["observations"],
                memory_entry_count=state["memory_entries"],
                claude_sessions=claude_sessions,
                codex_sessions=codex_sessions,
            )

            print()
            print("📍 Phase: Ready")
            print(f"→ Next: {next_command}")
            print(f"   Why: {reason}")
        finally:
            await backend.close()
        return 0

    print()
    print("📍 Phase: Not Initialized")
    print("→ Next: harness-mem quickstart")
    print("   Why: No active project set or data directory not initialized")
    return 0


async def cmd_status(project_name: str | None = None) -> int:
    """Show backend status, optionally scoped to a project."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        resolved_project = _resolve_project_name(project_name, required=False, action_label="status")
        if resolved_project:
            await _status_project_async(backend, resolved_project)
        else:
            print("harness-mem is ready")
            print(f"Data directory: {DEFAULT_DATA_DIR}")
            active_project = _get_active_project()
            if active_project:
                print(f"Active project: {active_project}")
                await _status_project_async(backend, active_project)
            else:
                print()
                print("📍 Phase: Not Initialized")
                print("→ Next: harness-mem quickstart")
                print("   Why: No active project set, run quickstart to get started")
    finally:
        await backend.close()
    return 0


async def cmd_wake_up(project_name: str | None) -> int:
    """Generate wake-up context for a project."""
    project_name = _resolve_project_name(project_name, action_label="wake-up")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    try:
        # Load project profile
        profile = await profile_store.get(project_name)
        if profile:
            profile_chars = len(profile.project_name or "") + len(_profile_text(profile))
            print(f"# Project Profile  (source: profile, ~{profile_chars} chars)")
            print(f"Description: {profile.description}")
            print(f"Stacks: {', '.join(profile.stacks)}")
            if profile.key_files:
                print("Key files:")
                for f in profile.key_files[:5]:
                    print(f"  - {f}")
            if profile.conventions:
                print("Conventions:")
                for convention in profile.conventions[:5]:
                    print(f"  - {convention}")
            print()
        else:
            print("# Project Profile  (source: profile, empty)")
            print()

        # Load latest handoffs
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
        if handoffs:
            hw_chars = sum(len(h.summary or "") + len(str(h.next_steps)) + len(str(h.blockers)) for h in handoffs)
            print(f"# Recent Tasks  (source: task_handoffs, {len(handoffs)} items, ~{hw_chars} chars)")
            for h in handoffs:
                print(f"## [{h.status}] {h.summary}")
                if h.next_steps:
                    print(f"  Next: {h.next_steps[0]}")
                if h.blockers:
                    print(f"  Blockers: {', '.join(h.blockers)}")
                if h.provenance:
                    prov = h.provenance
                    src = prov.get("session_id", prov.get("agent_type", "unknown"))
                    print(f"  📍 {src}")
            print()
        else:
            print("# Recent Tasks  (source: task_handoffs, empty)")
            print()

        # Load confirmed rules
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        if rules:
            rules_chars = sum(len(r.trigger or "") + len(r.pattern or "") for r in rules)
            print(f"# Confirmed Rules  (source: confirmed_rules, {len(rules)} rules, ~{rules_chars} chars)")
            for r in rules[:5]:
                trigger_preview = r.trigger[:60] + "..." if len(r.trigger) > 60 else r.trigger
                pattern_preview = r.pattern[:60] + "..." if len(r.pattern) > 60 else r.pattern
                print(f"- **{trigger_preview}**: {pattern_preview} [...truncated]")
                if r.provenance:
                    prov = r.provenance
                    src = prov.get("session_id", prov.get("agent_type", "unknown"))
                    print(f"  📍 {src}")
            print()
        else:
            print("# Confirmed Rules  (source: confirmed_rules, empty)")
            print()

        # Load recent memory entries
        entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
        if entries:
            entries_chars = sum(len(e.content or "") for e in entries)
            print(f"# Memory Entries  (source: structured_memory, {len(entries)} entries, ~{entries_chars} chars)")
            for e in entries:
                content_preview = e.content[:100] + "..." if len(e.content) > 100 else e.content
                print(f"- [{e.category}] {content_preview}")
                if e.provenance:
                    prov = e.provenance
                    src = prov.get("session_id", prov.get("agent_type", "unknown"))
                    print(f"  📍 {src}")
            print()
        else:
            print("# Memory Entries  (source: structured_memory, empty)")
            print()

        total_tokens, level = _wake_budget(profile, entries, rules, handoffs)
        print(f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]")
        if level in ("L3", "L4+"):
            from datetime import timezone
            three_months_ago = (datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)).strftime("%Y-%m-%d")
            print(f"⚠️  Memory budget at {level}")
            print(f"💡 Run: harness-mem purge --before {three_months_ago} --category all --dry-run")
            print("   to preview what can be archived.")
    finally:
        await backend.close()
    return 0


def _search_header(results: Sequence[object], requested_mode: str) -> str:
    if not results:
        return f"[{requested_mode.upper()} Search]"
    first = results[0]
    effective_mode = getattr(first, "_search_mode", requested_mode)
    fallback_reason = getattr(first, "_search_fallback_reason", None)
    if effective_mode == "hybrid":
        return "[Hybrid Search]"
    if fallback_reason:
        return f"[FTS Search] ({fallback_reason}, using full-text search)"
    return "[FTS Search]"


def _format_search_score(result: object) -> str:
    score = getattr(result, "_score", None)
    if score is None:
        score = getattr(result, "_hybrid_score", None)
    if score is None:
        score = getattr(result, "_fts_score", None)
    if isinstance(score, (int, float)):
        return f"{score:.3f}"
    return "n/a"


async def cmd_search(project_name: str | None, query: str, mode: str = "auto") -> int:
    """Search memory for a project."""
    project_name = _resolve_project_name(project_name, action_label="search")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        print(f"# Search: {query}")
        print()

        entries = await backend.structured_store.search_memory_entries(
            query,
            project_name,
            limit=10,
            mode=mode,
        )
        obs_list = await backend.verbatim_store.search(
            query,
            project_name=project_name,
            limit=10,
            mode=mode,
        )
        combined_results = entries or obs_list
        print(_search_header(combined_results, mode))
        print()

        if entries:
            print(f"## Memory Entries ({len(entries)} results)")
            for e in entries:
                preview = e.content[:150] + "..." if len(e.content) > 150 else e.content
                search_mode = getattr(e, "_search_mode", mode)
                print(f"- [{e.category}] {preview}  (score: {_format_search_score(e)}, mode: {search_mode})  -> structured")
            print()

        if obs_list:
            print(f"## Observations ({len(obs_list)} results)")
            for o in obs_list:
                preview = o.raw_content[:200].replace("\n", " ") + "..." if len(o.raw_content) > 200 else o.raw_content.replace("\n", " ")
                search_mode = getattr(o, "_search_mode", mode)
                print(f"- [{o.session_id}] {preview}  (score: {_format_search_score(o)}, mode: {search_mode})  -> verbatim")
            print()
    finally:
        await backend.close()
    return 0


async def cmd_timeline(project_name: str | None, limit: int = 50) -> int:
    """Show timeline of observations."""
    project_name = _resolve_project_name(project_name, action_label="timeline")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        obs_list = await backend.verbatim_store.timeline(project_name=project_name, limit=limit)
        print(f"# Timeline ({len(obs_list)} observations)")
        for o in obs_list:
            ts = o.timestamp.strftime("%Y-%m-%d %H:%M") if o.timestamp else "?"
            preview = o.raw_content[:100].replace("\n", " ")
            print(f"- {ts} [{o.session_id}] {preview}")
        print()
    finally:
        await backend.close()
    return 0


async def cmd_show(project_name: str | None, observation_id: str) -> int:
    """Show a specific observation."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        obs = await backend.verbatim_store.get(observation_id)
        if not obs:
            print(f"Observation not found: {observation_id}")
            return 1
        if project_name:
            resolved_project = _resolve_project_name(project_name, required=False, action_label="show")
            if resolved_project and obs.metadata.get("project_name") != resolved_project:
                print(f"Observation {observation_id} does not belong to project: {resolved_project}")
                return 1

        print(f"# Observation: {obs.id}")
        print(f"Session: {obs.session_id}")
        print(f"Client: {obs.client}")
        print(f"Type: {obs.content_type}")
        print(f"Timestamp: {obs.timestamp}")
        print(f"Tags: {', '.join(obs.tags)}")
        if obs.metadata.get("provenance"):
            print(f"Provenance: {obs.metadata['provenance']}")
        print()
        print(obs.raw_content)
    finally:
        await backend.close()
    return 0


async def cmd_distill(project_name: str | None, session_id: str | None = None, category: str | None = None) -> int:
    """Extract structured MemoryEntries from sessions using heuristic patterns."""
    project_name = _resolve_project_name(project_name, action_label="distill")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        adapter = ClaudeCodeAdapter(backend)

        if session_id:
            entries = await adapter.distill_session(session_id, project_name, category=category)
            if entries:
                print(f"Extracted {len(entries)} from {session_id}:")
                for e in entries:
                    source_label = _memory_entry_source_label(e)
                    print(f"  [{e.category}] {e.content[:100]}  (source: {source_label})")
                return 0
            else:
                if category:
                    print(f"No {category} entries found in session {session_id}")
                else:
                    print(f"No patterns found in session {session_id}")
                return 1
        else:
            sessions = adapter.list_project_sessions(project_name, min_size_kb=0, limit=100)
            if not sessions:
                print(f"No sessions found for project: {project_name}")
                return 1

            cat_suffix = f" ({category})" if category else ""
            print(f"Distilling {len(sessions)} sessions for {project_name}{cat_suffix}...")
            total = 0
            for sess in sessions:
                entries = await adapter.distill_session(sess["session_id"], project_name, category=category)
                for e in entries:
                    source_label = _memory_entry_source_label(e)
                    print(f"  [{e.category}] {e.content[:100]}  (source: {source_label})")
                    total += 1
            if total == 0 and category:
                print(f"No {category} entries found across {len(sessions)} sessions")
                return 1
            print(f"Extracted {total} memory entries from {len(sessions)} sessions")
            return 0
    finally:
        await backend.close()


async def cmd_ingest(client: str, project_name: str | None = None, limit: int = 10, full_rescan: bool = False) -> int:
    """Ingest sessions for a supported client."""
    project_name = _resolve_project_name(project_name, action_label=f"{client} ingest")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)

        if client == "claude-code":
            adapter = ClaudeCodeAdapter(backend)
            profile = await profile_store.get(project_name)
            all_sessions = adapter.list_project_sessions(project_name, min_size_kb=0)
            last_session_id = profile.last_ingest_session_id if profile and not full_rescan else None
            last_ingest_at = profile.last_ingest_at if profile and not full_rescan else None

            candidate_sessions: list[dict]
            if full_rescan:
                print(f"Ingesting {client} sessions for project: {project_name}")
                print("[Full Rescan] Processing all sessions without cursor shortcuts.")
                candidate_sessions = all_sessions[:limit]
            else:
                print(f"Ingesting {client} sessions for project: {project_name}")
                if last_session_id:
                    candidate_sessions = []
                    cursor_found = False
                    for session in all_sessions:
                        if session["session_id"] == last_session_id:
                            cursor_found = True
                            break
                        candidate_sessions.append(session)
                    if cursor_found:
                        print(f"[Incremental] Processing sessions newer than cursor: {last_session_id}")
                    else:
                        print(
                            f"Warning: ingest cursor {last_session_id} not found; "
                            "falling back to sessions newer than last ingest timestamp."
                        )
                        if last_ingest_at is not None:
                            candidate_sessions = [
                                session for session in all_sessions
                                if session.get("mtime") and session["mtime"] > last_ingest_at
                            ]
                        else:
                            candidate_sessions = all_sessions[:limit]
                    candidate_sessions = candidate_sessions[:limit]
                else:
                    candidate_sessions = all_sessions[:limit]

            existing_observations = await backend.verbatim_store.list(limit=100000)
            existing_session_ids = {
                observation.session_id
                for observation in existing_observations
                if observation.metadata.get("project_name") == project_name
            }

            ingested = 0
            errors = 0
            skipped_existing = 0

            for session in candidate_sessions:
                try:
                    if session["session_id"] in existing_session_ids:
                        skipped_existing += 1
                        continue
                    obs = adapter.turns_to_observation(session["path"], session["session_id"], project_name)
                    await backend.verbatim_store.save(obs)
                    ingested += 1
                    existing_session_ids.add(session["session_id"])
                except Exception:
                    errors += 1

            newest_seen_session_id = last_session_id
            if all_sessions:
                newest_seen_session_id = all_sessions[0]["session_id"]

            print(f"Sessions found: {len(all_sessions)}")
            print(f"Ingested: {ingested} sessions")
            if skipped_existing > 0:
                print(f"Skipped existing: {skipped_existing} sessions")
            if errors > 0:
                print(f"Errors: {errors}")

            # Update profile with new ingest cursor
            if profile is None:
                profile = ProjectProfile(project_name=project_name)
            if newest_seen_session_id is not None:
                profile.last_ingest_session_id = newest_seen_session_id
            if candidate_sessions or full_rescan:
                profile.last_ingest_at = datetime.now(timezone.utc)
            await profile_store.save(profile)

            # Auto-detect project profile if stacks are empty
            if not profile.stacks:
                sessions_dir = Path.home() / ".claude" / "projects"
                project_path = sessions_dir / project_name
                if project_path.exists():
                    detected = build_project_profile(project_path, project_name)
                    profile.stacks = detected.stacks
                    profile.key_files = detected.key_files
                    await profile_store.save(profile)
                    print(f"Auto-detected profile: {', '.join(profile.stacks)}")

            _set_active_project(project_name)
            return 0

        codex_adapter = CodexAdapter(backend)
        print(f"Ingesting {client} sessions for project: {project_name}")
        result = await codex_adapter.ingest(project_name=project_name, limit=limit, min_size_kb=0)
        if result["sessions_found"] == 0:
            print(f"No {client} sessions found.")
            return 1

        print(f"Sessions found: {result['sessions_found']}")
        print(f"Ingested: {result['ingested']} sessions")
        if result["errors"] > 0:
            print(f"Errors: {result['errors']}")
        _set_active_project(project_name)
    finally:
        await backend.close()
    return 0


async def cmd_profile(project_name: str | None) -> int:
    """Show project profile."""
    project_name = _resolve_project_name(project_name, action_label="profile")
    if not project_name:
        return 1
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    profile = await profile_store.get(project_name)
    if not profile:
        await backend.close()
        print(f"No profile found for: {project_name}")
        return 1

    # Collect memory stats — must match actual wake-up load (cmd_wake_up)
    # wake-up loads: profile + latest 3 handoffs + all rules + latest 5 memory entries
    # actual wake-up limit for entries is 5
    entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    # actual wake-up limit for handoffs is 3
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
    await backend.close()

    entry_chars = sum(len(e.content) for e in entries)
    rule_chars = sum(len(r.pattern) + len(r.trigger) for r in rules)
    handoff_chars = sum(
        len(h.summary) + sum(len(n) for n in h.next_steps)
        for h in handoffs
    )

    profile_tokens = _chars_to_tokens(len(_profile_text(profile)))
    entry_tokens = _chars_to_tokens(entry_chars)
    rule_tokens = _chars_to_tokens(rule_chars)
    handoff_tokens = _chars_to_tokens(handoff_chars)
    total_tokens = profile_tokens + entry_tokens + rule_tokens + handoff_tokens
    level = _disclosure_level(total_tokens)

    print(f"Project: {profile.project_name}")
    print(f"Description: {profile.description}")
    print(f"Stacks: {', '.join(profile.stacks) if profile.stacks else '(none detected)'}")
    print(f"Key files ({len(profile.key_files)}):")
    for f in profile.key_files[:10]:
        print(f"  - {f}")
    if len(profile.key_files) > 10:
        print(f"  ... and {len(profile.key_files) - 10} more")
    print(f"Conventions ({len(profile.conventions)}):")
    for convention in profile.conventions[:10]:
        print(f"  - {convention}")
    if len(profile.conventions) > 10:
        print(f"  ... and {len(profile.conventions) - 10} more")
    print()
    print("Memory budget estimate (actual wake-up load):")
    print(f"  Profile: ≈ {profile_tokens:,} tokens")
    print(f"  Memory entries: {len(entries)} (≈ {entry_tokens:,} tokens, limited to 5 latest)")
    print(f"  Confirmed rules: {len(rules)} (≈ {rule_tokens:,} tokens)")
    print(f"  Task handoffs: {len(handoffs)} (≈ {handoff_tokens:,} tokens, limited to 3 latest)")
    print(f"  Total wake-up: ≈ {total_tokens:,} tokens [{level}]")

    return 0


async def cmd_profile_edit(project_name: str | None) -> int:
    """Edit project profile fields interactively (merge strategy)."""
    project_name = _resolve_project_name(project_name, action_label="profile --edit")
    if not project_name:
        return 1

    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    profile = await profile_store.get(project_name)

    if profile:
        print(f"Editing profile: {project_name}")
        print("(Press Enter to keep the current value; '!clear' to reset a field)\n")
    else:
        if not _can_prompt():
            print(f"No profile found for: {project_name}. Run `harness-mem profile` first.")
            return 1
        print(f"No profile found for: {project_name}. Creating a new one.\n")
        profile = None

    # Editable fields: description, stacks, key_files, conventions
    if profile:
        new_description = _prompt_text(
            "description",
            default=profile.description or None,
            allow_empty=True,
            allow_clear=True,
        )
        new_stacks_raw = _prompt_list_labeled(
            "stacks",
            "programming languages & frameworks",
            existing=profile.stacks,
        )
        new_key_files_raw = _prompt_list_labeled(
            "key_files",
            "important files",
            existing=profile.key_files,
        )
        new_conventions_raw = _prompt_list_labeled(
            "conventions",
            "coding conventions",
            existing=profile.conventions,
        )
    else:
        new_description = _prompt_text("description", allow_empty=True)
        new_stacks_raw = _prompt_list("stacks (one per line, blank to finish)")
        new_key_files_raw = _prompt_list("key files (one per line, blank to finish)")
        new_conventions_raw = _prompt_list("conventions (one per line, blank to finish)")

    from datetime import timezone

    if profile:
        # Merge: update only the fields the user edited
        updated = ProjectProfile(
            id=profile.id,
            project_name=project_name,
            description=new_description if new_description is not None else profile.description,
            stacks=new_stacks_raw if new_stacks_raw is not None else profile.stacks,
            key_files=new_key_files_raw if new_key_files_raw is not None else profile.key_files,
            conventions=new_conventions_raw if new_conventions_raw is not None else profile.conventions,
            service_hints=profile.service_hints,
            database_hints=profile.database_hints,
            created_at=profile.created_at,
            last_updated=datetime.now(timezone.utc),
        )
    else:
        updated = ProjectProfile(
            project_name=project_name,
            description=new_description or "",
            stacks=new_stacks_raw or [],
            key_files=new_key_files_raw or [],
            conventions=new_conventions_raw or [],
            service_hints=[],
            database_hints=[],
            last_updated=datetime.now(timezone.utc),
        )

    await profile_store.save(updated)
    print(f"\nProfile saved for: {project_name}")
    return 0


async def cmd_purge(before_date: str, category: str, dry_run: bool) -> int:
    """Soft-delete observations/structured memory before a given date."""
    try:
        cutoff = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Invalid date format: {before_date}. Use YYYY-MM-DD.")
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        total_deleted = 0

        if category in ("observations", "all"):
            all_obs = await backend.verbatim_store.list(limit=100000)
            to_delete = [o for o in all_obs if o.timestamp and _as_utc(o.timestamp) < cutoff]
            if to_delete:
                if dry_run:
                    print(f"[DRY RUN] Would soft-delete {len(to_delete)} observations before {before_date}")
                    for o in to_delete[:10]:
                        ts = o.timestamp.strftime("%Y-%m-%d") if o.timestamp else "?"
                        preview = o.raw_content[:80].replace("\n", " ")
                        print(f"  - {o.id} [{ts}] {preview}...")
                    if len(to_delete) > 10:
                        print(f"  ... and {len(to_delete) - 10} more")
                else:
                    for o in to_delete:
                        await backend.verbatim_store.soft_delete(o.id)
                    total_deleted += len(to_delete)
                    print(f"Soft-deleted {len(to_delete)} observations.")

        if category in ("structured", "all"):
            project_name = _get_active_project()
            if project_name:
                entries = await backend.structured_store.list_memory_entries(project_name, limit=100000)
                entries_to_delete = [e for e in entries if e.created_at and _as_utc(e.created_at) < cutoff]
                if entries_to_delete:
                    if dry_run:
                        print(f"[DRY RUN] Would soft-delete {len(entries_to_delete)} structured memories before {before_date}")
                        for e in entries_to_delete[:10]:
                            preview = e.content[:80].replace("\n", " ")
                            print(f"  - {e.id} [{e.category}] {preview}...")
                        if len(entries_to_delete) > 10:
                            print(f"  ... and {len(entries_to_delete) - 10} more")
                    else:
                        for e in entries_to_delete:
                            await backend.structured_store.soft_delete_memory_entry(e.id)
                        total_deleted += len(entries_to_delete)
                        print(f"Soft-deleted {len(entries_to_delete)} structured memories.")

        if total_deleted == 0 and not (category in ("observations", "all") or category in ("structured", "all")):
            print("Nothing to purge. Try --category observations, --category structured, or --category all.")
        elif total_deleted == 0:
            print(f"No entries found before {before_date} in category '{category}'.")

        if not dry_run and total_deleted > 0:
            print("Run 'harness-mem doctor' to check new memory budget.")
        return 0
    finally:
        await backend.close()


def _prompt_list_labeled(field_label: str, item_description: str, existing: list[str] | None = None) -> list[str] | None:
    """Prompt for a list of strings, showing existing items.

    - For existing profile edit: blank returns None (keep existing), '!clear' resets to [].
    - For new profile creation: pass existing=[] so blank returns [].
    """
    if not _can_prompt():
        return None
    has_existing = existing is not None and len(existing) > 0
    if has_existing:
        print(f"{field_label} (current: {', '.join(existing or [])}):")
        print(f"  (Enter new {item_description}, blank to keep existing, '!clear' to reset)")
    else:
        print(f"{field_label} (one per line, blank to finish):")
    values: list[str] = []
    while True:
        value = input("> ").strip()
        if not value:
            if has_existing:
                return None  # keep existing
            return values  # return what was entered so far for new profile
        if value == "!clear":
            return []
        values.append(value)

    sys.exit(main())
