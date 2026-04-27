"""Doctor command implementation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem import __version__
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    claude_session_count,
    codex_scope_note,
    codex_session_count,
    get_active_project,
    log_next_step_shown,
    print_recent_sessions,
    project_state,
    recent_claude_sessions,
    recent_codex_sessions,
    resolve_project_name,
    suggested_next_step,
    wake_budget,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def cmd_doctor(project_name: str | None = None) -> int:
    """Inspect local setup and print actionable next steps."""
    resolved_project = resolve_project_name(project_name, required=False, action_label="doctor")
    initialized = DEFAULT_DATA_DIR.exists()
    active_project = get_active_project()

    print(f"harness-mem {__version__}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")
    print(f"Initialized: {'yes' if initialized else 'no'}")
    print(f"Active project: {active_project or '(none)'}")

    if not initialized:
        print("Suggested fix: run `harness-mem quickstart`.")
        return 1

    if resolved_project:
        claude_sessions = recent_claude_sessions(resolved_project, limit=3)
        codex_sessions = recent_codex_sessions(limit=3)
        print(f"Doctor project: {resolved_project}")
        print(f"Claude Code sessions: {claude_session_count(resolved_project)}")
        print(f"Codex sessions (global): {codex_session_count()}")
        print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
        print_recent_sessions("Recent Codex sessions (global):", codex_sessions)
        if codex_sessions:
            print(f"Note: {codex_scope_note()}")

        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
        profile = await profile_store.get(resolved_project)
        print(f"Profile saved: {'yes' if profile else 'no'}")
        if profile and profile.stacks:
            print(f"Stacks detected: {', '.join(profile.stacks)}")

        backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        await backend.init()
        try:
            state = await project_state(resolved_project)
            print(f"Observations: {state['observations']}")
            print(f"Memory entries: {state['memory_entries']}")
            print(f"Task handoffs: {state['task_handoffs']}")
            print(f"Confirmed rules: {state['confirmed_rules']}")

            entries = await backend.structured_store.list_memory_entries(resolved_project, limit=5)
            handoffs = await backend.structured_store.get_latest_handoffs(resolved_project, limit=3)
            rules = await backend.structured_store.list_confirmed_rules(resolved_project)
            total_tokens, level = wake_budget(profile, entries, rules, handoffs)
            print(f"Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")
            if level in ("L3", "L4+"):
                three_months_ago = (
                    datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
                ).strftime("%Y-%m-%d")
                purge_command = (
                    f"harness-mem purge -p {resolved_project} --before {three_months_ago} "
                    "--category all --dry-run"
                )
                print(f"💡 Run: {purge_command}")
                print("   to preview what can be archived.")

            next_command, reason = suggested_next_step(
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
            log_next_step_shown(resolved_project, "doctor", next_command)
        finally:
            await backend.close()
        return 0

    print()
    print("📍 Phase: Not Initialized")
    print("→ Next: harness-mem quickstart")
    print("   Why: No active project set or data directory not initialized")
    log_next_step_shown(None, "doctor", "harness-mem quickstart")
    return 0
