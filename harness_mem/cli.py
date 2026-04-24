"""CLI entry point for harness-mem."""

from __future__ import annotations
import argparse
import asyncio
import os
import sys
from datetime import datetime
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


def _prompt_text(label: str, default: str | None = None, *, allow_empty: bool = False) -> str | None:
    if not _can_prompt():
        return default if allow_empty else None

    while True:
        suffix = f" [{default}]" if default else ""
        value = input(f"{label}{suffix}: ").strip()
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
    adapter = ClaudeCodeAdapter(None)
    return adapter.list_project_sessions(project_name, min_size_kb=0, limit=limit)


def _recent_codex_sessions(limit: int | None = 3) -> list[dict]:
    adapter = CodexAdapter(None)
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
    return description + " " + " ".join(stacks) + " " + " ".join(key_files)


def _chars_to_tokens(chars: int) -> int:
    return round(chars / 4)


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

    # timeline
    timeline = sub.add_parser("timeline", aliases=["tl"], help="Show observation timeline")
    timeline.set_defaults(command_name="timeline")
    timeline.add_argument("limit_arg", nargs="?", type=int, help="Max results")
    timeline.add_argument("-p", "--project", help="Project name (defaults to active project)")
    timeline.add_argument("-n", "--limit", type=int, help="Max results")

    # show
    show = sub.add_parser("show", help="Show a specific observation")
    show.set_defaults(command_name="show")
    show.add_argument("observation_id_arg", nargs="?", help="Observation ID")
    show.add_argument("-p", "--project", help="Project name (optional)")
    show.add_argument("-i", "--id", dest="observation_id", help="Observation ID")

    # status
    status = sub.add_parser("status", aliases=["st"], help="Show memory status")
    status.set_defaults(command_name="status")
    status.add_argument("-p", "--project", help="Project name (defaults to active project)")

    # profile
    profile_cmd = sub.add_parser("profile", help="Show project profile")
    profile_cmd.set_defaults(command_name="profile")
    profile_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")

    # distill
    distill_cmd = sub.add_parser("distill", aliases=["ds"], help="Extract structured memory from sessions")
    distill_cmd.set_defaults(command_name="distill")
    distill_cmd.add_argument("session_id_arg", nargs="?", help="Session ID (optional)")
    distill_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    distill_cmd.add_argument("-s", "--session-id", dest="session_id", help="Session ID (optional; distill all if omitted)")
    distill_cmd.add_argument("-c", "--category", dest="category", choices=["architecture", "convention", "api", "bug", "decision"], help="Filter entries by category")

    # correct
    correct_cmd = sub.add_parser("correct", help="Create a rule candidate from a correction")
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
    handoff_cmd = sub.add_parser("handoff", help="Create or update a task handoff")
    handoff_cmd.set_defaults(command_name="handoff")
    handoff_cmd.add_argument("-p", "--project", help="Project name (defaults to active project)")
    handoff_cmd.add_argument("-t", "--task-id", dest="task_id", help="Task ID")
    handoff_cmd.add_argument("-s", "--summary", help="Task summary")
    handoff_cmd.add_argument("--status", default="in_progress", help="Task status")
    handoff_cmd.add_argument("-n", "--next-step", dest="next_steps", action="append", default=[], help="Next step (can repeat)")
    handoff_cmd.add_argument("-b", "--blocker", dest="blockers", action="append", default=[], help="Blocker (can repeat)")

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
            parser.error("search requires a query. Use `harness-mem search <query>` or `--query`.")
        return asyncio.run(cmd_search(args.project, query))

    if command == "timeline":
        limit = args.limit if args.limit is not None else (args.limit_arg or 50)
        return asyncio.run(cmd_timeline(args.project, limit))

    if command == "show":
        observation_id = args.observation_id or args.observation_id_arg
        if not observation_id:
            parser.error("show requires an observation id. Use `harness-mem show <id>` or `--id`.")
        return asyncio.run(cmd_show(args.project, observation_id))

    if command == "ingest":
        return asyncio.run(cmd_ingest(args.client, args.project, args.limit))

    if command == "profile":
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
    print("Suggested next step:")
    print(f"  {next_command}")
    print(f"Reason: {reason}")
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
                print("Budget warning: wake-up context is high; consider distilling or pruning stale memory before wake-up.")

            next_command, reason = _suggested_next_step(
                project_name=resolved_project,
                observation_count=state["observations"],
                memory_entry_count=state["memory_entries"],
                claude_sessions=claude_sessions,
                codex_sessions=codex_sessions,
            )

            print("Suggested next step:")
            print(f"  {next_command}")
            print(f"Reason: {reason}")
        finally:
            await backend.close()
        return 0

    print("Suggested next step: run `harness-mem use <project-name>` or `harness-mem quickstart`.")
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

        total_tokens, level = _wake_budget(profile, entries, rules, handoffs)
        print(f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]")
    finally:
        await backend.close()
    return 0


async def cmd_search(project_name: str | None, query: str) -> int:
    """Search memory for a project."""
    project_name = _resolve_project_name(project_name, action_label="search")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        print(f"# Search: {query}")
        print()

        entries = await backend.structured_store.search_memory_entries(query, project_name, limit=10)
        if entries:
            print(f"## Memory Entries ({len(entries)} results)")
            for e in entries:
                print(f"- [{e.category}] {e.content[:150]}  -> structured")
            print()

        obs_list = await backend.verbatim_store.search(query, project_name=project_name, limit=10)
        if obs_list:
            print(f"## Observations ({len(obs_list)} results)")
            for o in obs_list:
                preview = o.raw_content[:200].replace("\n", " ")
                print(f"- [{o.session_id}] {preview}  -> verbatim")
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


async def cmd_ingest(client: str, project_name: str | None = None, limit: int = 10) -> int:
    """Ingest sessions for a supported client."""
    project_name = _resolve_project_name(project_name, action_label=f"{client} ingest")
    if not project_name:
        return 1
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        if client == "claude-code":
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
            _set_active_project(project_name)
            return 0

        adapter = CodexAdapter(backend)
        print(f"Ingesting {client} sessions for project: {project_name}")
        result = await adapter.ingest(project_name=project_name, limit=limit, min_size_kb=0)
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
    all_obs = await backend.verbatim_store.list(limit=10000)
    project_obs = [o for o in all_obs if o.metadata.get("project_name") == project_name]
    # actual wake-up limit for entries is 5
    entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    # actual wake-up limit for handoffs is 3
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
    await backend.close()

    # Profile text (description + stacks + key files)
    profile_text = (
        (profile.description or "")
        + " " + " ".join(profile.stacks)
        + " " + " ".join(profile.key_files)
    )
    entry_chars = sum(len(e.content) for e in entries)
    rule_chars = sum(len(r.pattern) + len(r.trigger) for r in rules)
    handoff_chars = sum(
        len(h.summary) + sum(len(n) for n in h.next_steps)
        for h in handoffs
    )

    def chars_to_tokens(chars: int) -> int:
        return round(chars / 4)

    profile_tokens = chars_to_tokens(len(profile_text))
    entry_tokens = chars_to_tokens(entry_chars)
    rule_tokens = chars_to_tokens(rule_chars)
    handoff_tokens = chars_to_tokens(handoff_chars)
    total_tokens = profile_tokens + entry_tokens + rule_tokens + handoff_tokens

    def disclosure_level(tokens: int) -> str:
        if tokens < 500:
            return "L0"
        elif tokens < 2000:
            return "L1"
        elif tokens < 8000:
            return "L2"
        elif tokens < 32000:
            return "L3"
        else:
            return "L4+"

    level = disclosure_level(total_tokens)

    print(f"Project: {profile.project_name}")
    print(f"Description: {profile.description}")
    print(f"Stacks: {', '.join(profile.stacks) if profile.stacks else '(none detected)'}")
    print(f"Key files ({len(profile.key_files)}):")
    for f in profile.key_files[:10]:
        print(f"  - {f}")
    if len(profile.key_files) > 10:
        print(f"  ... and {len(profile.key_files) - 10} more")
    print()
    print(f"Memory budget estimate (actual wake-up load):")
    print(f"  Profile: ≈ {profile_tokens:,} tokens")
    print(f"  Memory entries: {len(entries)} (≈ {entry_tokens:,} tokens, limited to 5 latest)")
    print(f"  Confirmed rules: {len(rules)} (≈ {rule_tokens:,} tokens)")
    print(f"  Task handoffs: {len(handoffs)} (≈ {handoff_tokens:,} tokens, limited to 3 latest)")
    print(f"  Total wake-up: ≈ {total_tokens:,} tokens [{level}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
