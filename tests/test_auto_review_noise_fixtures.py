"""Noise fixtures for the shared auto-review policy.

These tests pin the five noise categories the v2.2 daily-workflow spec calls
out as "things that pollute candidate review queues but are not project
knowledge":

- tool failure (TeamCreate / SendMessage / MCP parameter error / agent idle)
- cross-project workflow leakage (/plan-eng-review, KISS / YAGNI etc.)
- generic advice (write good code / use clear names / follow best practices)
- distill-process self-reference (prepare_session_distill / session-distill)
- duplicate candidate (same content appearing twice in one auto-review pass)

The first four are pure-function regex matches and use ``decide_memory_entry``
/ ``decide_rule_candidate`` directly. The duplicate case needs the storage
layer because dedup happens at the ``auto_review_candidates`` orchestration
level (after individual decisions are computed).
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from harness_mem.commands.auto_review import (
    auto_review_candidates,
    decide_memory_entry,
    decide_rule_candidate,
    explain_decision,
)
from harness_mem.core.schemas import MemoryEntry, RuleCandidate
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def _entry(content: str, *, source: str = 'agent:test') -> MemoryEntry:
    return MemoryEntry(
        id=str(uuid4()),
        project_name='noise-fixtures',
        category='decision',
        content=content,
        confidence=0.9,
        status='pending',
        source=source,
    )


def _rule(pattern: str, trigger: str = 'When working on the codebase') -> RuleCandidate:
    return RuleCandidate(
        id=str(uuid4()),
        project_name='noise-fixtures',
        session_id='sess-test',
        pattern=pattern,
        trigger=trigger,
        examples=['example 1'],
        confidence=0.9,
        status='pending',
    )


# ---------------------------------------------------------------------------
# tool failure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('content', [
    'TeamCreate failed because no agent was idle to receive the work item.',
    'SendMessage returned an MCP parameter error when piping to the worker.',
    'TeamDelete dropped the working session before the run completed.',
    'ToolSearch could not resolve the request and the agent went idle.',
])
def test_tool_failure_content_is_auto_rejected(content: str) -> None:
    decision = decide_memory_entry(_entry(content))
    assert decision.action == 'auto_reject'
    assert 'tool failure' in decision.reason


# ---------------------------------------------------------------------------
# cross-project workflow leakage
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('content', [
    '/plan-eng-review was used to validate the upstream architecture proposal.',
    '/plan-ceo-review surfaced a scope question we should track separately.',
    'We applied KISS to keep the helper as a single function rather than a class.',
    'Always follow YAGNI when adding new optional flags to the CLI.',
    "Don't break userspace was the rationale for keeping the legacy alias.",
])
def test_cross_project_workflow_content_is_auto_rejected(content: str) -> None:
    decision = decide_memory_entry(_entry(content))
    assert decision.action == 'auto_reject'
    assert 'cross-project workflow' in decision.reason


# ---------------------------------------------------------------------------
# distill-process self-reference
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('content', [
    'prepare_session_distill returned no observations for the project this run.',
    'session-distill skill needs the evidence packet before it can produce candidates.',
    'The distill process itself should keep its summary on a single line.',
])
def test_distill_self_reference_content_is_auto_rejected(content: str) -> None:
    decision = decide_memory_entry(_entry(content))
    assert decision.action == 'auto_reject'
    assert 'distill-process self-reference' in decision.reason


# ---------------------------------------------------------------------------
# generic advice
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('content', [
    'Always write good code and keep the modules small for future readers.',
    'Test your code before committing to the shared branch.',
    'Use clear names for variables and helpers throughout the codebase.',
    'Follow best practices when designing the public API surface.',
])
def test_generic_advice_content_is_auto_rejected(content: str) -> None:
    decision = decide_memory_entry(_entry(content))
    assert decision.action == 'auto_reject'
    assert 'generic advice' in decision.reason


def test_generic_advice_rule_candidate_is_auto_rejected() -> None:
    rule = _rule('Write good code and follow best practices on every PR.')
    decision = decide_rule_candidate(rule)
    assert decision.action == 'auto_reject'
    assert 'generic advice' in decision.reason


# ---------------------------------------------------------------------------
# evidence-id requirement (4.2)
# ---------------------------------------------------------------------------

def test_auto_confirm_requires_non_manual_source() -> None:
    """A long, high-confidence decision still defers when source == 'manual'."""
    entry = _entry(
        'We standardised on SQLite + sqlite-utils for all structured stores '
        'because the project is local-first and benefits from a zero-config '
        'embedded database.',
        source='manual',
    )
    decision = decide_memory_entry(entry)
    assert decision.action == 'defer'
    assert 'evidence' in decision.reason.lower()
    assert decision.is_high_risk is True
    assert decision.evidence_id is None


def test_auto_confirm_evidence_id_is_propagated() -> None:
    entry = _entry(
        'We standardised on SQLite + sqlite-utils for all structured stores '
        'because the project is local-first and benefits from a zero-config '
        'embedded database.',
        source='obs_abc123',
    )
    decision = decide_memory_entry(entry)
    assert decision.action == 'auto_confirm'
    assert decision.evidence_id == 'obs_abc123'


def test_rule_candidate_without_examples_defers_as_high_risk() -> None:
    rule = RuleCandidate(
        id=str(uuid4()),
        project_name='noise-fixtures',
        session_id='sess-rule',
        pattern='Use parameterized queries for every dynamic SQL fragment.',
        trigger='Before composing SQL strings with user input',
        examples=[],
        confidence=0.95,
        status='pending',
    )
    decision = decide_rule_candidate(rule)
    assert decision.action == 'defer'
    assert 'evidence' in decision.reason.lower()
    assert decision.is_high_risk is True
    assert decision.evidence_id is None


# ---------------------------------------------------------------------------
# duplicate detection (4.3) — needs storage
# ---------------------------------------------------------------------------

def test_duplicate_candidate_is_auto_rejected_after_first_occurrence(
    data_dir: Path,
) -> None:
    """Same content twice: first keeps its decision, second becomes duplicate."""
    project_name = 'noise-fixtures-dup'
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store
        first = MemoryEntry(
            id=str(uuid4()),
            project_name=project_name,
            category='decision',
            content=(
                'We standardised on SQLite + sqlite-utils for all structured '
                'stores because the project is local-first and benefits from '
                'a zero-config embedded database.'
            ),
            confidence=0.9,
            status='pending',
            source='obs_first',
        )
        second = MemoryEntry(
            id=str(uuid4()),
            project_name=project_name,
            category='decision',
            content=first.content,
            confidence=0.9,
            status='pending',
            source='obs_second',
        )
        run(store.save_memory_entry(first))
        run(store.save_memory_entry(second))

        # apply=True so we can inspect each per-candidate decision.
        applied_summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        decisions_by_id = {
            d.candidate_id: d for d in applied_summary.applied_decisions
        }

        # Exactly two candidates, one keeps its action and one becomes
        # ``auto_reject (duplicate of <id>)``. Iteration order is store-
        # defined, so we don't pin which of ``first`` / ``second`` wins.
        actions = sorted(d.action for d in decisions_by_id.values())
        assert actions == ['auto_confirm', 'auto_reject']

        duplicate_decisions = [
            d for d in decisions_by_id.values()
            if 'duplicate of' in d.reason
        ]
        assert len(duplicate_decisions) == 1
        dup = duplicate_decisions[0]
        assert dup.action == 'auto_reject'
        # The duplicate's reason must reference the canonical id (the
        # other candidate in the pair) so /hm:distill can render
        # "rejected because duplicate of <id>".
        canonical_ids = {first.id, second.id} - {dup.candidate_id}
        assert canonical_ids
        canonical_id = next(iter(canonical_ids))
        assert canonical_id in dup.reason
    finally:
        run(backend.close())


# ---------------------------------------------------------------------------
# 4.4 silent-kept-pending vs needs-user-confirmation split
# ---------------------------------------------------------------------------

def test_silent_kept_pending_does_not_increment_needs_user_confirmation(
    data_dir: Path,
) -> None:
    """A bug-category defer is low-risk and should not nudge the user."""
    project_name = 'noise-fixtures-silent'
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store
        # bug-category defer: low-risk, must be silent.
        bug_entry = MemoryEntry(
            id=str(uuid4()),
            project_name=project_name,
            category='bug',
            content=(
                'A long bug description that exceeds the minimum content '
                'threshold so the auto-rejector lets it through to the '
                'category branch.'
            ),
            confidence=0.95,
            status='pending',
            source='obs_bug',
        )
        run(store.save_memory_entry(bug_entry))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        assert summary.kept_pending == 1
        assert summary.needs_user_confirmation == 0
    finally:
        run(backend.close())


def test_rule_candidate_defer_is_high_risk(data_dir: Path) -> None:
    project_name = 'noise-fixtures-rule-risk'
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store
        rule = RuleCandidate(
            id=str(uuid4()),
            project_name=project_name,
            session_id='sess-rule-risk',
            pattern=(
                'Always run pre-commit before pushing to the main branch '
                'because CI rejects unformatted commits.'
            ),
            trigger='Before any push to main',
            examples=['ran black on touched files'],
            # Below RULE_AUTO_CONFIRM_MIN_CONFIDENCE, so it defers.
            confidence=0.6,
            status='pending',
        )
        run(store.save_rule_candidate(rule))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )
        assert summary.kept_pending == 1
        assert summary.needs_user_confirmation == 1
    finally:
        run(backend.close())


# ---------------------------------------------------------------------------
# 4.5 explain_decision helper
# ---------------------------------------------------------------------------

def test_explain_decision_returns_full_record(data_dir: Path) -> None:
    project_name = 'noise-fixtures-explain'
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        store = backend.structured_store
        good = MemoryEntry(
            id=str(uuid4()),
            project_name=project_name,
            category='decision',
            content=(
                'We pinned the embedding baseline to all-MiniLM-L6-v2 for '
                'LongMemEval to keep the v2.x scoreboard reproducible across '
                'environments.'
            ),
            confidence=0.95,
            status='pending',
            source='obs_explain',
        )
        run(store.save_memory_entry(good))

        summary = run(
            auto_review_candidates(backend, project_name=project_name, apply=True)
        )

        record = explain_decision(summary, good.id)
        assert record is not None
        assert record['candidate_id'] == good.id
        assert record['kind'] == 'memory_entry'
        assert record['action'] == 'auto_confirm'
        assert record['evidence_id'] == 'obs_explain'
        assert record['reason']

        # Unknown id returns None instead of raising.
        assert explain_decision(summary, 'does-not-exist') is None
    finally:
        run(backend.close())
