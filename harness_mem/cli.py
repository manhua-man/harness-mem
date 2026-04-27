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
from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.commands import (
    cmd_doctor,
    cmd_ingest,
    cmd_quickstart,
    cmd_search,
    cmd_show,
    cmd_status,
    cmd_timeline,
    cmd_wake_up,
)
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.claude_code.project_profile_detector import build_project_profile
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.cli_commands import (
    cmd_correct,
    cmd_confirm_rule,
    cmd_reject_rule,
    cmd_list_candidates,
    cmd_confirmed_rules,
    cmd_handoff,
)


DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"

_ADOPTED_NEXT_STEP_COMMANDS = {
    "ingest",
    "distill",
    "wake-up",
    "search",
    "purge",
    "correct",
    "handoff",
}


def _log_cli_event(
    event_type: EventType,
    *,
    project_name: str | None = None,
    command: str | None = None,
    next_step: str | None = None,
    session_id: str | None = None,
    extra: dict | None = None,
) -> None:
    """Best-effort local event logging. Never fail the command path."""
    try:
        get_event_logger(DEFAULT_DATA_DIR).log_sync(
            event_type,
            project_name=project_name,
            command=command,
            next_step=next_step,
            session_id=session_id,
            extra=extra,
        )
    except Exception:
        pass


def _log_command_invoked(
    command: str,
    *,
    project_name: str | None = None,
    session_id: str | None = None,
    extra: dict | None = None,
) -> None:
    _log_cli_event(
        EventType.COMMAND_INVOKED,
        project_name=project_name,
        command=command,
        session_id=session_id,
        extra=extra,
    )
    if command in _ADOPTED_NEXT_STEP_COMMANDS:
        _log_cli_event(
            EventType.NEXT_STEP_ADOPTED,
            project_name=project_name,
            command=command,
            next_step=f"harness-mem {command}",
            session_id=session_id,
            extra=extra,
        )


def _log_next_step_shown(project_name: str | None, source_command: str, next_step: str) -> None:
    _log_cli_event(
        EventType.NEXT_STEP_SHOWN,
        project_name=project_name,
        command=source_command,
        next_step=next_step,
    )


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
        repo_root.parent / "tests" / "fixtures" / project_name,
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
    adapter = AdapterRegistry.build("claude-code", None)
    return adapter.list_sessions(project_name, min_size_kb=0, limit=limit)


def _recent_codex_sessions(limit: int | None = 3) -> list[dict]:
    adapter = AdapterRegistry.build("codex", None)
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


def _suggested_purge_command(project_name: str | None) -> str:
    project_flag = f" -p {project_name}" if project_name else ""
    return f"harness-mem purge{project_flag} --before <DATE> --category all --dry-run"


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
    show.add_argument("observation_id_arg", nargs="?", help="Observation ID or session ID")
    show.add_argument("-p", "--project", help="Project name (optional)")
    show.add_argument("-i", "--id", dest="observation_id", help="Observation ID or session ID (legacy, use -o instead)")
    show.add_argument("-o", "--observation-id", dest="observation_id", help="Observation ID or session ID")

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
    purge_cmd.add_argument("-p", "--project", help="Project name (defaults to active project for structured/all)")
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
            parser.error("show requires an observation or session id. Use `harness-mem show <id>` or `--observation-id`.")
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
        result = asyncio.run(cmd_correct(session_id, project_name, pattern, trigger))
        if result == 0:
            _log_command_invoked("correct", project_name=project_name, session_id=session_id)
            _log_cli_event(
                EventType.LEARNING_LOOP_COMPLETE,
                project_name=project_name,
                command="correct",
                session_id=session_id,
                extra={"stage": "candidate_created"},
            )
        return result

    if command == "confirm-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("confirm-rule requires a rule id. Use `harness-mem confirm-rule <id>` or `--rule-id`.")
        result = asyncio.run(cmd_confirm_rule(rule_id))
        if result == 0:
            active_project = _get_active_project()
            _log_command_invoked("confirm", project_name=active_project)
            _log_cli_event(EventType.RULE_CONFIRMED, project_name=active_project, command="confirm", extra={"rule_id": rule_id})
            _log_cli_event(
                EventType.LEARNING_LOOP_COMPLETE,
                project_name=active_project,
                command="confirm",
                extra={"stage": "rule_confirmed", "rule_id": rule_id},
            )
        return result

    if command == "reject-rule":
        rule_id = args.rule_id or args.rule_id_arg
        if not rule_id:
            parser.error("reject-rule requires a rule id. Use `harness-mem reject-rule <id>` or `--rule-id`.")
        result = asyncio.run(cmd_reject_rule(rule_id))
        if result == 0:
            active_project = _get_active_project()
            _log_command_invoked("reject", project_name=active_project)
            _log_cli_event(EventType.RULE_REJECTED, project_name=active_project, command="reject", extra={"rule_id": rule_id})
        return result

    if command == "purge":
        return asyncio.run(cmd_purge(args.before, args.category, args.dry_run, args.project))

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
        result = asyncio.run(cmd_handoff(
            project_name, task_id, summary,
            status=status, next_steps=next_steps, blockers=blockers
        ))
        if result == 0:
            _log_command_invoked("handoff", project_name=project_name, extra={"task_id": task_id, "status": status})
        return result

    if command == "api":
        import uvicorn
        from harness_mem.api.server import create_app
        app = create_app()
        print(f"Starting API server on {args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)
        return 0

    return 0


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
                _log_command_invoked(
                    "distill",
                    project_name=project_name,
                    session_id=session_id,
                    extra={"category": category, "memory_entries": len(entries)},
                )
                _log_cli_event(
                    EventType.MEMORY_DISTILLED,
                    project_name=project_name,
                    command="distill",
                    session_id=session_id,
                    extra={"category": category, "memory_entries": len(entries)},
                )
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
            _log_command_invoked(
                "distill",
                project_name=project_name,
                extra={"category": category, "memory_entries": total, "sessions": len(sessions)},
            )
            _log_cli_event(
                EventType.MEMORY_DISTILLED,
                project_name=project_name,
                command="distill",
                extra={"category": category, "memory_entries": total, "sessions": len(sessions)},
            )
            return 0
    finally:
        await backend.close()


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


async def cmd_purge(
    before_date: str,
    category: str,
    dry_run: bool,
    project_name: str | None = None,
) -> int:
    """Soft-delete observations/structured memory before a given date."""
    try:
        cutoff = datetime.strptime(before_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        print(f"Invalid date format: {before_date}. Use YYYY-MM-DD.")
        return 1

    resolved_project = _resolve_project_name(
        project_name,
        required=category == "structured" or category == "all",
        action_label="purge",
    )
    if category in ("structured", "all") and not resolved_project:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        total_deleted = 0
        observations_deleted = 0
        structured_deleted = 0

        if category in ("observations", "all"):
            all_obs = await backend.verbatim_store.list(limit=100000)
            to_delete = [
                o
                for o in all_obs
                if o.timestamp
                and _as_utc(o.timestamp) < cutoff
                and (resolved_project is None or o.metadata.get("project_name") == resolved_project)
            ]
            if to_delete:
                if dry_run:
                    target_scope = f" for project '{resolved_project}'" if resolved_project else ""
                    print(f"[DRY RUN] Would soft-delete {len(to_delete)} observations before {before_date}{target_scope}")
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
                    observations_deleted = len(to_delete)
                    print(f"Soft-deleted {len(to_delete)} observations.")

        if category in ("structured", "all"):
            assert resolved_project is not None
            entries = await backend.structured_store.list_memory_entries(resolved_project, limit=100000)
            entries_to_delete = [e for e in entries if e.created_at and _as_utc(e.created_at) < cutoff]
            if entries_to_delete:
                if dry_run:
                    print(
                        f"[DRY RUN] Would soft-delete {len(entries_to_delete)} structured memories before {before_date} "
                        f"for project '{resolved_project}'"
                    )
                    for e in entries_to_delete[:10]:
                        preview = e.content[:80].replace("\n", " ")
                        print(f"  - {e.id} [{e.category}] {preview}...")
                    if len(entries_to_delete) > 10:
                        print(f"  ... and {len(entries_to_delete) - 10} more")
                else:
                    for e in entries_to_delete:
                        await backend.structured_store.soft_delete_memory_entry(e.id)
                    total_deleted += len(entries_to_delete)
                    structured_deleted = len(entries_to_delete)
                    print(f"Soft-deleted {len(entries_to_delete)} structured memories.")

        if total_deleted == 0 and not (category in ("observations", "all") or category in ("structured", "all")):
            print("Nothing to purge. Try --category observations, --category structured, or --category all.")
        elif total_deleted == 0:
            print(f"No entries found before {before_date} in category '{category}'.")

        if not dry_run and total_deleted > 0:
            print("Run 'harness-mem doctor' to check new memory budget.")
            _log_command_invoked(
                "purge",
                project_name=resolved_project,
                extra={
                    "category": category,
                    "before_date": before_date,
                    "observations_deleted": observations_deleted,
                    "structured_deleted": structured_deleted,
                },
            )
        elif dry_run:
            _log_command_invoked(
                "purge",
                project_name=resolved_project,
                extra={"category": category, "before_date": before_date, "dry_run": True},
            )
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

if __name__ == "__main__":
    sys.exit(main())
