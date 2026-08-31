from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import logging
import os
from pathlib import Path

import pytest

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import (
    AssimilationDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.mcp import governance_handlers, tool_handlers
from harness_mem.mcp.distill_projection import (
    build_distill_compact_outline,
    build_distill_semantic_outline,
    render_distill_exchange_windows,
)
from harness_mem.mcp.response_budget import (
    attach_response_budget_receipt,
    serialized_result_tokens,
)
from harness_mem.qualification.distill_fixture_catalog import catalog_fingerprint, fixture
from harness_mem.qualification.distill_acceptance import (
    _decide_model_sample_with_retry,
    _duration_regression,
    _model_sample_status,
    _quality,
    _recover_prior_green_samples,
)
from harness_mem.session_notes import materialize_session_note
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import chunk_transcript_text


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
                        "reason": "The fixture source directly supports a reusable project point.",
                    }
                    for item in manifest["candidates"]
                ]
            }
        ),
        provider=self.name,
        model="deterministic",
        duration_seconds=0.01,
        input_sha256="e" * 64,
        response_sha256="f" * 64,
        input_tokens=20,
        output_tokens=10,
        total_tokens=30,
        event_count=1,
    )


def _assimilate_all_as_add(manifest: dict, *, provider: str) -> ProviderResult:
    points = [
        {
            "candidate_id": candidate["candidate_id"],
            "disposition": "add",
            "matched_truth_handles": [],
            "canonical_title": "Fixture memory",
            "canonical_statement": candidate["statement"],
            "topic_path": ["fixture"],
            "reason": "Deterministic fixture accepts the verified point.",
        }
        for candidate in manifest["verified_candidates"]
    ]
    return ProviderResult(
        decision=AssimilationDecision.model_validate({"points": points}),
        provider=provider,
        model="deterministic",
        duration_seconds=0.01,
        input_sha256="c" * 64,
        response_sha256="d" * 64,
        input_tokens=50,
        output_tokens=25,
        total_tokens=75,
        event_count=1,
        execution_mode="internal_http",
    )


def test_model_sample_cost_warning_is_not_reported_as_passed() -> None:
    assert (
        _model_sample_status(
            quality_passed=True,
            token_complete=True,
            warnings=["provider_duration_regressed_over_20pct"],
        )
        == "warning"
    )


def test_model_sample_quality_accepts_user_language_concept_terms() -> None:
    quality = _quality(
        "F3",
        {
            "semantic_review": {
                "session_summary": "用户确认了性能偏好，但测量工作尚未完成。",
                "final_user_request": "降低提炼开销并继续固定样本测量。",
                "final_outcome": "偏好已确认，测量仍待完成。",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["测量一个固定模型样本。"],
                "evidence_status": "partial",
                "promotion_decision": "partial",
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "性能偏好",
                    "content": "降低提炼延迟和令牌使用量，同时保持结果质量。",
                    "confidence": 0.99,
                    "tags": [],
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                }
            ],
        },
    )

    assert quality["checks"]["required_terms"] is True
    assert quality["passed"] is True


def test_model_sample_quality_accepts_rule_pattern_and_trigger() -> None:
    quality = _quality(
        "F3",
        {
            "semantic_review": {
                "session_summary": "性能偏好已确认，固定样本测量仍待完成。",
                "final_user_request": "降低提炼开销并继续固定样本测量。",
                "final_outcome": "偏好已确认，测量仍待完成。",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["测量一个固定模型样本。"],
                "evidence_status": "partial",
                "promotion_decision": "partial",
            },
            "candidates": [
                {
                    "kind": "rule",
                    "category": "性能偏好",
                    "pattern": "保持结果质量的同时降低提炼延迟和令牌使用量。",
                    "trigger": "设计或评估提炼流程时。",
                    "confidence": 0.99,
                    "tags": [],
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                }
            ],
        },
    )

    assert quality["checks"]["required_terms"] is True
    assert quality["passed"] is True


def test_model_sample_quality_filters_declared_handoff_control_state() -> None:
    quality = _quality(
        "F3",
        {
            "semantic_review": {
                "session_summary": "性能偏好已确认，测量仍待完成。",
                "final_user_request": "降低提炼开销并继续测量。",
                "final_outcome": "偏好保留，测量作为交接。",
                "last_turn_status": "unfinished",
                "contradictions": [],
                "unfinished_work": ["测量一个固定模型样本。"],
                "evidence_status": "partial",
                "promotion_decision": "partial",
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "性能偏好",
                    "content": "降低提炼延迟和令牌使用量，同时保持结果质量。",
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
            ],
        },
    )

    assert quality["passed"] is True
    assert quality["effective_candidate_count"] == 1
    assert quality["filtered_control_candidates"][0]["reason"] == (
        "unfinished work belongs to the job-bound handoff"
    )


def test_model_sample_quality_accepts_chinese_duration_synonym() -> None:
    quality = _quality(
        "F2",
        {
            "semantic_review": {
                "session_summary": "用户明确提出了长期有效的性能偏好。",
                "final_user_request": "降低蒸馏耗时和令牌使用。",
                "final_outcome": "该长期性能偏好已确认并记录。",
                "last_turn_status": "answered",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "answered",
                "promotion_decision": "promote",
            },
            "candidates": [
                {
                    "kind": "memory",
                    "category": "性能偏好",
                    "content": "减少耗时和令牌使用，同时保持结果质量。",
                    "confidence": 0.99,
                    "tags": [],
                    "evidence_basis": "user_statement",
                    "verification_outcome": "verified",
                    "verification_refs": [],
                    "verification_reason_codes": [],
                }
            ],
        },
    )

    assert quality["checks"]["required_terms"] is True
    assert quality["passed"] is True


def test_model_sample_retries_one_transient_provider_failure(tmp_path: Path) -> None:
    class _TransientThenGreen:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, manifest, *, runtime_dir):
            del manifest, runtime_dir
            self.calls += 1
            if self.calls == 1:
                raise ProviderError("timed out", kind="transient")
            return ProviderResult(
                decision=object(),  # type: ignore[arg-type]
                provider="test",
                model="test-model",
                duration_seconds=0.1,
                input_sha256="input",
                response_sha256="output",
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                event_count=1,
            )

    provider = _TransientThenGreen()
    result, failures = _decide_model_sample_with_retry(
        provider,
        {},
        runtime_dir=tmp_path,
    )

    assert provider.calls == 2
    assert result.attempt_count == 2
    assert failures == [{"kind": "transient", "message": "timed out"}]


def test_model_sample_does_not_retry_stable_provider_failure(tmp_path: Path) -> None:
    class _SetupFailure:
        def __init__(self) -> None:
            self.calls = 0

        def decide(self, manifest, *, runtime_dir):
            del manifest, runtime_dir
            self.calls += 1
            raise ProviderError("missing credentials", kind="setup_required")

    provider = _SetupFailure()
    with pytest.raises(ProviderError, match="missing credentials") as error:
        _decide_model_sample_with_retry(provider, {}, runtime_dir=tmp_path)

    assert provider.calls == 1
    assert error.value.attempt_count == 1
    assert error.value.attempt_errors == []


def test_model_baseline_is_recovered_from_prior_regression_receipt() -> None:
    recovered = _recover_prior_green_samples(
        {
            "samples": [
                {
                    "fixture_id": "F2",
                    "fixture_catalog": catalog_fingerprint(),
                    "provider": {
                        "model": "gpt-5.6-sol",
                        "total_tokens": 6000,
                        "duration_seconds": 18.0,
                    },
                    "regression": {
                        "baseline_available": True,
                        "token_delta_ratio": 0.2,
                        "duration_delta_ratio": 0.5,
                    },
                }
            ]
        }
    )

    assert recovered[0]["provider"] == {
        "model": "gpt-5.6-sol",
        "total_tokens": 5000,
        "duration_seconds": 12.0,
    }
    assert recovered[0]["baseline_recovered_from"] == (
        "prior_regression_receipt"
    )


def test_duration_regression_requires_three_samples_and_uses_median() -> None:
    early = _duration_regression(
        baseline_duration=10.0,
        recent_durations=[10.0, 14.0],
    )
    stable = _duration_regression(
        baseline_duration=10.0,
        recent_durations=[10.0, 14.0, 10.5],
    )
    regressed = _duration_regression(
        baseline_duration=10.0,
        recent_durations=[12.5, 14.0, 13.0],
    )

    assert early["duration_gate_ready"] is False
    assert stable["duration_gate_ready"] is True
    assert stable["duration_observed_seconds"] == 10.5
    assert stable["duration_delta_ratio"] == pytest.approx(0.05)
    assert regressed["duration_delta_ratio"] == pytest.approx(0.3)
    assert (
        _model_sample_status(
            quality_passed=True,
            token_complete=True,
            warnings=[],
        )
        == "passed"
    )


@contextmanager
def _bound(backend: LocalMemoryBackend):
    old_backend = tool_handlers._backend_provider
    old_observer = tool_handlers._observer_data_dir_provider
    old_budgets = tool_handlers._cost_surface_budgets_provider
    old_logger = tool_handlers.logger
    tool_handlers.configure_tool_handler_dependencies(
        backend_provider=lambda: backend,
        observer_data_dir=lambda: backend.data_dir,
        cost_surface_budgets=lambda _project_name: None,
        logger_instance=logging.getLogger("test.distill-acceptance"),
    )
    try:
        yield
    finally:
        if old_backend is None or old_observer is None or old_budgets is None:
            tool_handlers.reset_tool_handler_dependencies()
        else:
            tool_handlers.configure_tool_handler_dependencies(
                backend_provider=old_backend,
                observer_data_dir=old_observer,
                cost_surface_budgets=old_budgets,
                logger_instance=old_logger,
            )


def _snapshot(
    backend: LocalMemoryBackend,
    *,
    root: Path,
    fixture_id: str,
    project_name: str = "acceptance",
    session_id: str | None = None,
):
    transcript = str(fixture(fixture_id)["transcript"])
    selected_session = session_id or fixture_id
    return asyncio.run(
        persist_session_snapshot(
            backend,
            Observation(
                session_id=selected_session,
                client="codex",
                raw_content=transcript,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={},
            ),
            project_name=project_name,
            project_root=str(root),
            client="codex",
            session_id=selected_session,
            source_kind="jsonl",
            source_uri=f"file:///{selected_session}.jsonl",
            source_text=transcript,
        )
    )


def _prepare(
    backend: LocalMemoryBackend,
    *,
    root: Path,
    fixture_id: str,
    project_name: str = "acceptance",
):
    snapshot = _snapshot(
        backend,
        root=root,
        fixture_id=fixture_id,
        project_name=project_name,
    )
    packet = tool_handlers.tool_prepare_session_distill(
        project_name=project_name,
        project_root=str(root),
        client="codex",
        session_id=fixture_id,
        run_ingest=False,
        evidence_mode="semantic",
        detail_level="compact",
        budget_tokens=3000,
    )
    return snapshot, packet


def _preference_review(*, partial: bool = False) -> dict:
    return {
        "session_summary": (
            "The explicit performance preference was verified while one fixed "
            "measurement remained." if partial else
            "The explicit performance preference was verified and answered."
        ),
        "final_user_request": "Reduce time and tokens without reducing result quality.",
        "final_outcome": "The performance preference was retained.",
        "last_turn_status": "unfinished" if partial else "answered",
        "contradictions": (
            ["An older truncate-first approach was superseded."] if partial else []
        ),
        "unfinished_work": (
            ["Measure one fixed model sample next."] if partial else []
        ),
        "evidence_status": "partial" if partial else "answered",
        "promotion_decision": "partial" if partial else "promote",
    }


def _suggest_preference(
    snapshot,
    packet: dict,
    *,
    project_name: str = "acceptance",
) -> dict:
    ref = packet["zero_candidate_exchange_refs"][0]
    return governance_handlers.tool_suggest_memory_entry(
        project_name=project_name,
        category="preference",
        content="Use less time and fewer tokens without reducing distill result quality.",
        source=f"distill-job:{snapshot.distill_job_id}",
        confidence=0.99,
        tags=["performance", "distill"],
        distill_job_id=snapshot.distill_job_id,
        evidence_basis="user_statement",
        verification_outcome="verified",
        verification_refs=[
            {
                "kind": "user_statement",
                "exchange_index": ref["exchange_index"],
                "role": "user",
                "content_sha256": ref["content_sha256"],
            }
        ],
    )


def _zero_review(packet: dict) -> dict:
    template = dict(packet["zero_candidate_challenge_template"])
    template.update(
        {
            "evidence_fidelity": "complete",
            "future_utility": "none",
            "checks": {name: "absent" for name in template["checks"]},
            "conclusion": "no_durable_candidate",
            "rationale": "The complete fixture contains only a transient greeting with no future utility.",
        }
    )
    return {
        "session_summary": "The session returned a one-time greeting with no durable result.",
        "final_user_request": "Say hello once.",
        "final_outcome": "The one-time greeting was returned.",
        "last_turn_status": "answered",
        "contradictions": [],
        "unfinished_work": [],
        "evidence_status": "not_applicable",
        "promotion_decision": "no_promotion",
        "zero_candidate_challenge": template,
    }


def test_a1_compact_fixture_is_complete_and_honestly_budgeted() -> None:
    item = fixture("F5")
    compact, summary = build_distill_compact_outline(item["transcript"], budget_tokens=3000)
    payload = {"semantic_evidence": {"content": compact, **summary}}
    attach_response_budget_receipt(
        payload,
        requested_tokens=3000,
        evidence_tokens=summary["output_tokens"],
    )
    actual_tokens, tokenizer, actual_chars = serialized_result_tokens(payload)

    assert summary["exchange_count"] == 60
    assert compact.count("## E") == 60
    assert payload["response_budget"]["serialized_tokens"] == actual_tokens
    assert payload["response_budget"]["serialized_chars"] == actual_chars
    assert payload["response_budget"]["tokenizer"] == tokenizer
    assert payload["response_budget"]["hard_truncation_applied"] is False


def test_a2_full_and_compact_share_complete_exchange_coverage() -> None:
    transcript = fixture("F5")["transcript"]
    compact, compact_summary = build_distill_compact_outline(transcript, budget_tokens=3000)
    full, full_summary = build_distill_semantic_outline(transcript)

    assert compact_summary["exchange_count"] == full_summary["output_exchange_count"] == 60
    assert compact.count("## E") == full.count("## E") == 60
    assert len(full) > len(compact)
    assert compact_summary["detail_level"] == "compact"


def test_a3_drilldown_restores_begin_middle_end_and_rejects_out_of_range() -> None:
    item = fixture("F5")
    windows = render_distill_exchange_windows(
        item["transcript"], item["expected"]["anchor_indexes"]
    )

    assert [window["exchange_index"] for window in windows] == [1, 30, 60]
    for anchor, window in zip(item["expected"]["anchors"], windows, strict=True):
        assert anchor in window["content"]
    assert len(render_distill_exchange_windows(item["transcript"], list(range(1, 10)))) == 8
    assert render_distill_exchange_windows(item["transcript"], [999]) == []


def test_a4_raw_fixture_query_and_chunk_proof() -> None:
    item = fixture("F6")
    transcript = item["transcript"]
    chunks = chunk_transcript_text(
        transcript,
        source_id="F6-source",
        project_name="acceptance",
        client="codex",
        session_id="F6",
        max_chars=8000,
    )

    assert "".join(chunk.raw_content for chunk in chunks) == transcript
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    for chunk in chunks:
        assert hashlib.sha256(chunk.raw_content.encode("utf-8")).hexdigest() == chunk.content_sha256
    for proof in item["expected"]["proofs"]:
        assert any(proof in chunk.raw_content for chunk in chunks)
    assert not any("F6-NOT-PRESENT" in chunk.raw_content for chunk in chunks)


def test_b1_f2_user_preference_promotes_once_and_is_retrievable(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        with _bound(backend):
            snapshot, packet = _prepare(backend, root=tmp_path, fixture_id="F2")
            candidate = _suggest_preference(snapshot, packet)
            finalized = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=_preference_review(),
            )
        readable = asyncio.run(
            backend.structured_store.search_memory_entries(
                "tokens result quality", project_name="acceptance"
            )
        )
        assert finalized["promotion"]["promoted"] == 1
        assert [item.id for item in readable] == [candidate["entry_id"]]
    finally:
        asyncio.run(backend.close())


def test_b2_unbound_handoff_cannot_satisfy_job_gate(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        with _bound(backend):
            snapshot, packet = _prepare(backend, root=tmp_path, fixture_id="F3")
            governance_handlers.tool_create_task_handoff(
                project_name="acceptance",
                task_id="unbound",
                summary="This handoff is deliberately not job-bound.",
                status="in_progress",
                next_steps=["Do not accept this as the current job handoff."],
            )
            review = _preference_review(partial=True)
            review["zero_candidate_challenge"] = packet["zero_candidate_challenge_template"]
            finalized = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=review,
            )
        assert finalized["success"] is False
        assert finalized["error"] in {
            "zero_candidate_challenge_requires_candidate",
            "zero_candidate_signal_downgrade_unjustified",
        }
    finally:
        asyncio.run(backend.close())


def test_b2_autonomous_partial_creates_handoff_and_only_one_truth(
    tmp_path: Path, monkeypatch
) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    snapshot = _snapshot(backend, root=tmp_path, fixture_id="F3")
    job = backend.transcript_store.get_distill_job(snapshot.distill_job_id)
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.pending_distill_jobs",
        lambda *_args, **_kwargs: [],
    )

    class _PartialProvider:
        name = "partial-provider"
        verify = _verify_all_candidates

        def decide(self, manifest, *, runtime_dir, heartbeat=None):
            first, second = manifest["zero_candidate_exchange_refs"][:2]
            common = {
                "confidence": 0.99,
                "evidence_basis": "user_statement",
                "verification_outcome": "verified",
                "verification_reason_codes": [],
            }
            decision = AutonomousDecision.model_validate(
                {
                    "semantic_review": {
                        **_preference_review(partial=True),
                        "promotion_decision": "promote",
                        "zero_candidate_challenge": None,
                    },
                    "candidates": [
                        {
                            **common,
                            "kind": "memory",
                            "category": "preference",
                            "content": "Use lower latency and fewer tokens without reducing quality.",
                            "verification_refs": [
                                {
                                    "kind": "user_statement",
                                    "exchange_index": first["exchange_index"],
                                    "role": "user",
                                    "content_sha256": first["content_sha256"],
                                }
                            ],
                        },
                        {
                            **common,
                            "kind": "memory",
                            "category": "approach_decision",
                            "content": "The older truncate-first approach is superseded.",
                            "verification_refs": [
                                {
                                    "kind": "user_statement",
                                    "exchange_index": second["exchange_index"],
                                    "role": "user",
                                    "content_sha256": second["content_sha256"],
                                }
                            ],
                        },
                        {
                            **common,
                            "kind": "memory",
                            "category": "unfinished_handoff",
                            "content": "The next task remains unfinished.",
                            "verification_refs": [
                                {
                                    "kind": "user_statement",
                                    "exchange_index": second["exchange_index"],
                                    "role": "user",
                                    "content_sha256": second["content_sha256"],
                                }
                            ],
                        },
                    ],
                }
            )
            return ProviderResult(
                decision=decision,
                provider=self.name,
                model="deterministic",
                duration_seconds=0.01,
                input_sha256="a" * 64,
                response_sha256="b" * 64,
                input_tokens=500,
                output_tokens=100,
                total_tokens=600,
                event_count=1,
            )

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir, heartbeat
            return _assimilate_all_as_add(manifest, provider=self.name)

    try:
        result = run_autonomous_distill_batch(
            backend,
            project_name="acceptance",
            project_root=tmp_path,
            config=MergedConfig(dream_auto_enabled=False),
            trigger_id="F3",
            client="codex",
            provider=_PartialProvider(),
            notes_dir=tmp_path / "notes",
            max_jobs=1,
            preferred_job_id=job.id,
        )
        legacy_truths = asyncio.run(
            backend.structured_store.list_memory_entries("acceptance")
        )
        truths = asyncio.run(
            backend.structured_store.knowledge_store.list_entries("acceptance")
        )
        handoffs = asyncio.run(
            backend.structured_store.get_latest_handoffs("acceptance", limit=10)
        )
        stored = backend.transcript_store.get_distill_job(job.id)

        assert result["state"] == "succeeded", result
        assert len(truths) == 1
        assert legacy_truths == []
        assert len(handoffs) == 1
        assert handoffs[0].context["distill_job_id"] == job.id
        assert stored.semantic_review["promotion_decision"] == "partial"
        assert "dream" not in result["outcomes"][0]
    finally:
        asyncio.run(backend.close())


def test_b3_f1_zero_candidate_closes_without_pending_noise(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        with _bound(backend):
            snapshot, packet = _prepare(backend, root=tmp_path, fixture_id="F1")
            finalized = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=_zero_review(packet),
            )
        pending = asyncio.run(
            backend.structured_store.list_memory_entries(
                "acceptance", status="pending", limit=100
            )
        )
        assert finalized["completion"]["disposition"] == "no_candidate"
        assert pending == []
        assert Path(finalized["note"]["path"]).is_file()
    finally:
        asyncio.run(backend.close())


class _BatchProvider:
    name = "acceptance-provider"
    verify = _verify_all_candidates

    def decide(self, manifest, *, runtime_dir, heartbeat=None):
        session_id = manifest["session_id"]
        if session_id == "F-fail":
            raise ProviderError("fixture provider failure", kind="transient")
        refs = manifest["zero_candidate_exchange_refs"]
        if session_id == "F1":
            template = dict(manifest["zero_candidate_challenge_template"])
            template.update(
                {
                    "future_utility": "none",
                    "checks": {name: "absent" for name in template["checks"]},
                    "conclusion": "no_durable_candidate",
                    "rationale": "The complete fixture contains only a transient greeting with no durable value.",
                }
            )
            decision = {
                "semantic_review": {**_zero_review({"zero_candidate_challenge_template": template}), "zero_candidate_challenge": template},
                "candidates": [],
            }
        else:
            ref = refs[0]
            decision = {
                "semantic_review": {**_preference_review(), "zero_candidate_challenge": None},
                "candidates": [
                    {
                        "kind": "memory",
                        "category": "preference",
                        "content": "Use less time and fewer tokens without reducing distill result quality.",
                        "confidence": 0.99,
                        "tags": ["performance"],
                        "evidence_basis": "user_statement",
                        "verification_outcome": "verified",
                        "verification_refs": [
                            {
                                "kind": "user_statement",
                                "exchange_index": ref["exchange_index"],
                                "role": "user",
                                "content_sha256": ref["content_sha256"],
                            }
                        ],
                        "verification_reason_codes": [],
                    }
                ],
            }
        return ProviderResult(
            decision=AutonomousDecision.model_validate(decision),
            provider=self.name,
            model="deterministic",
            duration_seconds=0.01,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=500,
            output_tokens=100,
            total_tokens=600,
            event_count=1,
        )

    def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir, heartbeat
        return _assimilate_all_as_add(manifest, provider=self.name)


def _batch_setup(tmp_path: Path):
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    snapshots = [
        _snapshot(backend, root=tmp_path, fixture_id="F1"),
        _snapshot(backend, root=tmp_path, fixture_id="F2"),
        _snapshot(backend, root=tmp_path, fixture_id="F1", session_id="F-fail"),
    ]
    jobs = [backend.transcript_store.get_distill_job(item.distill_job_id) for item in snapshots]
    return backend, snapshots, jobs


def test_c2_three_job_batch_defers_only_failure_and_continues(
    tmp_path: Path, monkeypatch
) -> None:
    backend, snapshots, jobs = _batch_setup(tmp_path)
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.pending_distill_jobs",
        lambda *_args, **_kwargs: [jobs[1], jobs[2]],
    )
    try:
        result = run_autonomous_distill_batch(
            backend,
            project_name="acceptance",
            project_root=tmp_path,
            config=MergedConfig(dream_auto_enabled=False),
            trigger_id="F1",
            client="codex",
            provider=_BatchProvider(),
            notes_dir=tmp_path / "notes",
            max_jobs=3,
            preferred_job_id=snapshots[0].distill_job_id,
        )
        assert [item["session_id"] for item in result["outcomes"]] == ["F1", "F2", "F-fail"]
        assert [item["status"] for item in result["outcomes"]] == ["completed", "completed", "deferred"]
        assert result["state"] == "partial"
    finally:
        asyncio.run(backend.close())


def test_d2_assistant_role_cannot_impersonate_user_statement(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        with _bound(backend):
            snapshot, packet = _prepare(backend, root=tmp_path, fixture_id="F2")
            ref = packet["zero_candidate_exchange_refs"][0]
            candidate = governance_handlers.tool_suggest_memory_entry(
                project_name="acceptance",
                category="preference",
                content="Assistant text must not become a user preference.",
                source=f"distill-job:{snapshot.distill_job_id}",
                confidence=0.99,
                distill_job_id=snapshot.distill_job_id,
                evidence_basis="user_statement",
                verification_outcome="verified",
                verification_refs=[
                    {
                        "kind": "user_statement",
                        "exchange_index": ref["exchange_index"],
                        "role": "assistant",
                        "content_sha256": ref["content_sha256"],
                    }
                ],
            )
            finalized = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=_preference_review(),
            )
        stored = asyncio.run(
            backend.structured_store.get_memory_entry(candidate["entry_id"])
        )
        assert finalized["promotion"]["promoted"] == 0
        assert stored.status == "rejected"
    finally:
        asyncio.run(backend.close())


def test_e1_finalize_replay_keeps_note_hash_and_truth_count(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        with _bound(backend):
            snapshot, packet = _prepare(backend, root=tmp_path, fixture_id="F2")
            _suggest_preference(snapshot, packet)
            first = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=_preference_review(),
            )
            second = tool_handlers.tool_finalize_session_distill(
                project_name="acceptance",
                job_id=snapshot.distill_job_id,
                semantic_review=_preference_review(),
            )
        truths = asyncio.run(backend.structured_store.list_memory_entries("acceptance"))
        assert second["idempotent_replay"] is True
        assert first["completion"] == second["completion"]
        assert first["promotion"] == second["promotion"]
        assert first["note"]["path"] == second["note"]["path"]
        assert first["note"]["sha256"] == second["note"]["sha256"]
        assert len(truths) == 1
    finally:
        asyncio.run(backend.close())


def test_e3_provider_failure_has_no_note_and_next_job_continues(
    tmp_path: Path, monkeypatch
) -> None:
    backend, snapshots, jobs = _batch_setup(tmp_path)
    monkeypatch.setattr(
        "harness_mem.autonomous.worker.pending_distill_jobs",
        lambda *_args, **_kwargs: [jobs[2], jobs[1]],
    )
    try:
        result = run_autonomous_distill_batch(
            backend,
            project_name="acceptance",
            project_root=tmp_path,
            config=MergedConfig(dream_auto_enabled=False),
            trigger_id=None,
            client="codex",
            provider=_BatchProvider(),
            notes_dir=tmp_path / "notes",
            max_jobs=2,
        )
        assert [item["status"] for item in result["outcomes"]] == ["deferred", "completed"]
        assert not (tmp_path / "notes" / "F-fail.md").exists()
        assert (tmp_path / "notes" / "F2.md").is_file()
    finally:
        asyncio.run(backend.close())


def _completed_job(job_id: str, session_id: str, completed_at: datetime) -> SessionDistillJob:
    return SessionDistillJob(
        id=job_id,
        idempotency_key=job_id,
        project_name="acceptance",
        project_root="F:/acceptance",
        client="codex",
        session_id=session_id,
        source_id=f"source-{job_id}",
        source_revision="sha256:" + hashlib.sha256(job_id.encode()).hexdigest(),
        status="completed",
        phase="done",
        expected_chunk_count=1,
        completed_chunk_count=1,
        semantic_review={
            "session_summary": f"Completed {job_id} with a meaningful session result.",
            "final_outcome": f"{job_id} completed.",
            "unfinished_work": [],
        },
        completion_disposition="no_candidate",
        completed_at=completed_at,
    )


def test_e4_note_write_failure_never_advances_latest_and_retry_recovers(
    tmp_path: Path, monkeypatch
) -> None:
    notes = tmp_path / "notes"
    old = _completed_job("old-job", "growing", datetime.now(timezone.utc) - timedelta(minutes=5))
    new = _completed_job("new-job", "growing", datetime.now(timezone.utc))
    old_note = materialize_session_note(old, notes_dir=notes)
    old_latest = Path(old_note["latest_path"]).read_text(encoding="utf-8")
    real_replace = os.replace

    def fail_latest(source, destination):
        if Path(destination) == notes / "growing.md":
            raise OSError("injected latest write failure")
        return real_replace(source, destination)

    monkeypatch.setattr("harness_mem.session_notes.os.replace", fail_latest)
    with pytest.raises(OSError, match="injected"):
        materialize_session_note(new, notes_dir=notes)
    assert (notes / "growing.md").read_text(encoding="utf-8") == old_latest

    monkeypatch.setattr("harness_mem.session_notes.os.replace", real_replace)
    recovered = materialize_session_note(new, notes_dir=notes)
    assert Path(recovered["path"]).is_file()
    assert Path(recovered["latest_path"]).read_text(encoding="utf-8") == Path(
        recovered["path"]
    ).read_text(encoding="utf-8")


def test_e5_projects_isolate_sessions_candidates_handoffs_and_search(tmp_path: Path) -> None:
    backend = LocalMemoryBackend(tmp_path / "data")
    asyncio.run(backend.init())
    try:
        snap_a = _snapshot(backend, root=tmp_path / "a", fixture_id="F2", project_name="A")
        snap_b = _snapshot(backend, root=tmp_path / "b", fixture_id="F2", project_name="B")
        asyncio.run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="A",
                    category="decision",
                    content="PROJECT-A-ONLY distill decision",
                    confidence=1.0,
                    status="user_confirmed",
                    source="acceptance-fixture",
                )
            )
        )
        asyncio.run(
            backend.structured_store.save_task_handoff(
                TaskHandoff(
                    project_name="A",
                    task_id="A-only",
                    summary="PROJECT-A-ONLY handoff",
                )
            )
        )
        search_a = asyncio.run(
            backend.structured_store.search_memory_entries("PROJECT-A-ONLY", project_name="A")
        )
        search_b = asyncio.run(
            backend.structured_store.search_memory_entries("PROJECT-A-ONLY", project_name="B")
        )
        handoffs_b = asyncio.run(backend.structured_store.get_latest_handoffs("B"))
        jobs_a = backend.transcript_store.list_distill_jobs(project_name="A", limit=10)
        jobs_b = backend.transcript_store.list_distill_jobs(project_name="B", limit=10)

        assert snap_a.distill_job_id in {job.id for job in jobs_a}
        assert snap_a.distill_job_id not in {job.id for job in jobs_b}
        assert snap_b.distill_job_id in {job.id for job in jobs_b}
        assert len(search_a) == 1 and search_b == []
        assert handoffs_b == []
    finally:
        asyncio.run(backend.close())
