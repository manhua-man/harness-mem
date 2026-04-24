"""CLI commands for correction loop and task handoffs."""

from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from harness_mem.core.schemas import (
    TaskHandoff,
    RuleCandidate,
    ConfirmedRule,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"

async def cmd_correct(session_id: str, project_name: str, pattern: str, trigger: str, examples: list[str] | None = None) -> int:
    """Create a RuleCandidate from a correction.

    Usage: harness-mem correct --session-id <id> --project <name> --pattern "..." --trigger "..."
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Find observations from this session
        all_obs = await backend.verbatim_store.list(limit=1000)
        session_obs = [o for o in all_obs if o.session_id == session_id]

        if not session_obs:
            print(f"No observations found for session: {session_id}")
            return 1

        print(f"Found {len(session_obs)} observations for session {session_id}")

        # Build candidate
        candidate = RuleCandidate(
            id=str(uuid4()),
            project_name=project_name,
            session_id=session_id,
            pattern=pattern,
            trigger=trigger,
            examples=examples or [],
            confidence=0.6,
            status="pending",
        )

        saved_id = await backend.structured_store.save_rule_candidate(candidate)
        print(f"Created rule candidate: {saved_id}")
        print(f"  Pattern: {candidate.pattern}")
        print(f"  Trigger: {candidate.trigger}")
        print(f"  Session: {session_id}")
        print()
        print("To confirm: harness-mem confirm-rule --rule-id " + saved_id)
        return 0
    finally:
        await backend.close()


async def cmd_confirm_rule(rule_id: str) -> int:
    """Promote a RuleCandidate to ConfirmedRule.

    Usage: harness-mem confirm-rule --rule-id <id>
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Get the candidate
        candidate = await backend.structured_store.get_rule_candidate(rule_id)
        if not candidate:
            print(f"Candidate not found: {rule_id}")
            return 1

        if candidate.status == "accepted":
            print(f"Candidate already confirmed: {rule_id}")
            return 1

        # Create confirmed rule
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

        print(f"Confirmed rule: {confirmed.id}")
        print(f"  Pattern: {confirmed.pattern}")
        print(f"  Trigger: {confirmed.trigger}")
        print(f"  From candidate: {candidate.id}")
        return 0
    finally:
        await backend.close()


async def cmd_reject_rule(rule_id: str) -> int:
    """Reject a RuleCandidate.

    Usage: harness-mem reject-rule --rule-id <id>
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        candidate = await backend.structured_store.get_rule_candidate(rule_id)
        if not candidate:
            print(f"Candidate not found: {rule_id}")
            return 1

        await backend.structured_store.update_rule_candidate_status(rule_id, "rejected")
        print(f"Rejected candidate: {rule_id}")
        return 0
    finally:
        await backend.close()


async def cmd_list_candidates(project_name: str, status: str | None = None) -> int:
    """List rule candidates for a project.

    Usage: harness-mem list-candidates --project <name> [--status pending]
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        candidates = await backend.structured_store.list_rule_candidates(project_name, status=status)
        if not candidates:
            print(f"No candidates found for {project_name}")
            return 0

        print(f"# Rule Candidates for {project_name}")
        if status:
            print(f"(filtered by status: {status})")
        print()

        for c in candidates:
            print(f"## {c.id}")
            print(f"  Status: {c.status}")
            print(f"  Pattern: {c.pattern[:80]}")
            print(f"  Trigger: {c.trigger[:80]}")
            print(f"  Confidence: {c.confidence}")
            if c.examples:
                print(f"  Examples: {len(c.examples)}")
            print()

        return 0
    finally:
        await backend.close()


async def cmd_confirmed_rules(project_name: str) -> int:
    """List confirmed rules for a project.

    Usage: harness-mem confirmed-rules --project <name>
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        rules = await backend.structured_store.list_confirmed_rules(project_name)
        if not rules:
            print(f"No confirmed rules for {project_name}")
            return 0

        print(f"# Confirmed Rules for {project_name}")
        print()

        for r in rules:
            print(f"## {r.id}")
            print(f"  Pattern: {r.pattern}")
            print(f"  Trigger: {r.trigger}")
            print(f"  Confirmed: {r.confirmed_at}")
            if r.source_session_id:
                print(f"  Source session: {r.source_session_id}")
            if r.examples:
                print(f"  Examples:")
                for ex in r.examples[:3]:
                    print(f"    - {ex[:100]}")
            print()

        return 0
    finally:
        await backend.close()


async def cmd_handoff(project_name: str, task_id: str, summary: str, status: str = "in_progress", next_steps: list[str] | None = None, blockers: list[str] | None = None) -> int:
    """Create or update a task handoff.

    Usage: harness-mem handoff --project <name> --task-id <id> --summary "..."
    """
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Check if task already exists
        existing = None
        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=100)
        for h in handoffs:
            if h.task_id == task_id:
                existing = h
                break

        if existing:
            # Update
            existing.status = status
            if next_steps:
                existing.next_steps = next_steps
            if blockers:
                existing.blockers = blockers
            existing.updated_at = datetime.now(timezone.utc)
            await backend.structured_store.save_task_handoff(existing)
            print(f"Updated handoff: {existing.id}")
        else:
            handoff = TaskHandoff(
                id=str(uuid4()),
                project_name=project_name,
                task_id=task_id,
                summary=summary,
                status=status,
                next_steps=next_steps or [],
                blockers=blockers or [],
            )
            await backend.structured_store.save_task_handoff(handoff)
            print(f"Created handoff: {handoff.id}")

        return 0
    finally:
        await backend.close()
