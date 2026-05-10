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
HANDOFF_STATUSES = ("in_progress", "pending", "blocked", "done")


def clean_cli_text(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


def clean_cli_list(values: list[str] | None) -> list[str]:
    return [
        cleaned
        for value in values or []
        if (cleaned := clean_cli_text(value)) is not None
    ]


def normalize_handoff_status(value: str | None) -> str:
    cleaned = clean_cli_text(value)
    if cleaned is None:
        return "in_progress"
    return cleaned.lower().replace("-", "_")


def _required_text(label: str, value: str | None) -> str | None:
    cleaned = clean_cli_text(value)
    if cleaned is None:
        print(f"{label} is required.")
    return cleaned


def _observations_for_project(all_observations, session_id: str, project_name: str):
    matching_session = [
        observation for observation in all_observations
        if observation.session_id == session_id
    ]
    matching_project = [
        observation for observation in matching_session
        if observation.metadata.get("project_name") == project_name
    ]
    if matching_project:
        return matching_project
    if matching_session and all(
        "project_name" not in observation.metadata for observation in matching_session
    ):
        return matching_session
    return []

async def cmd_correct(session_id: str, project_name: str, pattern: str, trigger: str, examples: list[str] | None = None) -> int:
    """Create a RuleCandidate from a correction.

    Usage: harness-mem correct --session-id <id> --project <name> --pattern "..." --trigger "..."
    """
    clean_session_id = _required_text("Session ID", session_id)
    clean_project_name = _required_text("Project name", project_name)
    clean_pattern = _required_text("Rule pattern", pattern)
    clean_trigger = _required_text("Trigger", trigger)
    if not clean_session_id or not clean_project_name or not clean_pattern or not clean_trigger:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Find observations from this session
        all_obs = await backend.verbatim_store.list(limit=1000)
        session_obs = _observations_for_project(all_obs, clean_session_id, clean_project_name)

        if not session_obs:
            print(f"No observations found for session: {clean_session_id} in project: {clean_project_name}")
            print("Run `harness-mem ingest claude-code` first, or pass the project that owns this session.")
            return 1

        print(f"Found {len(session_obs)} observations for session {clean_session_id}")

        # Build candidate
        candidate = RuleCandidate(
            id=str(uuid4()),
            project_name=clean_project_name,
            session_id=clean_session_id,
            pattern=clean_pattern,
            trigger=clean_trigger,
            examples=clean_cli_list(examples),
            confidence=0.6,
            status="pending",
        )

        saved_id = await backend.structured_store.save_rule_candidate(candidate)
        print(f"Created rule candidate: {saved_id}")
        print(f"  Pattern: {candidate.pattern}")
        print(f"  Trigger: {candidate.trigger}")
        print(f"  Session: {clean_session_id}")
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
                print("  Examples:")
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
    clean_project_name = _required_text("Project name", project_name)
    clean_task_id = _required_text("Task ID", task_id)
    clean_summary = _required_text("Summary", summary)
    clean_status = normalize_handoff_status(status)
    clean_next_steps = clean_cli_list(next_steps)
    clean_blockers = clean_cli_list(blockers)
    if not clean_project_name or not clean_task_id or not clean_summary:
        return 1
    if clean_status not in HANDOFF_STATUSES:
        allowed = ", ".join(HANDOFF_STATUSES)
        print(f"Invalid handoff status: {status}. Expected one of: {allowed}")
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Check if task already exists
        existing = None
        handoffs = await backend.structured_store.get_latest_handoffs(clean_project_name, limit=100)
        for h in handoffs:
            if h.task_id == clean_task_id:
                existing = h
                break

        if existing:
            # Update
            now = datetime.now(timezone.utc)
            existing.summary = clean_summary
            existing.status = clean_status
            if clean_next_steps:
                existing.next_steps = clean_next_steps
            if clean_blockers:
                existing.blockers = clean_blockers
            existing.last_activity = now
            existing.updated_at = now
            await backend.structured_store.save_task_handoff(existing)
            print(f"Updated handoff: {existing.id}")
        else:
            handoff = TaskHandoff(
                id=str(uuid4()),
                project_name=clean_project_name,
                task_id=clean_task_id,
                summary=clean_summary,
                status=clean_status,
                next_steps=clean_next_steps,
                blockers=clean_blockers,
            )
            await backend.structured_store.save_task_handoff(handoff)
            print(f"Created handoff: {handoff.id}")

        return 0
    finally:
        await backend.close()
