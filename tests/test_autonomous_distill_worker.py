from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.autonomous.worker import (
    _decide_with_candidate_retry,
    _normalize_zero_candidate_signal_labels,
    _preferred_job_is_eligible,
    autonomous_receipt_path,
    read_autonomous_receipt,
    run_autonomous_distill_batch,
)
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.observation import Observation
from harness_mem.outcome_probe import inspect_autonomous_outcome
from harness_mem.hook_receipts import record_hook_execution
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class _DeterministicProvider:
    name = "codex_exec"

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
    )

    assert result["state"] == "succeeded", result
    stored = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    assert stored is not None and stored.status == "completed"
    assert stored.review_execution_source == "autonomous_worker"
    assert stored.semantic_review["session_summary"].startswith("The user established")
    note_path = notes_dir / "autonomous-session.md"
    note = note_path.read_text(encoding="utf-8")
    assert stored.id in note
    assert "## 最终结果" in note
    assert "## 记忆治理结果" in note

    receipt = read_autonomous_receipt(
        data_dir,
        project_name="demo",
        project_root=project,
    )
    assert receipt is not None
    assert receipt["schema_version"] == 3
    assert receipt["hook_launch_verified"] is True
    assert receipt["hook_config_fingerprint"]
    assert receipt["last_semantic_success_at"]
    assert receipt["last_job_completed_at"]
    assert receipt["last_note_materialized_at"]
    assert receipt["provider"]["total_tokens"] == 1000
    job_receipt = receipt["batch"]["jobs"][0]
    assert job_receipt["job_id"] == stored.id
    assert job_receipt["selection_reason"] == "trigger_session"
    assert job_receipt["provider"]["total_tokens"] == 1000
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
    assert outcome["lifecycle_verified"] is True, outcome

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

    receipt["batch"]["jobs"][0]["provider"] = None
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
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
