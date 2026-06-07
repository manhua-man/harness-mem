"""Status command implementation."""

from __future__ import annotations

from harness_mem.commands.dream import dream_status_snapshot
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    find_project_root,
    get_active_project,
    log_next_step_shown,
    resolve_project_name,
)
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.knowledge_cache import knowledge_cache_health
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
    await _print_dream_status(backend, project_name)
    await _print_knowledge_cache_status(backend, project_name, profile)

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
        next_step = f'MCP ingest_sessions(project_name="{project_name}", client="claude-code")'
        print(f"→ Next: {next_step}")
        print("   Why: No observations yet; ingestion should be driven by the agent through MCP")
        log_next_step_shown(project_name, "status", next_step)
    else:
        print()
        print("📍 Phase: Healthy")
        next_step = f'MCP wake(project_name="{project_name}")'
        print(f"→ Next: {next_step}")
        print("   Why: Memory is ready, MCP wake is the shortest path to project context")
        log_next_step_shown(project_name, "status", next_step)


def _suggested_purge_command(project_name: str | None) -> str:
    project_flag = f" -p {project_name}" if project_name else ""
    return f"harness-mem purge{project_flag} --before <DATE> --category all --dry-run"


def _load_project_config(project_name: str) -> MergedConfig | None:
    root = find_project_root(project_name)
    if root is None:
        return None
    try:
        return load_merged_config(str(root))
    except ConfigError:
        return None


async def _print_dream_status(
    backend: LocalMemoryBackend,
    project_name: str,
) -> None:
    config = _load_project_config(project_name)
    snapshot = await dream_status_snapshot(
        backend,
        project_name=project_name,
        config=config,
    )
    state = "enabled" if snapshot["enabled"] else "off"
    print(f"  Dream auto: {state}")
    if snapshot["last_run_id"]:
        print(
            "  Last dream: "
            f"{snapshot['last_status']} "
            f"(processed {snapshot['last_processed']}, failed {snapshot['last_failed']})"
        )
    else:
        print("  Last dream: none")


async def _print_knowledge_cache_status(
    backend: LocalMemoryBackend,
    project_name: str,
    profile: ProjectProfile | None,
) -> None:
    report = await knowledge_cache_health(
        backend,
        data_dir=DEFAULT_DATA_DIR,
        project_name=project_name,
        profile=profile,
        project_root=find_project_root(project_name),
    )
    print(
        "  Generated cache: "
        f"{report['generated_claim_count']} claims, "
        f"{report['stale_source_count']} stale source(s), "
        f"{report['orphaned_output_count']} orphaned output(s), "
        f"cache hit ratio {report['cache_hit_ratio']:.2f}"
    )


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
