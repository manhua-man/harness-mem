from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import (
    AssimilationDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
    DistillCandidate,
)
from harness_mem.autonomous.provider import (
    DEFAULT_DISTILL_MODEL,
    ProviderError,
    ProviderResult,
)
from harness_mem.autonomous.worker import (
    _decide_with_candidate_retry,
    _assimilate_with_schema_retry,
    _govern_unfinished_handoff,
    _normalize_zero_candidate_signal_labels,
    _preferred_job_is_eligible,
    autonomous_receipt_path,
    read_autonomous_receipt,
    normalize_provider_review_state,
    _required_confidence,
    _verify_candidates,
    provider_candidate_control_reason,
    run_autonomous_distill_batch,
)
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.observation import Observation
from harness_mem.outcome_probe import inspect_autonomous_outcome
from harness_mem.hook_receipts import record_hook_execution
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _verify_all_candidates(self, manifest, *, runtime_dir, heartbeat=None):
    del runtime_dir
    if heartbeat is not None:
        heartbeat()
    return ProviderResult(
        decision=CandidateVerificationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_index": item["candidate_index"],
                        "semantic_support": "supported",
                        "future_scope": "durable",
                        "reason": "The bounded source directly supports a reusable project point.",
                    }
                    for item in manifest["candidates"]
                ]
            }
        ),
        provider=self.name,
        model="deterministic-test",
        duration_seconds=0.01,
        input_sha256="e" * 64,
        response_sha256="f" * 64,
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
        event_count=1,
    )


def test_default_worker_provider_uses_bounded_distill_model(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class _Provider:
        name = "responses_api"

        def __init__(self, *, model=None):
            from harness_mem.autonomous.provider import ResponsesApiProvider

            captured["model"] = ResponsesApiProvider(model=model).model

    monkeypatch.setattr("harness_mem.autonomous.worker.ResponsesApiProvider", _Provider)
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        result = run_autonomous_distill_batch(
            backend,
            project_name="demo",
            project_root=tmp_path,
            config=load_merged_config(tmp_path),
            trigger_id=None,
            client="codex",
        )
    finally:
        asyncio.run(backend.close())

    assert result["state"] == "idle"
    assert captured["model"] == DEFAULT_DISTILL_MODEL


def test_trigger_receipt_stays_bound_to_preferred_job_when_backlog_finishes_later(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    project = tmp_path / "project"
    project.mkdir()
    backend = LocalMemoryBackend(data_dir)
    asyncio.run(backend.init())
    preferred = SessionDistillJob(
        id="preferred-job",
        idempotency_key="preferred-key",
        project_name="demo",
        project_root=str(project),
        client="codex",
        session_id="trigger-session",
        source_id="preferred-source",
        source_revision="sha256:" + "a" * 64,
    )
    backlog = SessionDistillJob(
        id="backlog-job",
        idempotency_key="backlog-key",
        project_name="demo",
        project_root=str(project),
        client="codex",
        session_id="backlog-session",
        source_id="backlog-source",
        source_revision="sha256:" + "b" * 64,
    )

    class _Provider:
        name = "deterministic"

    monkeypatch.setattr(
        backend.transcript_store,
        "get_distill_job",
        lambda job_id: preferred if job_id == preferred.id else None,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.pending_distill_jobs",
        lambda *_args, **_kwargs: [backlog],
    )

    def fake_run_one(_backend, *, job_id, **_kwargs):
        session_id = (
            preferred.session_id if job_id == preferred.id else backlog.session_id
        )
        return {
            "status": "completed",
            "job_id": job_id,
            "session_id": session_id,
            "provider": {"job_id": job_id, "total_tokens": 1},
            "note": {"path": str(tmp_path / f"{job_id}.md"), "sha256": "c" * 64},
            "last_semantic_success_at": "2026-08-19T00:00:00+00:00",
            "last_job_completed_at": "2026-08-19T00:00:01+00:00",
            "last_note_materialized_at": "2026-08-19T00:00:02+00:00",
            "error": None,
        }

    monkeypatch.setattr("harness_mem.autonomous.worker._run_one", fake_run_one)
    try:
        result = run_autonomous_distill_batch(
            backend,
            project_name="demo",
            project_root=project,
            config=load_merged_config(project),
            trigger_id=preferred.session_id,
            client="codex",
            provider=_Provider(),
            max_jobs=2,
            preferred_job_id=preferred.id,
            launch_source="ide_hook",
            dispatch_generation="preferred-generation",
        )
        receipt = result["receipt"]
        assert [item["job_id"] for item in result["outcomes"]] == [
            preferred.id,
            backlog.id,
        ]
        assert receipt["state"] == "succeeded"
        assert receipt["trigger_id"] == preferred.session_id
        assert receipt["dispatch_generation"] == "preferred-generation"
        assert receipt["job_id"] == preferred.id
        assert receipt["session_id"] == preferred.session_id
        assert receipt["provider"]["job_id"] == preferred.id
        assert receipt["batch"]["jobs"][-1]["job_id"] == backlog.id
    finally:
        asyncio.run(backend.close())


def test_assimilation_retries_one_invalid_knowledge_item_shape(tmp_path: Path) -> None:
    attempts: list[dict] = []

    class _Provider:
        name = "schema-retry-provider"

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir
            attempts.append(manifest)
            if heartbeat is not None:
                heartbeat()
            if len(attempts) == 1:
                raise ProviderError(
                    "Responses provider returned invalid assimilation JSON: missing title",
                    kind="unrecoverable",
                )
            return ProviderResult(
                decision=AssimilationDecision.model_validate({"points": []}),
                provider=self.name,
                model="deterministic-test",
                duration_seconds=0.01,
                input_sha256="a" * 64,
                response_sha256="b" * 64,
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                event_count=1,
            )

    result = _assimilate_with_schema_retry(
        _Provider(),
        manifest={"verified_candidates": []},
        runtime_dir=tmp_path,
        heartbeat=None,
    )

    assert isinstance(result.decision, AssimilationDecision)
    assert len(attempts) == 2
    feedback = attempts[1]["assimilation_validation_feedback"]
    assert "missing title" in feedback["errors"][0]
    assert "split the offending statement" in feedback["instruction"]
    assert "Do not repeat or lightly rephrase" in feedback["instruction"]


def test_assimilation_retries_invalid_runtime_truth_target(tmp_path: Path) -> None:
    attempts: list[dict] = []

    def reject_unknown_handle(decision: AssimilationDecision) -> None:
        if decision.points[0].matched_truth_handles:
            raise ValueError("unavailable truth handle")

    class _Provider:
        name = "target-retry-provider"

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir
            attempts.append(manifest)
            if heartbeat is not None:
                heartbeat()
            point = {
                "candidate_id": "candidate-1",
                "disposition": "confirm" if len(attempts) == 1 else "no_write",
                "matched_truth_handles": ["missing-handle"] if len(attempts) == 1 else [],
                "canonical_title": None,
                "canonical_statement": None,
                "topic_path": [],
                "knowledge_items": [],
                "reason": "The candidate is already represented by current truth.",
            }
            return ProviderResult(
                decision=AssimilationDecision.model_validate({"points": [point]}),
                provider=self.name,
                model="deterministic-test",
                duration_seconds=0.01,
                input_sha256="a" * 64,
                response_sha256="b" * 64,
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                event_count=1,
            )

    result = _assimilate_with_schema_retry(
        _Provider(),
        manifest={"verified_candidates": [{"candidate_id": "candidate-1"}]},
        runtime_dir=tmp_path,
        heartbeat=None,
        validate_decision=reject_unknown_handle,
    )

    assert result.decision.points[0].disposition == "no_write"
    assert len(attempts) == 2
    feedback = attempts[1]["assimilation_validation_feedback"]
    assert feedback["errors"] == ["unavailable truth handle"]


def test_assimilation_model_requires_one_target_for_refine() -> None:
    with pytest.raises(ValueError, match="refine requires exactly one current truth handle"):
        AssimilationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_id": "candidate-1",
                        "disposition": "refine",
                        "matched_truth_handles": [],
                        "canonical_title": "Updated rule",
                        "canonical_statement": "Use the corrected current project rule.",
                        "topic_path": ["governance"],
                        "knowledge_items": [],
                        "reason": "The new fact would revise existing current truth.",
                    }
                ]
            }
        )


def test_missing_legacy_confidence_uses_neutral_non_truth_default() -> None:
    candidate = DistillCandidate.model_validate(
        {
            "kind": "memory",
            "category": "decision",
            "content": "The project retains this verified decision.",
            "evidence_basis": "user_statement",
            "verification_outcome": "verified",
            "verification_refs": [],
            "verification_reason_codes": [],
        }
    )

    assert _required_confidence(candidate) == 0.5


def test_assimilation_model_rejects_broad_checklist_as_one_knowledge_item() -> None:
    with pytest.raises(ValueError, match="too many separate steps"):
        AssimilationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_id": "broad-point",
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": None,
                        "canonical_statement": None,
                        "topic_path": [],
                        "knowledge_items": [
                            {
                                "title": "Whole pipeline",
                                "statement": (
                                    "Capture source data、preserve immutable evidence、"
                                    "normalize candidates、validate protocol、publish atomically."
                                ),
                                "topic_path": ["ingestion"],
                                "claim_kind": "design_requirement",
                            }
                        ],
                        "reason": "The candidate needs an atomic output.",
                    }
                ]
            }
        )

    relational = AssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": "relational-title-point",
                    "disposition": "add",
                    "matched_truth_handles": [],
                    "canonical_title": "Structure validation and business admission",
                    "canonical_statement": "Keep structure validation separate from business admission.",
                    "topic_path": ["ingestion"],
                    "knowledge_items": [],
                    "reason": "The relationship is one independently searchable principle.",
                }
            ]
        }
    )
    assert relational.points[0].canonical_title == "Structure validation and business admission"

    with pytest.raises(ValueError, match="title enumerates multiple facts"):
        AssimilationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_id": "combined-title-point",
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Capture, normalization, and publication",
                        "canonical_statement": "Validate the final API output.",
                        "topic_path": ["ingestion"],
                        "knowledge_items": [],
                        "reason": "The candidate needs one independently searchable fact.",
                    }
                ]
            }
        )

    with pytest.raises(ValueError, match="independent obligations"):
        AssimilationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_id": "combined-obligation-point",
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Publication and output validation",
                        "canonical_statement": (
                            "Must publish related records in one transaction; "
                            "must validate the final public API output."
                        ),
                        "topic_path": ["publication"],
                        "knowledge_items": [],
                        "reason": "The candidate combines independent publication and output rules.",
                    }
                ]
            }
        )


def test_distill_candidate_allows_broad_discovery_for_later_atomic_split() -> None:
    candidate = DistillCandidate.model_validate(
        {
            "kind": "memory",
            "category": "architecture",
            "content": (
                "Capture the source、preserve immutable evidence、normalize candidates、"
                "validate the protocol、publish transactionally."
            ),
            "evidence_basis": "user_statement",
            "verification_outcome": "verified",
            "verification_refs": [],
            "verification_reason_codes": [],
        }
    )

    assert candidate.content is not None
    assert "publish transactionally" in candidate.content


def test_canonical_knowledge_allows_one_obligation_with_required_field_list() -> None:
    decision = AssimilationDecision.model_validate(
        {
            "points": [
                {
                    "candidate_id": "final-review-fields",
                    "disposition": "add",
                    "matched_truth_handles": [],
                    "canonical_title": "Final review completeness",
                    "canonical_statement": (
                        "The final review must record the user request、actual result、"
                        "last-turn status、contradictions、unfinished work、evidence "
                        "status and promotion eligibility."
                    ),
                    "topic_path": ["session review"],
                    "knowledge_items": [],
                    "reason": "The listed fields form one completeness obligation.",
                }
            ]
        }
    )

    assert decision.points[0].canonical_statement is not None


def test_per_point_verifier_blocks_unsupported_and_session_only_candidates(
    tmp_path: Path,
) -> None:
    candidates = [
        DistillCandidate.model_validate(
            {
                "kind": "memory",
                "category": "status",
                "content": "The implementation is complete.",
                "confidence": 0.9,
                "evidence_basis": "user_statement",
                "verification_outcome": "verified",
                "verification_refs": [],
                "verification_reason_codes": [],
            }
        ),
        DistillCandidate.model_validate(
            {
                "kind": "memory",
                "category": "request",
                "content": "Show the current result now.",
                "confidence": 0.9,
                "evidence_basis": "user_statement",
                "verification_outcome": "verified",
                "verification_refs": [],
                "verification_reason_codes": [],
            }
        ),
    ]
    validated = [
        (candidate, {"kind": "memory", "content": candidate.content})
        for candidate in candidates
    ]

    class _Verifier:
        name = "semantic-verifier-test"

        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            del manifest, runtime_dir, heartbeat
            return ProviderResult(
                decision=CandidateVerificationDecision.model_validate(
                    {
                        "points": [
                            {
                                "candidate_index": 0,
                                "semantic_support": "partial",
                                "future_scope": "unclear",
                                "reason": "The source does not prove completion.",
                            },
                            {
                                "candidate_index": 1,
                                "semantic_support": "supported",
                                "future_scope": "session_only",
                                "reason": "This is only a one-off display request.",
                            },
                        ]
                    }
                ),
                provider=self.name,
                model="test",
                duration_seconds=0.01,
                input_sha256="a" * 64,
                response_sha256="b" * 64,
                input_tokens=10,
                output_tokens=10,
                total_tokens=20,
                event_count=1,
            )

    _result, verified = _verify_candidates(
        _Verifier(),
        manifest={"candidates": []},
        validated_candidates=validated,
        runtime_dir=tmp_path,
        heartbeat=None,
    )

    assert verified[0][1]["verification_outcome"] == "unverified"
    assert "semantic_support_incomplete" in verified[0][1][
        "verification_reason_codes"
    ]
    assert verified[1][1]["verification_outcome"] == "not_applicable"
    assert "session_only_not_durable" in verified[1][1][
        "verification_reason_codes"
    ]


class _DeterministicProvider:
    name = "codex_exec"
    verify = _verify_all_candidates

    def decide(self, manifest, *, runtime_dir, heartbeat=None):
        assert manifest["coverage"] == "complete_indexed_semantic_projection"
        assert manifest["semantic_projection"]["chunks"]
        refs = manifest["zero_candidate_exchange_refs"]
        assert refs
        if heartbeat is not None:
            heartbeat()
        exchange = refs[0]
        decision = AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "The user established a durable SQLite storage preference for this project.",
                    "final_user_request": "Always use SQLite for local indexes in this project.",
                    "final_outcome": "The assistant acknowledged the project-level storage preference.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                    "zero_candidate_challenge": None,
                },
                "candidates": [
                    {
                        "kind": "memory",
                        "category": "decision",
                        "content": "The project uses SQLite for local derived indexes.",
                        "confidence": 0.95,
                        "tags": ["sqlite", "storage"],
                        "evidence_basis": "user_statement",
                        "verification_outcome": "verified",
                        "verification_refs": [
                            {
                                "kind": "user_statement",
                                "exchange_index": exchange["exchange_index"],
                                "role": "user",
                                "content_sha256": exchange["content_sha256"],
                            }
                        ],
                        "verification_reason_codes": [],
                    }
                ],
            }
        )
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model="deterministic-test",
            duration_seconds=0.01,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=800,
            output_tokens=200,
            total_tokens=1000,
            event_count=3,
        )

    def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir
        if heartbeat is not None:
            heartbeat()
        points = [
            {
                "candidate_id": item["candidate_id"],
                "disposition": "add",
                "matched_truth_handles": [],
                "canonical_title": "Local index storage",
                "canonical_statement": item["statement"],
                "topic_path": ["storage"],
                "reason": "New durable project decision.",
            }
            for item in manifest["verified_candidates"]
        ]
        return ProviderResult(
            decision=AssimilationDecision.model_validate({"points": points}),
            provider=self.name,
            model="deterministic-test",
            duration_seconds=0.01,
            input_sha256="c" * 64,
            response_sha256="d" * 64,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            event_count=1,
            sandbox="no-tools",
        )


class _TransientProvider:
    name = "transient-test"

    def decide(self, manifest, *, runtime_dir, heartbeat=None):
        del manifest, runtime_dir, heartbeat
        raise ProviderError("timed out", kind="transient")


def test_autonomous_worker_adds_missing_exact_signal_labels_to_real_rationale() -> None:
    decision = AutonomousDecision.model_validate(
        {
            "semantic_review": {
                "session_summary": "The session only contained transient execution detail.",
                "final_user_request": "Run the requested maintenance workflow.",
                "final_outcome": "The workflow detail was useful only in this session.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "not_applicable",
                "promotion_decision": "no_promotion",
                "zero_candidate_challenge": {
                    "version": "v1",
                    "source_revision": "sha256:" + "a" * 64,
                    "evidence_fidelity": "complete",
                    "future_utility": "session_only",
                    "checks": {
                        "user_correction": "absent",
                        "explicit_decision": "absent",
                        "successful_solution": "absent",
                        "repeated_failure": "absent",
                        "rule_or_preference": "not_durable",
                        "reusable_workflow_or_fact": "not_durable",
                        "version_or_migration": "absent",
                        "unfinished_handoff": "absent",
                    },
                    "inspected_exchange_refs": [
                        {"exchange_index": 1, "content_sha256": "b" * 64}
                    ],
                    "conclusion": "no_durable_candidate",
                    "rationale": (
                        "The detected details describe only this run and do not "
                        "establish a stable preference or reusable verified result."
                    ),
                },
            },
            "candidates": [],
        }
    )
    normalized = _normalize_zero_candidate_signal_labels(
        decision,
        packet={
            "zero_candidate_challenge_template": {
                "checks": {
                    "rule_or_preference": "candidate_required",
                    "reusable_workflow_or_fact": "candidate_required",
                }
            }
        },
    )

    rationale = normalized.semantic_review.zero_candidate_challenge.rationale
    assert "rule_or_preference" in rationale
    assert "reusable_workflow_or_fact" in rationale
    assert rationale.startswith("The detected details describe only this run")


def test_autonomous_worker_retries_inconsistent_zero_candidate_decision(
    tmp_path: Path,
) -> None:
    source_revision = "sha256:" + "a" * 64
    exchange_ref = {"exchange_index": 1, "content_sha256": "b" * 64}

    def decision(*, corrected: bool) -> AutonomousDecision:
        return AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "The session described a potentially reusable workflow.",
                    "final_user_request": "Review the workflow for durable utility.",
                    "final_outcome": "The workflow was reviewed.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "not_applicable",
                    "promotion_decision": "no_promotion",
                    "zero_candidate_challenge": {
                        "version": "v1",
                        "source_revision": source_revision,
                        "evidence_fidelity": "complete",
                        "future_utility": "session_only" if corrected else "durable",
                        "checks": {
                            "user_correction": "absent",
                            "explicit_decision": "absent",
                            "successful_solution": "absent",
                            "repeated_failure": "absent",
                            "rule_or_preference": "not_durable"
                            if corrected
                            else "absent",
                            "reusable_workflow_or_fact": "not_durable"
                            if corrected
                            else "absent",
                            "version_or_migration": "absent",
                            "unfinished_handoff": "absent",
                        },
                        "inspected_exchange_refs": [exchange_ref],
                        "conclusion": "no_durable_candidate",
                        "rationale": (
                            "rule_or_preference and reusable_workflow_or_fact are "
                            "specific to this completed run and not stable project truth."
                            if corrected
                            else "The workflow appears durable but no candidate was returned."
                        ),
                    },
                },
                "candidates": [],
            }
        )

    class RetryProvider:
        name = "zero-retry-test"

        def __init__(self) -> None:
            self.manifests: list[dict] = []

        def decide(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir, heartbeat
            self.manifests.append(manifest)
            chosen = decision(corrected=len(self.manifests) == 2)
            return ProviderResult(
                decision=chosen,
                provider=self.name,
                model="test",
                duration_seconds=0.1,
                input_sha256=str(len(self.manifests)) * 64,
                response_sha256="f" * 64,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                event_count=1,
            )

    provider = RetryProvider()
    job = SessionDistillJob(
        id="job-zero",
        idempotency_key="key-zero",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-zero",
        source_id="source-zero",
        source_revision=source_revision,
        status="reviewing",
        phase="review",
        expected_chunk_count=1,
        completed_chunk_count=1,
    )
    result, final, validated, warnings = _decide_with_candidate_retry(
        provider,
        manifest={"contract_version": "test"},
        packet={
            "zero_candidate_challenge_template": {
                "checks": {
                    "rule_or_preference": "candidate_required",
                    "reusable_workflow_or_fact": "candidate_required",
                }
            }
        },
        job=job,
        runtime_dir=tmp_path,
        heartbeat=None,
    )

    assert len(provider.manifests) == 2
    feedback = provider.manifests[1]["candidate_validation_feedback"]
    assert "schema inconsistent" in " ".join(feedback["errors"])
    assert "cannot be marked absent" in " ".join(feedback["errors"])
    assert (
        final.semantic_review.zero_candidate_challenge.future_utility == "session_only"
    )
    assert validated == []
    assert warnings == []
    assert result.attempt_count == 2


def test_autonomous_worker_retries_partial_zero_candidate_before_finalization(
    tmp_path: Path,
) -> None:
    source_revision = "sha256:" + "d" * 64
    exchange_ref = {"exchange_index": 1, "content_sha256": "e" * 64}

    def decision(*, corrected: bool) -> AutonomousDecision:
        return AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "The session has no durable result after the complete review.",
                    "final_user_request": "Review the session for a durable conclusion.",
                    "final_outcome": "The work was reviewed without a durable conclusion.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "not_applicable",
                    "promotion_decision": "no_promotion",
                    "zero_candidate_challenge": {
                        "version": "v1",
                        "source_revision": source_revision,
                        "evidence_fidelity": "complete" if corrected else "partial",
                        "future_utility": "session_only",
                        "checks": {
                            "user_correction": "absent",
                            "explicit_decision": "absent",
                            "successful_solution": "absent",
                            "repeated_failure": "absent",
                            "rule_or_preference": "absent",
                            "reusable_workflow_or_fact": "absent",
                            "version_or_migration": "absent",
                            "unfinished_handoff": "absent",
                        },
                        "inspected_exchange_refs": [exchange_ref],
                        "conclusion": "no_durable_candidate",
                        "rationale": "Every required exchange was reviewed and contains no durable conclusion.",
                    },
                },
                "candidates": [],
            }
        )

    class RetryProvider:
        name = "partial-zero-retry-test"

        def __init__(self) -> None:
            self.manifests: list[dict] = []

        def decide(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir, heartbeat
            self.manifests.append(manifest)
            return ProviderResult(
                decision=decision(corrected=len(self.manifests) == 2),
                provider=self.name,
                model="test",
                duration_seconds=0.1,
                input_sha256=str(len(self.manifests)) * 64,
                response_sha256="f" * 64,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                event_count=1,
            )

    provider = RetryProvider()
    job = SessionDistillJob(
        id="job-partial-zero",
        idempotency_key="key-partial-zero",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-partial-zero",
        source_id="source-partial-zero",
        source_revision=source_revision,
        status="reviewing",
        phase="review",
        expected_chunk_count=1,
        completed_chunk_count=1,
    )
    _result, final, validated, warnings = _decide_with_candidate_retry(
        provider,
        manifest={"contract_version": "test"},
        packet={"zero_candidate_challenge_template": {"checks": {}}},
        job=job,
        runtime_dir=tmp_path,
        heartbeat=None,
    )

    assert len(provider.manifests) == 2
    assert "complete evidence fidelity" in " ".join(
        provider.manifests[1]["candidate_validation_feedback"]["errors"]
    )
    assert (
        final.semantic_review.zero_candidate_challenge.evidence_fidelity == "complete"
    )
    assert validated == []
    assert warnings == []


def test_reconciled_reviewing_trigger_job_remains_preferred() -> None:
    job = SessionDistillJob(
        id="job-1",
        idempotency_key="key-1",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-1",
        source_id="source-1",
        source_revision="sha256:" + "a" * 64,
        status="reviewing",
        phase="review",
        expected_chunk_count=1,
        completed_chunk_count=1,
    )

    assert _preferred_job_is_eligible(
        job,
        project_name="demo",
        trigger_id="session-1",
    )


def test_autonomous_worker_persists_job_bound_handoff_for_partial_review() -> None:
    job = SessionDistillJob(
        id="job-partial",
        idempotency_key="key-partial",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-partial",
        source_id="source-partial",
        source_revision="sha256:" + "a" * 64,
        status="reviewing",
        phase="review",
        expected_chunk_count=1,
        completed_chunk_count=1,
    )
    decision = AutonomousDecision.model_validate(
        {
            "semantic_review": {
                "session_summary": "The preference was answered while follow-up work remained.",
                "final_user_request": "Keep quality while reducing cost.",
                "final_outcome": "The preference was verified and follow-up remains.",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["Measure the next fixed model sample."],
                "evidence_status": "partial",
                "promotion_decision": "partial",
                "zero_candidate_challenge": None,
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "preference",
                    "content": "Reduce time and tokens without lowering result quality.",
                    "confidence": 0.99,
                    "tags": ["performance"],
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                }
            ],
        }
    )

    class _Tools:
        def __init__(self) -> None:
            self.calls = []

        def tool_govern_memory(self, *, action, arguments):
            self.calls.append((action, arguments))
            return {"success": True, "handoff_id": "handoff-partial"}

    tools = _Tools()
    result = _govern_unfinished_handoff(tools, job=job, decision=decision)

    assert result == {"success": True, "handoff_id": "handoff-partial"}
    assert tools.calls == [
        (
            "handoff",
            {
                "project_name": "demo",
                "task_id": "distill-follow-up-job-partial",
                "summary": "The preference was verified and follow-up remains.",
                "status": "in_progress",
                "next_steps": ["Measure the next fixed model sample."],
                "blockers": [],
                "distill_job_id": "job-partial",
            },
        )
    ]


def test_autonomous_worker_filters_handoff_and_bare_superseded_candidates() -> None:
    decision = AutonomousDecision.model_validate(
        {
            "semantic_review": {
                "session_summary": "A durable preference was answered while fixed measurement remained.",
                "final_user_request": "Reduce cost and measure one fixed sample.",
                "final_outcome": "The older approach was superseded; measurement remains.",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["Measure one fixed model sample."],
                "evidence_status": "partial",
                "promotion_decision": "partial",
                "zero_candidate_challenge": None,
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "preference",
                    "content": "Use fewer tokens without reducing quality.",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                },
                {
                    "kind": "memory",
                    "category": "approach_decision",
                    "content": "The older truncate-first approach is superseded.",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                },
                {
                    "kind": "memory",
                    "category": "unfinished_handoff",
                    "content": "The next task remains unfinished.",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                },
                {
                    "kind": "memory",
                    "category": "后续事项",
                    "content": "需要测量一个固定模型样本。",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                },
                {
                    "kind": "memory",
                    "category": "procedure",
                    "content": "When validation remains unfinished, retain the source and defer migration.",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                },
            ],
        }
    )

    reasons = [
        provider_candidate_control_reason(candidate, decision=decision)
        for candidate in decision.candidates
    ]

    assert reasons == [
        None,
        "bare superseded history belongs to summary or final outcome",
        "unfinished work belongs to the job-bound handoff",
        "unfinished work belongs to the job-bound handoff",
        None,
    ]


def test_autonomous_worker_normalizes_unfinished_promote_to_partial() -> None:
    decision = AutonomousDecision.model_validate(
        {
            "semantic_review": {
                "session_summary": "A durable preference exists while measurement remains unfinished.",
                "final_user_request": "Preserve the preference and measure a sample.",
                "final_outcome": "The preference was identified but measurement did not run.",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["Measure one fixed sample."],
                "evidence_status": "partial",
                "promotion_decision": "promote",
                "zero_candidate_challenge": None,
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "preference",
                    "content": "Use fewer tokens without reducing quality.",
                    "confidence": 0.99,
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                }
            ],
        }
    )

    normalized = normalize_provider_review_state(decision)

    assert normalized.semantic_review.promotion_decision == "partial"
    assert normalized.semantic_review.evidence_status == "partial"
    assert normalized.semantic_review.last_turn_status == "unfinished"


def test_autonomous_worker_retries_when_every_candidate_has_invalid_shape(
    tmp_path: Path,
) -> None:
    base_review = {
        "session_summary": "The session contains one potentially durable project rule.",
        "final_user_request": "Preserve the project workflow rule.",
        "final_outcome": "The workflow rule was identified for review.",
        "last_turn_status": "answered",
        "contradictions": [],
        "unfinished_work": [],
        "evidence_status": "answered",
        "promotion_decision": "promote",
        "zero_candidate_challenge": None,
    }
    decisions = [
        AutonomousDecision.model_validate(
            {
                "semantic_review": base_review,
                "candidates": [
                    {
                        "kind": "rule",
                        "pattern": None,
                        "trigger": "When the workflow runs",
                        "examples": [],
                        "evidence_basis": "transcript",
                        "verification_outcome": "unverified",
                        "verification_refs": [],
                        "verification_reason_codes": ["test-invalid-shape"],
                    }
                ],
            }
        ),
        AutonomousDecision.model_validate(
            {
                "semantic_review": base_review,
                "candidates": [
                    {
                        "kind": "rule",
                        "pattern": "Run the verified workflow before release.",
                        "trigger": "When the workflow runs",
                        "examples": [],
                        "evidence_basis": "transcript",
                        "verification_outcome": "unverified",
                        "verification_refs": [],
                        "verification_reason_codes": [],
                    }
                ],
            }
        ),
    ]

    class _RetryProvider:
        name = "retry-test"

        def __init__(self):
            self.manifests = []

        def decide(self, manifest, *, runtime_dir, heartbeat=None):
            self.manifests.append(manifest)
            decision = decisions[len(self.manifests) - 1]
            return ProviderResult(
                decision=decision,
                provider=self.name,
                model="test",
                duration_seconds=0.1,
                input_sha256=str(len(self.manifests)) * 64,
                response_sha256="f" * 64,
                input_tokens=100,
                output_tokens=20,
                total_tokens=120,
                event_count=1,
            )

    provider = _RetryProvider()
    job = SessionDistillJob(
        id="job-1",
        idempotency_key="key-1",
        project_name="demo",
        project_root="F:/demo",
        client="codex",
        session_id="session-1",
        source_id="source-1",
        source_revision="sha256:" + "a" * 64,
        status="reviewing",
        phase="review",
        expected_chunk_count=1,
        completed_chunk_count=1,
    )
    result, decision, validated, warnings = _decide_with_candidate_retry(
        provider,
        manifest={"contract_version": "test"},
        packet={"zero_candidate_exchange_refs": []},
        job=job,
        runtime_dir=tmp_path,
        heartbeat=None,
    )

    assert len(provider.manifests) == 2
    assert provider.manifests[1]["candidate_validation_feedback"]["errors"]
    assert decision.candidates[0].pattern
    assert len(validated) == 1
    assert warnings == []
    assert result.attempt_count == 2
    assert result.total_tokens == 240


def test_autonomous_worker_completes_job_materializes_note_and_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / ".harness-mem.toml").write_text(
        "[distill.autonomous]\nenabled = false\n\n[dream.auto]\nenabled = false\n",
        encoding="utf-8",
    )
    hook_manifest = project / ".codex" / "hooks.json"
    hook_manifest.parent.mkdir()
    hook_manifest.write_text(
        '{"hooks":{"SessionStart":[{"command":"harness-mem-hook"}],'
        '"Stop":[{"command":"harness-mem-hook"}]}}\n',
        encoding="utf-8",
    )
    data_dir = tmp_path / "data"
    notes_dir = tmp_path / "notes"
    backend = LocalMemoryBackend(data_dir)
    asyncio.run(backend.init())
    receipt_path = autonomous_receipt_path(
        data_dir,
        project_name="demo",
        project_root=project,
    )
    receipt_path.parent.mkdir(parents=True)
    receipt_path.write_text(
        '{"schema_version":1,"batch":{"jobs":[{"job_id":"stale"}]}}\n',
        encoding="utf-8",
    )
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="autonomous-session",
                client="codex",
                raw_content=(
                    "User: Always use SQLite for local indexes in this project.\n\n"
                    "Assistant: I will preserve that project storage decision.\n"
                ),
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name="demo",
            project_root=str(project),
            client="codex",
            session_id="autonomous-session",
            source_kind="jsonl",
            source_uri="file:///autonomous-session.jsonl",
            source_text=(
                "User: Always use SQLite for local indexes in this project.\n\n"
                "Assistant: I will preserve that project storage decision.\n"
            ),
        )
    )
    assert snapshot.distill_job_id is not None
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.pending_distill_jobs",
        lambda *_args, **_kwargs: [],
    )

    result = run_autonomous_distill_batch(
        backend,
        project_name="demo",
        project_root=project,
        config=load_merged_config(project),
        trigger_id="autonomous-session",
        client="codex",
        provider=_DeterministicProvider(),
        notes_dir=notes_dir,
        max_jobs=1,
        preferred_job_id=snapshot.distill_job_id,
        launch_source="ide_hook",
        dispatch_generation="dispatch-autonomous-session",
    )

    assert result["state"] == "succeeded", result
    stored = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert stored is not None and stored.status == "completed"
    # The new autonomous path is physically separated: this fresh session must
    # not create a compatibility candidate or promote a legacy MemoryEntry.
    legacy_entries = asyncio.run(
        backend.structured_store.list_memory_entries("demo", limit=20)
    )
    legacy_rules = asyncio.run(backend.structured_store.list_confirmed_rules("demo"))
    knowledge_store = backend.structured_store.knowledge_store
    separated_candidates = asyncio.run(knowledge_store.list_candidates("demo"))
    separated_entries = asyncio.run(knowledge_store.list_entries("demo"))
    assert legacy_entries == []
    assert legacy_rules == []
    assert separated_candidates == []
    mutations = asyncio.run(knowledge_store.list_mutations("demo"))
    assert [mutation.disposition for mutation in mutations] == ["add"]
    assert [(entry.title, entry.statement) for entry in separated_entries] == [
        ("Local index storage", "The project uses SQLite for local derived indexes.")
    ]
    assert len(stored.output_candidate_ids) == 1
    assert stored.promotion_summary["answer_packet"]["promoted_items"] == [
        {
            "title": "Local index storage",
            "fact": "The project uses SQLite for local derived indexes.",
            "kind": "knowledge",
            "category": "storage",
        }
    ]
    knowledge_path = project / ".harness-mem" / "session-knowledge-base.md"
    assert not knowledge_path.exists()
    knowledge_text = asyncio.run(
        knowledge_store.render_markdown("demo", include_details=True)
    )
    assert "## storage" in knowledge_text
    assert backend.transcript_store.db_path.resolve().as_uri() in knowledge_text
    assert f"source_id={snapshot.source.id}" in knowledge_text
    assert "source_revision=sha256%3A" in knowledge_text
    assert "file:///autonomous-session.jsonl" not in knowledge_text
    assert stored.review_execution_source == "autonomous_worker"
    assert stored.semantic_review["session_summary"].startswith("The user established")
    latest_note_path = notes_dir / "autonomous-session.md"
    note_path = notes_dir / "revisions" / stored.id / "autonomous-session.md"
    note = note_path.read_text(encoding="utf-8")
    assert latest_note_path.read_text(encoding="utf-8") == note
    assert stored.id in note
    assert "## 最终结果" in note
    assert "## 记忆治理结果" in note

    receipt = read_autonomous_receipt(
        data_dir,
        project_name="demo",
        project_root=project,
    )
    assert receipt is not None
    assert receipt["schema_version"] == 4
    assert receipt["hook_launch_verified"] is True
    assert receipt["hook_config_fingerprint"]
    assert receipt["last_semantic_success_at"]
    assert receipt["last_job_completed_at"]
    assert receipt["last_note_materialized_at"]
    assert receipt["provider"]["total_tokens"] == 1000
    verified_completion = receipt["last_verified_completion"]
    assert verified_completion["trigger_id"] == "autonomous-session"
    assert verified_completion["dispatch_generation"] == "dispatch-autonomous-session"
    assert verified_completion["job_id"] == stored.id
    assert verified_completion["provider"]["total_tokens"] == 1000
    assert verified_completion["note"]["sha256"]
    job_receipt = receipt["batch"]["jobs"][0]
    assert job_receipt["job_id"] == stored.id
    assert job_receipt["selection_reason"] == "trigger_session"
    assert job_receipt["provider"]["total_tokens"] == 1000
    assert job_receipt["provider"]["job_id"] == stored.id
    assert job_receipt["provider"]["source_revision"] == stored.source_revision
    assert job_receipt["provider"]["session_id_sha256"].startswith("sha256:")
    assert (
        job_receipt["provider"]["trigger_id_sha256"]
        == job_receipt["provider"]["session_id_sha256"]
    )
    assert job_receipt["provider"]["project_root_sha256"].startswith("sha256:")
    assert job_receipt["note"]["sha256"]

    # A later batch-level projection must never be used to fill evidence for
    # the trigger job. The verifier reads one complete batch.jobs[] record.
    receipt["provider"] = {**receipt["provider"], "total_tokens": 9999}
    receipt["note"] = {"path": str(notes_dir / "unrelated-session.md")}
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    record_hook_execution(
        data_dir,
        project_root=project,
        project_name="demo",
        client="codex",
        action="post-turn-maintenance",
        source="ide_hook",
        trigger_id="autonomous-session",
    )

    outcome = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert outcome["provider_isolated"] is True
    assert outcome["provider"]["total_tokens"] == 1000
    assert outcome["note_verified"] is True
    assert outcome["durable_hook_binding"] is True
    assert outcome["dispatch_generation_bound"] is True
    assert outcome["lifecycle_verified"] is True, outcome

    # A later revision gets its own immutable Note and cannot invalidate the
    # receipt-bound artifact for this completed job.
    later = stored.model_copy(
        update={
            "id": "later-job",
            "completed_at": datetime.now(timezone.utc),
        }
    )
    from harness_mem.session_notes import materialize_session_note

    later_note = materialize_session_note(later, notes_dir=notes_dir)
    assert Path(later_note["path"]).is_file()
    assert Path(outcome["note"]["path"]).read_text(encoding="utf-8") == note
    repeated = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert repeated["note_verified"] is True

    # A later Desktop Stop may overwrite the global latest hook receipt. The
    # autonomous receipt keeps its launch binding, so historical health stays
    # valid instead of turning red during normal interleaved tasks.
    record_hook_execution(
        data_dir,
        project_root=project,
        project_name="demo",
        client="codex",
        action="post-turn-maintenance",
        source="ide_hook",
        trigger_id="later-session",
    )
    interleaved = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert interleaved["latest_trigger_matches_hook"] is False
    assert interleaved["durable_hook_binding"] is True
    assert interleaved["lifecycle_verified"] is True

    # A complete v3 success is lazily migrated before the next mutable attempt.
    legacy = dict(receipt)
    legacy["schema_version"] = 3
    legacy.pop("last_verified_completion", None)
    receipt_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # A later attempt with no eligible work updates current attempt state but
    # must not erase the last complete success evidence.
    idle = run_autonomous_distill_batch(
        backend,
        project_name="demo",
        project_root=project,
        config=load_merged_config(project),
        trigger_id="idle-session",
        client="codex",
        provider=_DeterministicProvider(),
        notes_dir=notes_dir,
        max_jobs=1,
        launch_source="ide_hook",
    )
    assert idle["state"] == "idle"
    preserved = read_autonomous_receipt(
        data_dir,
        project_name="demo",
        project_root=project,
    )
    assert preserved is not None
    assert preserved["state"] == "idle"
    assert preserved["job_id"] is None
    assert preserved["last_verified_completion"] == verified_completion
    after_idle = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert after_idle["state"] == "idle"
    assert after_idle["latest_attempt_trigger_id"] == "idle-session"
    assert after_idle["trigger_id"] == "autonomous-session"
    assert after_idle["verified_completion_preserved"] is True
    assert after_idle["lifecycle_verified"] is True

    # A later provider timeout remains visible as the latest attempt while the
    # independently verified prior completion remains valid.
    deferred_snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="deferred-session",
                client="codex",
                raw_content="User: remember this timeout test\nAssistant: acknowledged\n",
                content_type="transcript",
            ),
            project_name="demo",
            project_root=str(project),
            client="codex",
            session_id="deferred-session",
            source_kind="jsonl",
            source_uri="file:///deferred-session.jsonl",
            source_text="User: remember this timeout test\nAssistant: acknowledged\n",
        )
    )
    assert deferred_snapshot.distill_job_id is not None
    deferred = run_autonomous_distill_batch(
        backend,
        project_name="demo",
        project_root=project,
        config=load_merged_config(project),
        trigger_id="deferred-session",
        client="codex",
        provider=_TransientProvider(),
        notes_dir=notes_dir,
        max_jobs=1,
        preferred_job_id=deferred_snapshot.distill_job_id,
        launch_source="ide_hook",
    )
    assert deferred["state"] == "deferred"
    after_deferred = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert after_deferred["state"] == "deferred"
    assert after_deferred["latest_attempt_trigger_id"] == "deferred-session"
    assert after_deferred["trigger_id"] == "autonomous-session"
    assert after_deferred["lifecycle_verified"] is True

    preserved = read_autonomous_receipt(
        data_dir,
        project_name="demo",
        project_root=project,
    )
    assert preserved is not None
    preserved["last_verified_completion"]["provider"] = None
    receipt_path.write_text(
        json.dumps(preserved, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    incomplete = inspect_autonomous_outcome(
        data_dir,
        project_name="demo",
        project_root=project,
        jobs=[stored],
    )
    assert incomplete["provider_metrics_bound"] is False
    assert incomplete["lifecycle_verified"] is False
    asyncio.run(backend.close())


def test_missing_summary_repair_uses_job_bound_note_after_identity_pruning(
    tmp_path: Path,
) -> None:
    from harness_mem.autonomous.worker import _repair_missing_notes
    from harness_mem.session_notes import materialize_session_note

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    notes_dir = tmp_path / "notes"
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="pruned-session",
                client="codex",
                raw_content="User: Preserve the historical topic.\nAssistant: Preserved.\n",
                content_type="transcript",
            ),
            project_name="demo",
            project_root=str(tmp_path / "project"),
            client="codex",
            session_id="pruned-session",
            source_kind="jsonl",
            source_uri="file:///pruned-session.jsonl",
            source_text="User: Preserve the historical topic.\nAssistant: Preserved.\n",
        )
    )
    assert snapshot.distill_job_id is not None
    queued = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert queued is not None
    original = queued.model_copy(
        update={
            "status": "completed",
            "phase": "done",
            "semantic_review": {
                "session_summary": (
                    "The immutable Note preserves the historical session topic."
                ),
                "final_user_request": "Preserve the historical topic.",
                "final_outcome": "The topic was preserved.",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
            },
            "completed_at": datetime.now(timezone.utc),
        }
    )
    backend.transcript_store._distill._upsert_job_locked(original)
    backend.transcript_store._conn.commit()
    materialize_session_note(original, notes_dir=notes_dir)
    pruned = original.model_copy(
        update={
            "project_root": "",
            "session_id": "",
            "semantic_review": {
                "session_summary": (
                    "The session topic could not be recovered from the available evidence."
                ),
                "last_turn_status": "answered",
                "evidence_status": "answered",
                "promotion_decision": "no_promotion",
                "evidence_state": "source_pruned",
            },
        }
    )
    backend.transcript_store._distill._upsert_job_locked(pruned)
    backend.transcript_store._conn.commit()

    _repair_missing_notes(
        backend,
        project_name="demo",
        project_root=tmp_path / "project",
        notes_dir=notes_dir,
    )

    repaired = backend.transcript_store.get_distill_job(original.id)
    assert repaired is not None
    assert repaired.semantic_review["session_summary"] == (
        "The immutable Note preserves the historical session topic."
    )
    asyncio.run(backend.close())


def test_missing_summary_repair_marks_pruned_job_without_note_unavailable(
    tmp_path: Path,
) -> None:
    from harness_mem.autonomous.worker import _repair_missing_notes

    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    snapshot = asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id="missing-note-session",
                client="codex",
                raw_content="User: transient task\nAssistant: done\n",
                content_type="transcript",
            ),
            project_name="demo",
            project_root=str(tmp_path / "project"),
            client="codex",
            session_id="missing-note-session",
            source_kind="jsonl",
            source_uri="file:///missing-note-session.jsonl",
            source_text="User: transient task\nAssistant: done\n",
        )
    )
    assert snapshot.distill_job_id is not None
    queued = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert queued is not None
    pruned = queued.model_copy(
        update={
            "status": "completed",
            "phase": "done",
            "project_root": "",
            "session_id": "",
            "semantic_review": {
                "session_summary": (
                    "The session topic could not be recovered from the available evidence."
                ),
                "last_turn_status": "answered",
                "evidence_status": "not_applicable",
                "promotion_decision": "no_promotion",
                "evidence_state": "source_pruned",
            },
            "completed_at": datetime.now(timezone.utc),
        }
    )
    backend.transcript_store._distill._upsert_job_locked(pruned)
    backend.transcript_store._conn.commit()

    _repair_missing_notes(
        backend,
        project_name="demo",
        project_root=tmp_path / "project",
        notes_dir=tmp_path / "notes",
    )

    repaired = backend.transcript_store.get_distill_job(pruned.id)
    assert repaired is not None
    assert repaired.semantic_review["historical_summary_status"] == "unavailable"
    assert repaired.semantic_review["historical_summary_reason"] == (
        "immutable_note_missing_after_source_pruned"
    )
    assert not (tmp_path / "notes" / ".md").exists()
    asyncio.run(backend.close())
