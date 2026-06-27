"""Commands for managing memory candidates and confirmed rules."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from harness_mem.commands import support as command_support
from harness_mem.event_log import StateEventType, append_state_event
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.core.schemas import (
    ConfirmedRule,
    RuleCandidate,
    SupersedeCandidate,
)
from harness_mem.read_api import format_validity_marker
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _record_state_event(
    backend: LocalMemoryBackend,
    *,
    event_type: StateEventType,
    project_name: str | None,
    target_kind: str,
    target_id: str,
    status: str | None,
    source_surface: str,
    payload: dict | None = None,
) -> str | None:
    try:
        return append_state_event(
            backend.data_dir,
            event_type=event_type,
            project_name=project_name,
            target_kind=target_kind,
            target_id=target_id,
            status=status,
            source_surface=source_surface,
            actor="cli",
            payload=payload,
        )
    except Exception:
        return None


async def cmd_correct(
    session_id: str,
    project_name: str,
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
    *,
    supersedes_rule_id: str | None = None,
    reason: str | None = None,
) -> int:
    """Create a RuleCandidate from a correction.

    When ``supersedes_rule_id`` is provided, the correction goes through the
    supersede path instead: a new ConfirmedRule is created immediately and
    the old rule's ``valid_to`` is set, with ``supersedes`` / ``superseded_by``
    links established. This is the right shape for "I'm correcting an
    existing rule because reality changed" (e.g. a Tauri v1 -> v2 migration
    obsoleting an IPC rule).

    The ordinary candidate-layer path (no ``supersedes_rule_id``) stays
    unchanged for backward compatibility and for "this is a new rule" flows.

    Why this is *not* a candidate-layer write when supersede is requested:
    the user (or an LLM agent calling ``suggest_correction``) has already
    expressed an explicit intent to replace a specific old rule. That intent
    is the confirm — making them then approve a supersede candidate would
    require two manual confirms for one decision.
    """
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()

    try:
        # Find observations from this session
        # We search project-specific first, then session-wide
        all_obs = await backend.verbatim_store.list(session_id=session_id, limit=1000)

        # Filtering logic: matches project_name OR has no project_name metadata (legacy/direct)
        session_obs = [
            obs
            for obs in all_obs
            if obs.metadata.get("project_name") == project_name
            or "project_name" not in obs.metadata
        ]

        if not session_obs:
            print(
                f"No observations found for session: {session_id} in project: {project_name}"
            )
            return 1

        print(f"Found {len(session_obs)} observations for session {session_id}")

        if supersedes_rule_id:
            return await _correct_via_supersede(
                backend,
                project_name=project_name,
                session_id=session_id,
                pattern=pattern,
                trigger=trigger,
                examples=command_support.clean_cli_list(examples),
                supersedes_rule_id=supersedes_rule_id,
                reason=reason,
            )

        # Default path: build a regular RuleCandidate.
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
        _record_state_event(
            backend,
            event_type=StateEventType.CANDIDATE_CREATED,
            project_name=project_name,
            target_kind="rule_candidate",
            target_id=saved_id,
            status="pending",
            source_surface="cli.correct",
            payload={"session_id": session_id, "trigger": trigger},
        )
        print(f"Created rule candidate: {saved_id}")
        return 0
    finally:
        await backend.close()


async def _correct_via_supersede(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    session_id: str,
    pattern: str,
    trigger: str,
    examples: list[str],
    supersedes_rule_id: str,
    reason: str | None,
) -> int:
    """Implement the ``supersedes_rule_id`` branch of ``cmd_correct``.

    Steps:
      1. Verify the old ConfirmedRule exists and is current (valid_to is None).
      2. Save the new ConfirmedRule (no candidate detour — the user supplied
         an explicit old_rule_id, which is the confirm).
      3. Save a SupersedeCandidate, then immediately confirm it. The confirm
         path applies all temporal updates atomically (old.valid_to,
         old.superseded_by, new.supersedes).
      4. Print a summary the human can read at a glance.
    """
    old_rule = await backend.structured_store.get_confirmed_rule(supersedes_rule_id)
    if old_rule is None:
        print(f"Cannot supersede: ConfirmedRule {supersedes_rule_id!r} not found.")
        return 1
    if old_rule.project_name != project_name:
        print(
            f"Cannot supersede: rule {supersedes_rule_id!r} belongs to project "
            f"{old_rule.project_name!r}, not {project_name!r}."
        )
        return 1
    if old_rule.valid_to is not None:
        print(
            f"Cannot supersede: rule {supersedes_rule_id!r} is already historical "
            f"(valid_to={old_rule.valid_to.isoformat()})."
        )
        return 1

    new_rule = ConfirmedRule(
        id=str(uuid4()),
        project_name=project_name,
        pattern=pattern,
        trigger=trigger,
        examples=examples,
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=f"correction:{session_id}",
        source_session_id=session_id,
    )
    await backend.structured_store.save_confirmed_rule(new_rule)
    _record_state_event(
        backend,
        event_type=StateEventType.TRUTH_CONFIRMED,
        project_name=project_name,
        target_kind="confirmed_rule",
        target_id=new_rule.id,
        status="accepted",
        source_surface="cli.correct",
        payload={"supersedes_rule_id": old_rule.id, "trigger": trigger},
    )

    candidate = SupersedeCandidate(
        id=str(uuid4()),
        project_name=project_name,
        target_type="confirmed_rule",
        target_id=old_rule.id,
        replacement_type="confirmed_rule",
        replacement_id=new_rule.id,
        reason=reason or f"Correction from session {session_id}.",
        evidence=f"User-driven correction in session {session_id}.",
        source=f"correction:{session_id}",
        confidence=1.0,
    )
    await backend.structured_store.save_supersede_candidate(candidate)
    _record_state_event(
        backend,
        event_type=StateEventType.CANDIDATE_CREATED,
        project_name=project_name,
        target_kind="supersede",
        target_id=candidate.id,
        status="pending",
        source_surface="cli.correct",
        payload={
            "target_type": candidate.target_type,
            "target_id": candidate.target_id,
            "replacement_type": candidate.replacement_type,
            "replacement_id": candidate.replacement_id,
        },
    )
    confirmed = await backend.structured_store.confirm_supersede_candidate(candidate.id)
    if confirmed is None:
        print(
            f"Created new rule {new_rule.id} but supersede confirmation failed; "
            f"old rule {old_rule.id} is still current. "
            f"Call MCP confirm_supersede(candidate_id={candidate.id!r})"
        )
        return 1

    # v2.3.0: shadow-emit a `supersede_completed` retrieval signal so the
    # metabolism replay-window selector treats CLI-driven corrections the
    # same as MCP-driven ones.
    await record_retrieval_signal(
        backend,
        project_name=project_name,
        signal_type="supersede_completed",
        target_kind="supersede",
        target_id=confirmed.id,
        context={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
            "source": "cmd_correct",
        },
    )
    _record_state_event(
        backend,
        event_type=StateEventType.SUPERSEDE_COMPLETED,
        project_name=project_name,
        target_kind="supersede",
        target_id=confirmed.id,
        status=confirmed.status,
        source_surface="cli.correct",
        payload={
            "target_type": confirmed.target_type,
            "target_id": confirmed.target_id,
            "replacement_type": confirmed.replacement_type,
            "replacement_id": confirmed.replacement_id,
        },
    )

    print(
        f"Superseded rule {old_rule.id} with new rule {new_rule.id}. "
        f"Old rule is now historical (valid_to={confirmed.reviewed_at.isoformat() if confirmed.reviewed_at else 'now'})."
    )
    return 0


async def cmd_confirm_rule(rule_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        # Check MemoryEntry, RelationFact, and RuleCandidate
        if await backend.structured_store.update_memory_entry_status(
            rule_id, "accepted"
        ):
            entry = await backend.structured_store.get_memory_entry(rule_id)
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_CONFIRMED,
                project_name=entry.project_name if entry else None,
                target_kind="memory_entry",
                target_id=rule_id,
                status="accepted",
                source_surface="cli.confirm_rule",
                payload={"category": getattr(entry, "category", None)},
            )
            print(f"Confirmed MemoryEntry: {rule_id}")
            return 0
        if await backend.structured_store.update_relation_fact_status(
            rule_id, "accepted"
        ):
            fact = await backend.structured_store.get_relation_fact(rule_id)
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_CONFIRMED,
                project_name=fact.project_name if fact else None,
                target_kind="relation_fact",
                target_id=rule_id,
                status="accepted",
                source_surface="cli.confirm_rule",
                payload={"relation_type": getattr(fact, "relation_type", None)},
            )
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
            await backend.structured_store.update_rule_candidate_status(
                rule_id, "accepted"
            )
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_CONFIRMED,
                project_name=candidate.project_name,
                target_kind="confirmed_rule",
                target_id=confirmed.id,
                status="accepted",
                source_surface="cli.confirm_rule",
                payload={"source_candidate_id": rule_id, "trigger": confirmed.trigger},
            )
            print(f"Confirmed Rule: {confirmed.id}")
            return 0
        return 1
    finally:
        await backend.close()


async def cmd_reject_rule(rule_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        if await backend.structured_store.update_memory_entry_status(
            rule_id, "rejected"
        ):
            entry = await backend.structured_store.get_memory_entry(rule_id)
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_REJECTED,
                project_name=entry.project_name if entry else None,
                target_kind="memory_entry",
                target_id=rule_id,
                status="rejected",
                source_surface="cli.reject_rule",
                payload={"category": getattr(entry, "category", None)},
            )
            print(f"Rejected MemoryEntry: {rule_id}")
            return 0
        if await backend.structured_store.update_relation_fact_status(
            rule_id, "rejected"
        ):
            fact = await backend.structured_store.get_relation_fact(rule_id)
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_REJECTED,
                project_name=fact.project_name if fact else None,
                target_kind="relation_fact",
                target_id=rule_id,
                status="rejected",
                source_surface="cli.reject_rule",
                payload={"relation_type": getattr(fact, "relation_type", None)},
            )
            print(f"Rejected RelationFact: {rule_id}")
            return 0
        if await backend.structured_store.update_rule_candidate_status(
            rule_id, "rejected"
        ):
            candidate = await backend.structured_store.get_rule_candidate(rule_id)
            _record_state_event(
                backend,
                event_type=StateEventType.TRUTH_REJECTED,
                project_name=candidate.project_name if candidate else None,
                target_kind="rule_candidate",
                target_id=rule_id,
                status="rejected",
                source_surface="cli.reject_rule",
                payload={"trigger": getattr(candidate, "trigger", None)},
            )
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
        rules = await backend.structured_store.list_rule_candidates(
            project_name, status=effective_status
        )
        entries = await backend.structured_store.list_memory_entries(
            project_name, status=effective_status
        )
        facts = await backend.structured_store.list_relation_facts(
            project_name, status=effective_status
        )
        supersedes = await backend.structured_store.list_supersede_candidates(
            project_name, status=effective_status
        )
        procedural = await backend.structured_store.list_procedural_candidates(
            project_name, status=effective_status
        )
        total = (
            len(rules) + len(entries) + len(facts) + len(supersedes) + len(procedural)
        )
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
        for candidate in procedural:
            print(
                f"  [Procedural] {candidate.id}: {candidate.activation_condition[:50]}"
            )
        return 0
    finally:
        await backend.close()


async def cmd_confirmed_rules(
    project_name: str, *, include_history: bool = False
) -> int:
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
        _record_state_event(
            backend,
            event_type=StateEventType.CANDIDATE_CREATED,
            project_name=project_name,
            target_kind="supersede",
            target_id=saved_id,
            status="pending",
            source_surface="cli.suggest_supersede",
            payload={
                "target_type": target_type,
                "target_id": target_id,
                "replacement_type": replacement_type,
                "replacement_id": replacement_id,
            },
        )
        print(f"Created SupersedeCandidate: {saved_id}")
        return 0
    finally:
        await backend.close()


async def cmd_confirm_supersede(candidate_id: str) -> int:
    backend = LocalMemoryBackend(command_support.DEFAULT_DATA_DIR)
    await backend.init()
    try:
        confirmed = await backend.structured_store.confirm_supersede_candidate(
            candidate_id
        )
        if confirmed is None:
            return 1
        await record_retrieval_signal(
            backend,
            project_name=confirmed.project_name,
            signal_type="supersede_completed",
            target_kind="supersede",
            target_id=confirmed.id,
            context={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
        _record_state_event(
            backend,
            event_type=StateEventType.SUPERSEDE_COMPLETED,
            project_name=confirmed.project_name,
            target_kind="supersede",
            target_id=confirmed.id,
            status=confirmed.status,
            source_surface="cli.confirm_supersede",
            payload={
                "target_type": confirmed.target_type,
                "target_id": confirmed.target_id,
                "replacement_type": confirmed.replacement_type,
                "replacement_id": confirmed.replacement_id,
            },
        )
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
        updated = await backend.structured_store.update_supersede_candidate_status(
            candidate_id, "rejected"
        )
        if not updated:
            return 1
        _record_state_event(
            backend,
            event_type=StateEventType.TRUTH_REJECTED,
            project_name=candidate.project_name,
            target_kind="supersede",
            target_id=candidate_id,
            status="rejected",
            source_surface="cli.reject_supersede",
            payload={
                "target_type": candidate.target_type,
                "target_id": candidate.target_id,
                "replacement_type": candidate.replacement_type,
                "replacement_id": candidate.replacement_id,
            },
        )
        print(f"Rejected SupersedeCandidate: {candidate_id}")
        return 0
    finally:
        await backend.close()
