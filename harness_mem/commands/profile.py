"""Use/profile command implementations."""

from __future__ import annotations

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    chars_to_tokens,
    disclosure_level,
    get_active_project,
    profile_text,
    resolve_project_name,
    set_active_project,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


def cmd_use(project_name: str | None = None) -> int:
    """Set or show the active project."""
    if not project_name:
        current = get_active_project()
        if current:
            print(f"Active project: {current}")
            return 0
        print("No active project set. Run: harness-mem use <project-name>")
        return 1

    set_active_project(project_name)
    print(f"Active project set to: {project_name}")
    return 0


async def cmd_profile(project_name: str | None) -> int:
    """Show project profile."""
    project_name = resolve_project_name(project_name, action_label="profile")
    if not project_name:
        return 1

    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        profile = await profile_store.get(project_name)
        if not profile:
            print(f"No profile found for: {project_name}")
            return 1

        entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
    finally:
        await backend.close()

    entry_chars = sum(len(entry.content) for entry in entries)
    rule_chars = sum(len(rule.pattern) + len(rule.trigger) for rule in rules)
    handoff_chars = sum(
        len(handoff.summary) + sum(len(step) for step in handoff.next_steps)
        for handoff in handoffs
    )

    profile_tokens = chars_to_tokens(len(profile_text(profile)))
    entry_tokens = chars_to_tokens(entry_chars)
    rule_tokens = chars_to_tokens(rule_chars)
    handoff_tokens = chars_to_tokens(handoff_chars)
    total_tokens = profile_tokens + entry_tokens + rule_tokens + handoff_tokens
    level = disclosure_level(total_tokens)

    print(f"Project: {profile.project_name}")
    print(f"Description: {profile.description}")
    print(f"Stacks: {', '.join(profile.stacks) if profile.stacks else '(none detected)'}")
    print(f"Key files ({len(profile.key_files)}):")
    for key_file in profile.key_files[:10]:
        print(f"  - {key_file}")
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
