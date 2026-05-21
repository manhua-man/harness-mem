"""Commands for managing memory candidates and confirmed rules."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from harness_mem.commands import support as command_support
from harness_mem.core.schemas import (
    ConfirmedRule,
    RuleCandidate,
    SupersedeCandidate,
)
from harness_mem.read_api import format_validity_marker
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def cmd_correct(session_id: str, project_name: str, pattern: str, trigger: str, examples: list[str] | None = None) -> int:
    """Create a RuleCandidate from a correction."""
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Find observations from this session
        # We search project-specific first, then session-wide
        all_obs = await backend.verbatim_store.list(session_id=session_id, limit=1000)
        
        # Filtering logic: matches project_name OR has no project_name metadata (legacy/direct)
        session_obs = [
            obs for obs in all_obs
            if obs.metadata.get("project_name") == project_name or "project_name" not in obs.metadata
        ]

        if not session_obs:
            print(f"No observations found for session: {session_id} in project: {project_name}")
            return 1

        print(f"Found {len(session_obs)} observations for session {session_id}")

        # Build candidate
        candidate = RuleCandidate(
            id=str(uuid4()),
            project_name=project_name,
            session_id=session_id,
            pattern=pattern,
            trigger=trigger,
            examples=command_support.clean_cli_list(examples),
            confidence=0.6,
            status="pending",
        )

        saved_id = await backend.structured_store.save_rule_candidate(candidate)
        print(f"Created rule candidate: {saved_id}")
        return 0
    finally:
        await backend.close()

async def cmd_confirm_rule(rule_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        # Check MemoryEntry, RelationFact, and RuleCandidate
        if await backend.structured_store.update_memory_entry_status(rule_id, "accepted"):
            print(f"Confirmed MemoryEntry: {rule_id}")
            return 0
        if await backend.structured_store.update_relation_fact_status(rule_id, "accepted"):
            print(f"Confirmed RelationFact: {rule_id}")
            return 0
            
        candidate = await backend.structured_store.get_rule_candidate(rule_id)
        if candidate:
            confirmed = ConfirmedRule(
                id=str(uuid4()),
                project_name=candidate.project_name,
                pattern=candidate.pattern,
                trigger=candidate.trigger,
                examples=candidate.examples,
                confirmed_at=datetime.now(timezone.utc),
                source_candidate_id=candidate.id,
                source_session_id=candidate.session_id,
            )
            await backend.structured_store.save_confirmed_rule(confirmed)
            await backend.structured_store.update_rule_candidate_status(rule_id, "accepted")
            print(f"Confirmed Rule: {confirmed.id}")
            return 0
        return 1
    finally:
        await backend.close()

async def cmd_reject_rule(rule_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        if await backend.structured_store.update_memory_entry_status(rule_id, "rejected"):
            print(f"Rejected MemoryEntry: {rule_id}")
            return 0
        if await backend.structured_store.update_relation_fact_status(rule_id, "rejected"):
            print(f"Rejected RelationFact: {rule_id}")
            return 0
        if await backend.structured_store.update_rule_candidate_status(rule_id, "rejected"):
            print(f"Rejected RuleCandidate: {rule_id}")
            return 0
        return 1
    finally:
        await backend.close()

async def cmd_list_candidates(project_name: str, status: str | None = None) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    effective_status = status or "pending"
    try:
        rules = await backend.structured_store.list_rule_candidates(project_name, status=effective_status)
        entries = await backend.structured_store.list_memory_entries(project_name, status=effective_status)
        facts = await backend.structured_store.list_relation_facts(project_name, status=effective_status)
        supersedes = await backend.structured_store.list_supersede_candidates(project_name, status=effective_status)
        total = len(rules) + len(entries) + len(facts) + len(supersedes)
        print(f"# Candidates ({project_name}): {total} items ({effective_status})")
        for rule_candidate in rules:
            print(f"  [Rule] {rule_candidate.id}: {rule_candidate.pattern[:50]}")
        for entry in entries:
            print(f"  [Entry] {entry.id}: {entry.content[:50]}")
        for fact in facts:
            print(f"  [Fact] {fact.id}: {fact.source_entity}->{fact.target_entity}")
        for supersede_candidate in supersedes:
            print(
                f"  [Supersede] {supersede_candidate.id}: "
                f"{supersede_candidate.target_type} -> {supersede_candidate.replacement_type}"
            )
        return 0
    finally:
        await backend.close()

async def cmd_confirmed_rules(project_name: str, *, include_history: bool = False) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        rules = await backend.structured_store.list_confirmed_rules(
            project_name,
            include_history=include_history,
        )
        print(f"# Confirmed Rules ({project_name})")
        for rule in rules:
            print(f"- {rule.trigger}{format_validity_marker(rule)}: {rule.pattern}")
        return 0
    finally:
        await backend.close()


async def cmd_suggest_supersede(
    project_name: str,
    target_type: str,
    target_id: str,
    replacement_type: str,
    replacement_id: str,
    reason: str,
    evidence: str,
    *,
    source: str = "",
    confidence: float = 0.7,
) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        candidate = SupersedeCandidate(
            project_name=project_name,
            target_type=target_type,
            target_id=target_id,
            replacement_type=replacement_type,
            replacement_id=replacement_id,
            reason=reason,
            evidence=evidence,
            source=source,
            confidence=confidence,
        )
        saved_id = await backend.structured_store.save_supersede_candidate(candidate)
        print(f"Created SupersedeCandidate: {saved_id}")
        return 0
    finally:
        await backend.close()


async def cmd_confirm_supersede(candidate_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        confirmed = await backend.structured_store.confirm_supersede_candidate(candidate_id)
        if confirmed is None:
            return 1
        print(f"Confirmed SupersedeCandidate: {confirmed.id}")
        return 0
    finally:
        await backend.close()


async def cmd_reject_supersede(candidate_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        candidate = await backend.structured_store.get_supersede_candidate(candidate_id)
        if candidate is None:
            return 1
        updated = await backend.structured_store.update_supersede_candidate_status(candidate_id, "rejected")
        if not updated:
            return 1
        print(f"Rejected SupersedeCandidate: {candidate_id}")
        return 0
    finally:
        await backend.close()
