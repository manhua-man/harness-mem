"""Wake command implementation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    log_next_step_shown,
    profile_text,
    resolve_project_name,
    wake_budget,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def cmd_wake_up(project_name: str | None) -> int:
    """Generate wake-up context for a project."""
    project_name = resolve_project_name(project_name, action_label="wake-up")
    if not project_name:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    try:
        profile = await profile_store.get(project_name)
        if profile:
            profile_chars = len(profile.project_name or "") + len(profile_text(profile))
            print(f"# Project Profile  (source: profile, ~{profile_chars} chars)")
            print(f"Description: {profile.description}")
            print(f"Stacks: {', '.join(profile.stacks)}")
            if profile.key_files:
                print("Key files:")
                for key_file in profile.key_files[:5]:
                    print(f"  - {key_file}")
            if profile.conventions:
                print("Conventions:")
                for convention in profile.conventions[:5]:
                    print(f"  - {convention}")
            print()
        else:
            print("# Project Profile  (source: profile, empty)")
            print()

        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
        if handoffs:
            handoff_chars = sum(
                len(handoff.summary or "") + len(str(handoff.next_steps)) + len(str(handoff.blockers))
                for handoff in handoffs
            )
            print(f"# Recent Tasks  (source: task_handoffs, {len(handoffs)} items, ~{handoff_chars} chars)")
            for handoff in handoffs:
                print(f"## [{handoff.status}] {handoff.summary}")
                if handoff.next_steps:
                    print(f"  Next: {handoff.next_steps[0]}")
                if handoff.blockers:
                    print(f"  Blockers: {', '.join(handoff.blockers)}")
                if handoff.provenance:
                    provenance = handoff.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()
        else:
            print("# Recent Tasks  (source: task_handoffs, empty)")
            print()

        rules = await backend.structured_store.list_confirmed_rules(project_name)
        if rules:
            rules_chars = sum(len(rule.trigger or "") + len(rule.pattern or "") for rule in rules)
            print(f"# Confirmed Rules  (source: confirmed_rules, {len(rules)} rules, ~{rules_chars} chars)")
            for rule in rules[:5]:
                trigger_preview = rule.trigger[:60] + "..." if len(rule.trigger) > 60 else rule.trigger
                pattern_preview = rule.pattern[:60] + "..." if len(rule.pattern) > 60 else rule.pattern
                print(f"- **{trigger_preview}**: {pattern_preview} [...truncated]")
                if rule.provenance:
                    provenance = rule.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()
        else:
            print("# Confirmed Rules  (source: confirmed_rules, empty)")
            print()

        relation_facts = await backend.structured_store.list_relation_facts(project_name, limit=5)
        if relation_facts:
            relation_chars = sum(
                len(fact.source_entity)
                + len(fact.relation_type)
                + len(fact.target_entity)
                + len(fact.evidence)
                for fact in relation_facts
            )
            print(
                f"# Relation Facts  (source: relation_facts, "
                f"{len(relation_facts)} facts, ~{relation_chars} chars)"
            )
            for fact in relation_facts:
                evidence_preview = fact.evidence[:100] + "..." if len(fact.evidence) > 100 else fact.evidence
                print(f"- {fact.source_entity} --{fact.relation_type}-> {fact.target_entity}: {evidence_preview}")
                if fact.provenance:
                    provenance = fact.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()

        entries = await backend.structured_store.list_memory_entries(project_name, limit=5)
        if entries:
            entry_chars = sum(len(entry.content or "") for entry in entries)
            print(f"# Memory Entries  (source: structured_memory, {len(entries)} entries, ~{entry_chars} chars)")
            for entry in entries:
                content_preview = entry.content[:100] + "..." if len(entry.content) > 100 else entry.content
                print(f"- [{entry.category}] {content_preview}")
                if entry.provenance:
                    provenance = entry.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
                await backend.structured_store.touch_memory_entry(entry.id)
            print()
        else:
            print("# Memory Entries  (source: structured_memory, empty)")
            print()

        total_tokens, level = wake_budget(profile, entries, rules, handoffs, relation_facts)
        print(f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]")
        if level in ("L3", "L4+"):
            three_months_ago = (
                datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
            ).strftime("%Y-%m-%d")
            purge_command = (
                f"harness-mem purge -p {project_name} --before {three_months_ago} --category all --dry-run"
            )
            print(f"⚠️  Memory budget at {level}")
            print(f"💡 Run: {purge_command}")
            print("   to preview what can be archived.")
            log_next_step_shown(project_name, "wake-up", purge_command)

        log_command_invoked(
            "wake-up",
            project_name=project_name,
            extra={
                "disclosure_level": level,
                "memory_entries": len(entries),
                "relation_facts": len(relation_facts),
                "rules": len(rules),
            },
        )
    finally:
        await backend.close()
    return 0
