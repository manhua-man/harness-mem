"""Status command implementation."""

from __future__ import annotations

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    get_active_project,
    log_next_step_shown,
    resolve_project_name,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def cmd_status(project_name: str | None = None) -> int:
    """Show backend status, optionally scoped to a project."""
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        resolved_project = resolve_project_name(project_name, required=False, action_label="status")
        if resolved_project:
            await _status_project_async(backend, resolved_project)
        else:
            print("harness-mem is ready")
            print(f"Data directory: {DEFAULT_DATA_DIR}")
            active_project = get_active_project()
            if active_project:
                print(f"Active project: {active_project}")
                await _status_project_async(backend, active_project)
            else:
                print()
                print("📍 Phase: Not Initialized")
                print("→ Next: harness-mem quickstart")
                print("   Why: No active project set, run quickstart to get started")
                log_next_step_shown(None, "status", "harness-mem quickstart")
    finally:
        await backend.close()
    return 0


async def _status_project_async(backend: LocalMemoryBackend, project_name: str) -> None:
    """Show status for a specific project."""
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    all_obs = await backend.verbatim_store.list(limit=10000)
    project_obs = [
        observation
        for observation in all_obs
        if observation.metadata.get("project_name") == project_name
        or project_name in (getattr(observation, "session_id", "") or "")
    ]
    entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    profile = await profile_store.get(project_name)

    print(f"Project: {project_name}")
    print(f"  Observations: {len(project_obs)}")
    print(f"  Memory entries: {len(entries)} (limited to 5 latest in wake-up)")
    print(f"  Task handoffs: {len(handoffs)} (limited to 3 latest in wake-up)")
    print(f"  Confirmed rules: {len(rules)}")

    profile_text = ""
    if profile:
        profile_text = (profile.description or "") + " " + " ".join(profile.stacks) + " " + " ".join(profile.key_files)
    entry_chars = sum(len(entry.content) for entry in entries)
    rule_chars = sum(len(rule.pattern) + len(rule.trigger) for rule in rules)
    handoff_chars = sum(len(handoff.summary) + sum(len(step) for step in handoff.next_steps) for handoff in handoffs)
    total_tokens = round(len(profile_text) / 4) + round(entry_chars / 4) + round(rule_chars / 4) + round(handoff_chars / 4)
    level = _disclosure_level(total_tokens)
    print(f"  Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")

    if level in ("L3", "L4+"):
        purge_command = _suggested_purge_command(project_name)
        print()
        print(f"📍 Phase: Budget Warning ({level})")
        print(f"→ Next: {purge_command}")
        print(f"   Why: Memory budget at {level}, archiving old data can help")
        log_next_step_shown(project_name, "status", purge_command)
    elif len(project_obs) == 0:
        print()
        print("📍 Phase: Empty")
        print("→ Next: harness-mem ingest claude-code")
        print("   Why: No observations yet, ingest sessions to get started")
        log_next_step_shown(project_name, "status", "harness-mem ingest claude-code")
    else:
        print()
        print("📍 Phase: Healthy")
        print("→ Next: harness-mem wake")
        print("   Why: Memory is ready, wake-up is the shortest path to project context")
        log_next_step_shown(project_name, "status", "harness-mem wake")


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
