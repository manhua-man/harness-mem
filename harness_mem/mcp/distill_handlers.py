"""Lossless session distillation MCP handlers.

This module owns evidence projection, chunk checkpointing, semantic review,
finalization, and bounded legacy fallback.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
import os
from pathlib import Path
from typing import Any, Mapping, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AssimilationDecision as ProviderAssimilationDecision,
)
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    SUPPORTED_INGEST_CLIENTS,
    normalize_client_name,
    resolve_project_context,
    resolve_host_source,
    resolve_ingest_client,
)
from harness_mem.commands.distill_lifecycle import distill_drainer_metrics
from harness_mem.commands.separated_assimilation import (
    apply_separated_assimilation,
    prepare_separated_assimilation,
    separated_job_candidate_ids,
    validate_separated_assimilation_decision,
)
from harness_mem.commands.evidence_admission import (
    answer_gate_status,
    evidence_summary_key,
)
from harness_mem.adapters.projection_repair import repair_source_observation_projection
from harness_mem.core.schemas.session_distill import (
    AssimilationPacketPoint,
    AnswerPacket,
    PromotedKnowledgeItem,
    SessionDistillJob,
    ZeroCandidateChallenge,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.session_notes import delete_session_notes, materialize_session_note
from harness_mem.transcript_chunking import sha256_text
from harness_mem.mcp.distill_projection import (
    DISTILL_INCREMENTAL_PROJECTION,
    build_append_aware_distill_projection,
    render_distill_exchange_windows,
    split_distill_semantic_content,
)
from harness_mem.mcp.response_budget import (
    attach_response_budget_receipt,
    distill_response_budget_hints,
    serialized_result_tokens,
)

from .handler_facade_proxy import tool_handlers_facade as _core


_SIGNAL_GATE_RECHECK_PIPELINE_VERSION = "lossless-distill-v1-signal-gate-v2"
_CURRENT_KNOWLEDGE_RECHECK_PIPELINE_VERSION = (
    "lossless-distill-v1-current-knowledge-v1"
)


def _session_notes_dir(backend: LocalMemoryBackend) -> Path:
    override = str(os.environ.get("HARNESS_MEM_SESSION_NOTES_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if Path(backend.data_dir).resolve() != DEFAULT_DATA_DIR.resolve():
        return Path(backend.data_dir) / "session_notes"
    return Path.home() / ".codex" / "hm-distill" / "sessions"


def _get_backend():
    return _core._get_backend()


def _ingest_sessions(*args, **kwargs):
    return _core._ingest_sessions(*args, **kwargs)


async def _recent_project_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int | None,
) -> list[Any]:
    observations = await backend.verbatim_store.list(limit=None)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    ordered = sorted(
        project_observations,
        key=lambda observation: (
            observation.timestamp or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )
    return ordered if limit is None else ordered[:limit]


# Deterministic semantic projections live in distill_projection.py.


def _with_complete_response_budget(handler):
    """Measure the complete handler result without clipping any evidence."""

    handler_signature = signature(handler)

    @wraps(handler)
    def wrapped(*args, **kwargs):
        result = handler(*args, **kwargs)
        if not isinstance(result, dict) or not bool(result.get("success")):
            return result
        bound = handler_signature.bind_partial(*args, **kwargs)
        requested_tokens = int(bound.arguments.get("budget_tokens") or 3000)
        evidence_tokens, outcome_hint, reason_hint = distill_response_budget_hints(
            result
        )
        return attach_response_budget_receipt(
            result,
            requested_tokens=requested_tokens,
            evidence_tokens=evidence_tokens,
            outcome_hint=outcome_hint,
            reason_hint=reason_hint,
        )

    return wrapped


def _load_distill_semantic_evidence(
    backend: LocalMemoryBackend,
    *,
    source_id: str,
    source_revision: str,
    detail_level: str,
    budget_tokens: int,
) -> dict[str, Any] | None:
    """Load the parser-derived user/assistant/tool rendering for a raw revision."""

    observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
    observation = asyncio.run(backend.verbatim_store.get(observation_id))
    if (
        observation is None
        or observation.metadata.get("source_revision") != source_revision
    ):
        observation = repair_source_observation_projection(
            backend,
            source_id=source_id,
            source_revision=source_revision,
        )
    if observation is None:
        return None

    parser_content = observation.raw_content
    revision = backend.transcript_store.get_revision(source_id, source_revision)
    if revision is None:
        return None
    source_bytes = backend.transcript_store.reconstruct_raw(
        source_id,
        source_revision=source_revision,
    )
    prior_projection = backend.transcript_store.get_latest_prior_distill_projection(
        source_id,
        source_revision,
        record_version=DISTILL_INCREMENTAL_PROJECTION,
    )
    prior_source_bytes: bytes | None = None
    if prior_projection is not None:
        prior_revision = str(prior_projection.get("source_revision") or "")
        try:
            prior_source_bytes = backend.transcript_store.reconstruct_raw(
                source_id,
                source_revision=prior_revision,
            )
        except (KeyError, ValueError):
            # A projection cache is disposable. Missing or invalid prior bytes
            # disable reuse; the current immutable revision still rebuilds in
            # full and remains the only evidence authority.
            prior_projection = None

    content, projection_summary, projection_lineage = (
        build_append_aware_distill_projection(
            parser_content,
            source_revision=source_revision,
            source_bytes=source_bytes,
            covered_sequence_count=revision.sequence_count,
            detail_level=detail_level,
            budget_tokens=budget_tokens,
            previous_projection=prior_projection,
            previous_source_bytes=prior_source_bytes,
        )
    )
    backend.transcript_store.save_distill_projection(
        {**projection_lineage, "source_id": source_id}
    )
    if detail_level == "full":
        projection_summary["budget_reason"] = (
            "caller explicitly requested complete semantic evidence"
        )
    source = backend.transcript_store.get_source(source_id)
    raw_char_count = sum(
        len(chunk.raw_content)
        for chunk in backend.transcript_store.list_chunks(
            source_id,
            source_revision=source_revision,
        )
    )
    semantic_char_count = len(content)
    semantic_chunks = split_distill_semantic_content(content)
    return {
        "mode": "semantic",
        "observation_id": observation_id,
        "source_id": source_id,
        "source_revision": source_revision,
        "client": source.client if source is not None else observation.client,
        "session_id": source.session_id
        if source is not None
        else observation.session_id,
        **projection_summary,
        "content_sha256": sha256_text(content),
        "raw_char_count": raw_char_count,
        "parser_render_char_count": len(parser_content),
        "semantic_char_count": semantic_char_count,
        "projection_reduction_ratio": round(
            semantic_char_count / len(parser_content), 4
        )
        if parser_content
        else 1.0,
        "reduction_ratio": round(semantic_char_count / raw_char_count, 4)
        if raw_char_count
        else 1.0,
        "semantic_chunk_count": len(semantic_chunks),
        "chunks": semantic_chunks,
    }


def _load_distill_exchange_windows(
    backend: LocalMemoryBackend,
    *,
    source_id: str,
    source_revision: str,
    indexes: list[int],
) -> list[dict[str, Any]]:
    observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
    observation = asyncio.run(backend.verbatim_store.get(observation_id))
    if (
        observation is None
        or observation.metadata.get("source_revision") != source_revision
    ):
        observation = repair_source_observation_projection(
            backend,
            source_id=source_id,
            source_revision=source_revision,
        )
    if observation is None:
        return []
    return render_distill_exchange_windows(observation.raw_content, indexes)


def _load_response_budgeted_semantic_evidence(
    backend: LocalMemoryBackend,
    *,
    source_id: str,
    source_revision: str,
    detail_level: str,
    requested_tokens: int,
    base_payload: dict[str, Any],
    response_fields: dict[str, Any],
) -> dict[str, Any] | None:
    """Allocate semantic detail from the measured complete response shell."""

    if detail_level == "full":
        return _load_distill_semantic_evidence(
            backend,
            source_id=source_id,
            source_revision=source_revision,
            detail_level=detail_level,
            budget_tokens=requested_tokens,
        )

    minimum = _load_distill_semantic_evidence(
        backend,
        source_id=source_id,
        source_revision=source_revision,
        detail_level=detail_level,
        budget_tokens=256,
    )
    if minimum is None:
        return None
    probe = {
        **base_payload,
        **response_fields,
        "semantic_evidence": minimum,
    }
    attach_response_budget_receipt(
        probe,
        requested_tokens=requested_tokens,
        evidence_tokens=int(minimum.get("output_tokens") or 0),
    )
    measured_tokens, _tokenizer, _chars = serialized_result_tokens(probe)
    protocol_tokens = max(
        0,
        measured_tokens - int(minimum.get("output_tokens") or 0),
    )
    evidence_target = max(256, requested_tokens - protocol_tokens)
    if evidence_target == 256:
        return minimum
    return _load_distill_semantic_evidence(
        backend,
        source_id=source_id,
        source_revision=source_revision,
        detail_level=detail_level,
        budget_tokens=evidence_target,
    )


def _attach_semantic_decision_bundle(
    backend: LocalMemoryBackend,
    *,
    payload: dict[str, Any],
    source_id: str,
    source_revision: str,
    semantic_evidence: dict[str, Any],
) -> None:
    """Bundle the bounded decision windows needed by the common fast path."""

    requested_indexes = [
        int(index)
        for index in semantic_evidence.get(
            "zero_candidate_required_exchange_indexes",
            [],
        )
        if int(index) >= 1
    ]
    windows = _load_distill_exchange_windows(
        backend,
        source_id=source_id,
        source_revision=source_revision,
        indexes=requested_indexes,
    )
    exchange_refs = [
        {
            "exchange_index": int(window["exchange_index"]),
            "content_sha256": str(window["content_sha256"]),
        }
        for window in windows
    ]
    check_names = (
        "user_correction",
        "explicit_decision",
        "successful_solution",
        "repeated_failure",
        "rule_or_preference",
        "reusable_workflow_or_fact",
        "version_or_migration",
        "unfinished_handoff",
    )
    signaled_checks = {
        str(reason)
        for reasons in semantic_evidence.get(
            "zero_candidate_required_exchange_reasons",
            {},
        ).values()
        for reason in reasons
    }
    detected_checks = signaled_checks & set(check_names)
    requires_candidate = bool(detected_checks)
    challenge_template = {
        "version": "v1",
        "source_revision": source_revision,
        "evidence_fidelity": "complete",
        "future_utility": "durable" if requires_candidate else "session_only",
        "checks": {
            name: "candidate_required" if name in detected_checks else "absent"
            for name in check_names
        },
        "inspected_exchange_refs": exchange_refs,
        "conclusion": (
            "candidate_required" if requires_candidate else "no_durable_candidate"
        ),
        "rationale": (
            "Detected memory-value signals require a scoped candidate or handoff."
            if requires_candidate
            else "Bundled decision exchanges contain no durable candidate after review."
        ),
    }
    payload.update(
        {
            "semantic_decision_exchanges": windows,
            "semantic_decision_exchange_count": len(windows),
            "zero_candidate_exchange_refs": exchange_refs,
            "zero_candidate_challenge_template": challenge_template,
            "agent_execution": {
                "contract_version": "agent-distill-fast-path-v1",
                "path": "prepare_then_finalize",
                "target_mcp_calls": 2,
                "completed_mcp_calls": 1,
                "next_tool": "finalize_session_distill",
                "additional_prepare_required": False,
                "additional_prepare_allowed_when": [
                    "candidate_needs_raw_proof",
                    "legacy_raw_fallback",
                ],
            },
        }
    )


def _checkpoint_distill_structural_projection(
    backend: LocalMemoryBackend,
    *,
    job_id: str,
    source_revision: str,
    semantic_content_sha256: str,
) -> Any:
    """Checkpoint raw chunks after runtime validation for semantic fast mode."""

    while True:
        job = backend.transcript_store.get_distill_job(job_id)
        if job is None:
            raise KeyError(job_id)
        if job.status == "reviewing":
            return job
        lease_owner = f"mcp-distill-semantic:{uuid4()}"
        claims = backend.transcript_store.claim_distill_chunks(
            job_id,
            lease_owner=lease_owner,
            limit=256,
        )
        if not claims:
            return job
        for chunk, _checkpoint in claims:
            if sha256_text(chunk.raw_content) != chunk.content_sha256:
                raise ValueError(f"distill input chunk hash mismatch: {chunk.id}")
            backend.transcript_store.checkpoint_distill_chunk(
                job_id,
                chunk.id,
                lease_owner=lease_owner,
                result={
                    "evidence_mode": "semantic",
                    "structural_verified": True,
                    "chunk_index": chunk.chunk_index,
                    "content_sha256": chunk.content_sha256,
                    "source_revision": source_revision,
                    "semantic_content_sha256": semantic_content_sha256,
                },
            )


@_with_complete_response_budget
def tool_prepare_session_distill(
    project_name: str | None = None,
    client: str = "auto",
    limit: int | None = None,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
    observation_limit: int | None = None,
    chunk_limit: int | None = None,
    evidence_mode: str = "semantic",
    detail_level: str = "compact",
    budget_tokens: int = 3000,
    drilldown_exchange_indexes: list[int] | None = None,
    drilldown_chunk_indexes: list[int] | None = None,
    drilldown_query: str | None = None,
    run_ingest: bool = True,
    defer_job_id: str | None = None,
    defer_reason: str | None = None,
    session_id: str | None = None,
    distill_job_id: str | None = None,
    _distill_source: str = "agent",
) -> dict:
    """Prepare a compact evidence packet for an AI-led remember request.

    This intentionally stops before synthesis. The model should read the
    returned observations, decide what deserves a pending candidate, then call
    govern_memory(action=suggest). The lower-level sync step may call ingest_sessions, but
    The single hm entry is the user-facing flow.
    """
    normalized_client = normalize_client_name(client)
    if normalized_client not in SUPPORTED_INGEST_CLIENTS:
        return {
            "success": False,
            "error": "client must be one of: auto, agent, claude-code, codex, codex-archive, cursor, grok, antigravity, opencode, hermes",
        }
    if scope not in {"project", "all"}:
        return {"success": False, "error": "scope must be one of: project, all"}
    if evidence_mode not in {"raw", "semantic"}:
        return {
            "success": False,
            "error": "evidence_mode must be one of: raw, semantic",
        }
    if detail_level not in {"compact", "full"}:
        return {
            "success": False,
            "error": "detail_level must be one of: compact, full",
        }
    resolved_budget_tokens = max(256, int(budget_tokens or 3000))
    requested_exchange_indexes = sorted(
        {int(index) for index in (drilldown_exchange_indexes or []) if int(index) >= 1}
    )
    requested_drilldown_indexes = sorted(
        {int(index) for index in (drilldown_chunk_indexes or []) if int(index) >= 0}
    )
    requested_drilldown_query = str(drilldown_query or "").strip()[:200]
    requested_session_id = str(session_id or "").strip() or None
    requested_job_id = str(distill_job_id or "").strip() or None
    host_source = resolve_host_source(normalized_client)
    project_context = resolve_project_context(
        project_name,
        project_root=project_root,
        required=True,
        action_label="MCP prepare_session_distill",
    )
    if project_context is None:
        return {
            "success": False,
            "error": (
                "project_name could not be resolved. Pass project_name, pass "
                "project_root, run from a workspace directory, or set an active project."
            ),
        }
    resolved_project_name = project_context.project_name
    resolved_project_root = (
        str(project_context.project_root)
        if project_context.project_root is not None
        else project_root
    )

    effective_limit = None if limit is None else max(1, int(limit))
    effective_observation_limit = (
        None if observation_limit is None else max(0, int(observation_limit))
    )

    ingest_payload: dict[str, Any] = {
        "success": True,
        "skipped": True,
        "reason": "run_ingest=false",
    }
    if run_ingest:
        ingest_payload = _ingest_sessions(
            project_name=resolved_project_name,
            client=normalized_client,
            limit=effective_limit,
            full_rescan=full_rescan,
            scope=scope,
            project_root=resolved_project_root,
            session_id=requested_session_id,
        )

    backend = _get_backend()
    deferred_id: str | None = None
    if defer_job_id:
        deferred = backend.transcript_store.get_distill_job(defer_job_id)
        if deferred is None or deferred.project_name != resolved_project_name:
            return {
                "success": False,
                "error": "defer_job_id does not belong to this project",
            }
        backend.transcript_store.defer_distill_job(
            defer_job_id,
            error=(defer_reason or "Agent deferred a failed distill job"),
        )
        deferred_id = defer_job_id
    if requested_job_id and requested_job_id == deferred_id:
        return {
            "success": False,
            "error": "distill_job_id cannot be the job deferred by the same call",
            "distill_job_id": requested_job_id,
        }
    # Explicit recovery must observe durable checkpoints before lane selection.
    # Do not run the crash reconciler during an ordinary multi-call raw read:
    # between calls a healthy interactive job has completed checkpoints but no
    # active chunk lease, which is not evidence that its worker crashed.
    if requested_session_id or requested_job_id:
        backend.transcript_store.reconcile_distill_jobs(
            project_name=resolved_project_name,
            recovery_budget=3,
        )
    if requested_session_id:
        matching_jobs = [
            job
            for job in backend.transcript_store.list_distill_jobs(
                project_name=resolved_project_name,
                limit=100_000,
            )
            if job.session_id == requested_session_id
        ]
        if not matching_jobs:
            return {
                "success": False,
                "error": "session_id is not available for this project",
                "session_id": requested_session_id,
            }
        session_job = max(
            matching_jobs,
            key=lambda item: (item.created_at, item.updated_at),
        )
        recheck_pipeline: str | None = None
        if requested_job_id is None:
            if _completed_job_requires_signal_gate_recheck(session_job):
                recheck_pipeline = _SIGNAL_GATE_RECHECK_PIPELINE_VERSION
            elif (
                session_job.pipeline_version
                != _CURRENT_KNOWLEDGE_RECHECK_PIPELINE_VERSION
                and asyncio.run(
                    _completed_promotion_result_error(backend, job=session_job)
                )
                is not None
            ):
                recheck_pipeline = _CURRENT_KNOWLEDGE_RECHECK_PIPELINE_VERSION
        if recheck_pipeline is not None:
            session_job = backend.transcript_store.enqueue_distill_job(
                session_job.source_id,
                pipeline_version=recheck_pipeline,
            )
        if requested_job_id and requested_job_id != session_job.id:
            return {
                "success": False,
                "error": "session_id and distill_job_id refer to different jobs",
                "session_id": requested_session_id,
                "distill_job_id": requested_job_id,
            }
        requested_job_id = session_job.id
    requested_job = (
        backend.transcript_store.get_distill_job(requested_job_id)
        if requested_job_id
        else None
    )
    if requested_job_id and (
        requested_job is None or requested_job.project_name != resolved_project_name
    ):
        return {
            "success": False,
            "error": "distill_job_id does not belong to this project",
            "distill_job_id": requested_job_id,
        }
    if requested_job and requested_job.status == "completed":
        current_result_error = asyncio.run(
            _completed_promotion_result_error(backend, job=requested_job)
        )
        if current_result_error is not None:
            return {
                "success": False,
                "project_name": resolved_project_name,
                "project_root": resolved_project_root,
                "session_id": requested_job.session_id,
                "distill_job_id": requested_job.id,
                "selection_source": (
                    "explicit_session" if requested_session_id else "explicit"
                ),
                "distill_status": requested_job.status,
                "error": "completed result is not present in current knowledge",
                "reason_codes": [current_result_error],
            }
        source_cleanup = _replay_completed_source_cleanup(
            backend,
            job=requested_job,
        )
        return {
            "success": True,
            "project_name": resolved_project_name,
            "project_root": resolved_project_root,
            "session_id": requested_job.session_id,
            "distill_job_id": requested_job.id,
            "selection_source": (
                "explicit_session" if requested_session_id else "explicit"
            ),
            "distill_status": requested_job.status,
            "completion": {
                "disposition": requested_job.completion_disposition,
                "reason_codes": requested_job.completion_reason_codes,
            },
            "session_summary": _session_summary_payload(requested_job),
            "promotion": dict(requested_job.promotion_summary),
            "source_cleanup": source_cleanup,
            "agent_execution": {
                "contract_version": "agent-distill-fast-path-v1",
                "path": "already_completed",
                "target_mcp_calls": 1,
                "completed_mcp_calls": 1,
                "next_tool": None,
                "additional_prepare_required": False,
            },
        }
    explicitly_activated = bool(requested_job and requested_job.status == "parked")
    if requested_job_id and explicitly_activated:
        requested_job = backend.transcript_store.activate_parked_distill_job_for_agent(
            requested_job_id,
        )
    elif requested_session_id and requested_job_id:
        backend.transcript_store.mark_distill_jobs_agent_offered(
            resolved_project_name,
            [requested_job_id],
        )
        requested_job = backend.transcript_store.get_distill_job(requested_job_id)
    lossless_jobs = []
    for job_status in ("processing", "queued", "retryable", "reviewing"):
        lossless_jobs.extend(
            backend.transcript_store.list_distill_jobs(
                project_name=resolved_project_name,
                status=job_status,
            )
        )
    if deferred_id:
        lossless_jobs = [job for job in lossless_jobs if job.id != deferred_id]
    now = datetime.now(timezone.utc)
    lossless_jobs = [
        job
        for job in lossless_jobs
        if job.status != "retryable"
        or job.retry_after is None
        or job.retry_after <= now
    ]
    if requested_job_id and not any(
        job.id == requested_job_id for job in lossless_jobs
    ):
        return {
            "success": False,
            "error": "distill_job_id is not currently eligible for Agent processing",
            "distill_job_id": requested_job_id,
            "distill_status": requested_job.status if requested_job else None,
            "retry_after": (
                requested_job.retry_after.isoformat()
                if requested_job and requested_job.retry_after
                else None
            ),
        }
    if lossless_jobs:
        # Automatic selection is recent-first: one malformed historical
        # session cannot head-of-line block every newer task. Old work is
        # still reached once the recent lane is drained.
        status_priority = {"reviewing": 4, "processing": 3, "queued": 2, "retryable": 1}
        lossless_job = (
            next(job for job in lossless_jobs if job.id == requested_job_id)
            if requested_job_id
            else max(
                lossless_jobs,
                key=lambda item: (status_priority.get(item.status, 0), item.created_at),
            )
        )
        base_payload: dict[str, Any] = {
            "success": True,
            "project_name": resolved_project_name,
            "project_root": resolved_project_root,
            "project_resolution_source": project_context.source,
            "client": normalized_client,
            "resolved_client": resolve_ingest_client(normalized_client),
            "host_client": host_source.host_client,
            "source_kind": host_source.source_kind,
            "adapter_available": host_source.adapter_available,
            "scope": scope,
            "limit": effective_limit,
            "ingest": ingest_payload,
            "distill_mode": "lossless_chunks",
            "distill_job_id": lossless_job.id,
            "session_id": lossless_job.session_id,
            "selection_source": (
                "explicit_session_parked"
                if requested_session_id and explicitly_activated
                else "explicit_session"
                if requested_session_id
                else "explicit_parked"
                if explicitly_activated
                else "explicit"
                if requested_job_id
                else "queue_policy"
            ),
            "distill_status": lossless_job.status,
            "source_id": lossless_job.source_id,
            "source_revision": lossless_job.source_revision,
            "expected_chunk_count": lossless_job.expected_chunk_count,
            "completed_chunk_count": lossless_job.completed_chunk_count,
            "evidence_mode": evidence_mode,
            "detail_level": detail_level,
            "budget_tokens": resolved_budget_tokens,
            "zero_candidate_challenge_version": (
                lossless_job.zero_candidate_challenge_version
            ),
        }
        if _distill_source == "ide_hook":
            base_payload.update(
                {
                    "chunks": [],
                    "chunk_count": 0,
                    "distill_instructions": [
                        "Evidence was synchronized and queued without claiming Agent work.",
                        "Consume this job the next time an Agent uses hm.",
                    ],
                }
            )
            return base_payload
        if lossless_job.status == "reviewing":
            if requested_exchange_indexes:
                semantic_windows = _load_distill_exchange_windows(
                    backend,
                    source_id=lossless_job.source_id,
                    source_revision=lossless_job.source_revision,
                    indexes=requested_exchange_indexes,
                )
                base_payload.update(
                    {
                        "semantic_drilldown_exchanges": semantic_windows,
                        "semantic_drilldown_exchange_count": len(semantic_windows),
                        "distill_instructions": [
                            "Use these complete semantic windows to choose precise raw proof queries.",
                            "For a zero-candidate challenge, return each required exchange_index and content_sha256.",
                            "Verify durable candidates against raw chunks before final review.",
                        ],
                    }
                )
                if not requested_drilldown_indexes and not requested_drilldown_query:
                    return base_payload
            if requested_drilldown_indexes or requested_drilldown_query:
                raw_chunks = backend.transcript_store.list_chunks(
                    lossless_job.source_id,
                    source_revision=lossless_job.source_revision,
                )
                chunks_by_index = {chunk.chunk_index: chunk for chunk in raw_chunks}
                selected_by_index = {
                    index: chunks_by_index[index]
                    for index in requested_drilldown_indexes
                    if index in chunks_by_index
                }
                if requested_drilldown_query:
                    query_folded = requested_drilldown_query.casefold()
                    query_terms = [
                        term for term in query_folded.split() if len(term) >= 2
                    ]
                    exact_matches = [
                        chunk
                        for chunk in raw_chunks
                        if query_folded in chunk.raw_content.casefold()
                    ]
                    query_matches = exact_matches or [
                        chunk
                        for chunk in raw_chunks
                        if query_terms
                        and all(
                            term in chunk.raw_content.casefold() for term in query_terms
                        )
                    ]
                    for chunk in query_matches:
                        selected_by_index.setdefault(chunk.chunk_index, chunk)
                selected_chunks = [
                    selected_by_index[index] for index in sorted(selected_by_index)
                ]
                base_payload.update(
                    {
                        "raw_drilldown_chunks": [
                            {
                                "chunk_id": chunk.id,
                                "chunk_index": chunk.chunk_index,
                                "char_start": chunk.char_start,
                                "char_end": chunk.char_end,
                                "content_sha256": chunk.content_sha256,
                                "raw_content": chunk.raw_content,
                            }
                            for chunk in selected_chunks
                        ],
                        "raw_drilldown_chunk_count": len(selected_chunks),
                        "raw_drilldown_query": requested_drilldown_query or None,
                        "distill_instructions": [
                            "Use these read-only raw chunks to verify candidate evidence.",
                            "Do not submit them again; structural checkpoints are already complete.",
                            "Finish with finalize_session_distill after semantic review.",
                        ],
                    }
                )
                return base_payload
            if evidence_mode == "semantic":
                checkpoints = backend.transcript_store.list_distill_checkpoints(
                    lossless_job.id
                )
                structurally_verified = sum(
                    bool(checkpoint.result.get("structural_verified"))
                    for checkpoint in checkpoints
                )
                distill_instructions = [
                    "Read the complete indexed semantic outline in order.",
                    "Runtime already hash-verified and checkpointed every raw chunk.",
                    "Use the bundled semantic_decision_exchanges for the final decision.",
                    "Do not call prepare again unless a durable candidate needs precise raw proof.",
                    "If no candidates remain, verify and reuse zero_candidate_challenge_template in finalization.",
                    "Create only warranted candidates through govern_memory(action=suggest), then call finalize_session_distill.",
                ]
                response_fields = {
                    "chunks": [],
                    "chunk_count": 0,
                    "structural_checkpoint_summary": {
                        "expected": lossless_job.expected_chunk_count,
                        "completed": lossless_job.completed_chunk_count,
                        "runtime_verified": structurally_verified,
                    },
                    "distill_instructions": distill_instructions,
                }
                semantic_evidence = _load_response_budgeted_semantic_evidence(
                    backend,
                    source_id=lossless_job.source_id,
                    source_revision=lossless_job.source_revision,
                    detail_level=detail_level,
                    requested_tokens=resolved_budget_tokens,
                    base_payload=base_payload,
                    response_fields=response_fields,
                )
                if semantic_evidence is not None:
                    lossless_job = (
                        backend.transcript_store.enable_zero_candidate_challenge(
                            lossless_job.id
                        )
                    )
                    base_payload["zero_candidate_challenge_version"] = (
                        lossless_job.zero_candidate_challenge_version
                    )
                    base_payload.update(
                        {**response_fields, "semantic_evidence": semantic_evidence}
                    )
                    _attach_semantic_decision_bundle(
                        backend,
                        payload=base_payload,
                        source_id=lossless_job.source_id,
                        source_revision=lossless_job.source_revision,
                        semantic_evidence=semantic_evidence,
                    )
                    return base_payload
                base_payload.update(
                    {
                        "evidence_mode": "raw",
                        "evidence_mode_fallback_reason": (
                            "current semantic observation is unavailable or stale"
                        ),
                    }
                )
            checkpoints = backend.transcript_store.list_distill_checkpoints(
                lossless_job.id
            )
            base_payload.update(
                {
                    "chunks": [],
                    "chunk_count": 0,
                    "chunk_results": [
                        {
                            "chunk_id": checkpoint.chunk_id,
                            "chunk_index": checkpoint.chunk_index,
                            "result": checkpoint.result,
                        }
                        for checkpoint in checkpoints
                    ],
                    "distill_instructions": [
                        "Review all chunk results as one complete session in order.",
                        "Identify final outcome, contradictions, unfinished work, and evidence strength.",
                        "Create only warranted candidates and pass this distill_job_id to every govern_memory action=suggest call.",
                        "Finish with finalize_session_distill; it runs auto-review and Dream.",
                    ],
                }
            )
            return base_payload
        if evidence_mode == "semantic":
            distill_instructions = [
                "Read the complete indexed semantic outline in order.",
                "Runtime already hash-verified and checkpointed every raw chunk.",
                "Use the bundled semantic_decision_exchanges for the final decision.",
                "Do not call prepare again unless a durable candidate needs precise raw proof.",
                "If no candidates remain, verify and reuse zero_candidate_challenge_template in finalization.",
                "Create only warranted candidates, then call finalize_session_distill.",
            ]
            response_fields = {
                "distill_status": "reviewing",
                "completed_chunk_count": lossless_job.expected_chunk_count,
                "chunks": [],
                "chunk_count": 0,
                "structural_checkpoint_summary": {
                    "expected": lossless_job.expected_chunk_count,
                    "completed": lossless_job.expected_chunk_count,
                    "runtime_verified": lossless_job.expected_chunk_count,
                },
                "distill_instructions": distill_instructions,
            }
            semantic_evidence = _load_response_budgeted_semantic_evidence(
                backend,
                source_id=lossless_job.source_id,
                source_revision=lossless_job.source_revision,
                detail_level=detail_level,
                requested_tokens=resolved_budget_tokens,
                base_payload=base_payload,
                response_fields=response_fields,
            )
            if semantic_evidence is not None:
                lossless_job = backend.transcript_store.enable_zero_candidate_challenge(
                    lossless_job.id
                )
                base_payload["zero_candidate_challenge_version"] = (
                    lossless_job.zero_candidate_challenge_version
                )
                updated_job = _checkpoint_distill_structural_projection(
                    backend,
                    job_id=lossless_job.id,
                    source_revision=lossless_job.source_revision,
                    semantic_content_sha256=semantic_evidence["content_sha256"],
                )
                if updated_job.status == "reviewing":
                    response_fields["distill_status"] = updated_job.status
                    response_fields["completed_chunk_count"] = (
                        updated_job.completed_chunk_count
                    )
                    response_fields["structural_checkpoint_summary"] = {
                        "expected": updated_job.expected_chunk_count,
                        "completed": updated_job.completed_chunk_count,
                        "runtime_verified": updated_job.completed_chunk_count,
                    }
                    base_payload.update(
                        {**response_fields, "semantic_evidence": semantic_evidence}
                    )
                    _attach_semantic_decision_bundle(
                        backend,
                        payload=base_payload,
                        source_id=lossless_job.source_id,
                        source_revision=lossless_job.source_revision,
                        semantic_evidence=semantic_evidence,
                    )
                    return base_payload
                base_payload.update(
                    {
                        "evidence_mode": "raw",
                        "evidence_mode_fallback_reason": (
                            "active raw chunk leases prevented semantic fast-path checkpointing"
                        ),
                    }
                )
            else:
                base_payload.update(
                    {
                        "evidence_mode": "raw",
                        "evidence_mode_fallback_reason": (
                            "current semantic observation is unavailable or stale"
                        ),
                    }
                )
        lease_owner = f"mcp-distill:{uuid4()}"
        claims = backend.transcript_store.claim_distill_chunks(
            lossless_job.id,
            lease_owner=lease_owner,
            limit=None if chunk_limit is None else max(1, int(chunk_limit)),
        )
        base_payload.update(
            {
                "lease_owner": lease_owner if claims else None,
                "chunks": [
                    {
                        "chunk_id": chunk.id,
                        "chunk_index": chunk.chunk_index,
                        "char_start": chunk.char_start,
                        "char_end": chunk.char_end,
                        "content_sha256": chunk.content_sha256,
                        "raw_content": chunk.raw_content,
                    }
                    for chunk, _checkpoint in claims
                ],
                "chunk_count": len(claims),
                "distill_instructions": [
                    "Read every returned chunk completely and in chunk_index order.",
                    "Submit one structured result per chunk with submit_distill_chunk.",
                    "Then call prepare_session_distill again for the next chunk or final review.",
                    "Do not create final memory candidates until the job enters reviewing state.",
                ],
            }
        )
        return base_payload

    observations = asyncio.run(
        _recent_project_observations(
            backend,
            project_name=resolved_project_name,
            limit=effective_observation_limit,
        )
    )
    packet_observations = []
    for observation in observations:
        packet_observations.append(
            {
                "source": f"observation:{observation.id}",
                "id": observation.id,
                "session_id": observation.session_id,
                "client": observation.client,
                "content_type": observation.content_type,
                "timestamp": observation.timestamp.isoformat()
                if observation.timestamp
                else None,
                "tags": observation.tags,
                "metadata": observation.metadata,
                "raw_content": observation.raw_content,
                "packet_truncated": False,
                "source_coverage": observation.metadata.get(
                    "source_coverage",
                    "legacy_partial",
                ),
            }
        )

    return {
        "success": bool(packet_observations) or bool(ingest_payload.get("success")),
        "project_name": resolved_project_name,
        "project_root": resolved_project_root,
        "project_resolution_source": project_context.source,
        "client": normalized_client,
        "resolved_client": resolve_ingest_client(normalized_client),
        "host_client": host_source.host_client,
        "source_kind": host_source.source_kind,
        "adapter_available": host_source.adapter_available,
        "scope": scope,
        "limit": effective_limit,
        "ingest": ingest_payload,
        "observation_limit": effective_observation_limit,
        "observations": packet_observations,
        "observation_count": len(packet_observations),
        "distill_mode": "legacy_partial",
        "distill_job_id": None,
        "distill_status": "not_queued",
        "coverage": "legacy_partial",
        "distill_instructions": [
            "No complete native transcript revision is available for these legacy observations.",
            "Treat them as a searchable audit view, not as complete lossless session evidence.",
            "Do not claim the session was completely read, automatically summarized, or eligible for automatic promotion.",
            "When the native transcript is available, synchronize it to create a lossless distill job instead.",
        ],
    }


def tool_submit_distill_chunk(
    job_id: str,
    chunk_id: str,
    lease_owner: str,
    result: dict,
) -> dict:
    """Checkpoint one fully read transcript chunk under its active lease."""

    backend = _get_backend()
    job = backend.transcript_store.checkpoint_distill_chunk(
        job_id,
        chunk_id,
        lease_owner=lease_owner,
        result=result,
    )
    return {
        "success": True,
        "distill_job_id": job.id,
        "distill_status": job.status,
        "distill_phase": job.phase,
        "completed_chunk_count": job.completed_chunk_count,
        "expected_chunk_count": job.expected_chunk_count,
        "next_action": (
            "call prepare_session_distill for final review"
            if job.status == "reviewing"
            else "call prepare_session_distill for the next chunk"
        ),
    }


def _session_summary_payload(job: SessionDistillJob) -> dict[str, Any]:
    """Return the human-readable result independently from memory promotion."""

    review = dict(job.semantic_review or {})
    final_request = str(review.get("final_user_request") or "").strip()
    final_outcome = str(review.get("final_outcome") or "").strip()
    summary = str(review.get("session_summary") or "").strip()
    if not summary:
        summary = final_request
        if final_outcome and final_outcome != final_request:
            summary = f"{summary}; outcome: {final_outcome}" if summary else final_outcome
    return {
        "session_id": job.session_id,
        "summary": summary,
        "final_outcome": final_outcome,
        "last_turn_status": review.get("last_turn_status", "unknown"),
        "unfinished_work": list(review.get("unfinished_work") or []),
        "memory_disposition": job.completion_disposition,
    }


async def _distill_candidates(
    backend: LocalMemoryBackend, candidate_ids: list[str]
) -> list[Any]:
    candidates: list[Any] = []
    for candidate_id in candidate_ids:
        candidate: Any = await backend.structured_store.get_memory_entry(candidate_id)
        if candidate is None:
            candidate = await backend.structured_store.get_rule_candidate(candidate_id)
        if candidate is None:
            candidate = await backend.structured_store.get_relation_fact(candidate_id)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


async def _interactive_assimilation_plan(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Turn explicit Agent proposals into the normal separated write plan.

    The interactive Agent already decides what each admitted point means.  The
    local runtime still revalidates its evidence, resolves any named current
    target from the bounded SQLite view, and applies the same validator used by
    the autonomous worker.  A missing decision is an incomplete review, never
    permission to promote a legacy ``MemoryEntry`` status.
    """

    prepared = await prepare_separated_assimilation(
        backend,
        project_name=project_name,
        project_root=project_root,
        candidate_ids=candidate_ids,
    )
    handle_by_truth_id = {
        truth_id: handle for handle, truth_id in prepared.truth_by_handle.items()
    }
    points: list[dict[str, Any]] = []
    for candidate_id in prepared.eligible_candidate_ids:
        separated = await backend.structured_store.knowledge_store.get_candidate(
            candidate_id
        )
        if separated is None:
            raise ValueError("interactive candidate is no longer readable")
        disposition = str(
            separated.assimilation_disposition or ""
        ).strip()
        if disposition not in {
            "add",
            "refine",
            "confirm",
            "replace",
            "no_write",
            "handoff",
            "defer",
            "conflict",
            "reject",
        }:
            raise ValueError(
                "interactive candidate is missing a valid assimilation decision"
            )
        reason = str(separated.assimilation_reason or "").strip()
        if len(reason) < 8:
            raise ValueError("interactive candidate decision needs a concrete reason")

        target_ids = [
            str(value).strip()
            for value in separated.assimilation_target_ids
            if str(value).strip()
        ]
        matched_handles: list[str] = []
        if disposition in {"confirm", "refine", "replace"}:
            if disposition == "confirm" and len(target_ids) != 1:
                raise ValueError("interactive confirm requires one current target")
            if not target_ids:
                raise ValueError(
                    f"interactive {disposition} requires a current project target"
                )
            for target_id in target_ids:
                handle = handle_by_truth_id.get(target_id)
                if handle is None:
                    raise ValueError(
                        "interactive candidate target is not current project knowledge"
                    )
                matched_handles.append(handle)
        elif disposition == "conflict" and target_ids:
            if len(target_ids) > 1:
                raise ValueError("interactive conflict may name one current target")
            handle = handle_by_truth_id.get(target_ids[0])
            if handle is None:
                raise ValueError(
                    "interactive candidate conflict target is not current project knowledge"
                )
            matched_handles = [handle]
        elif target_ids:
            raise ValueError(
                f"interactive {disposition} candidate must not name a current target"
            )

        knowledge_items: list[dict[str, Any]] = []
        if disposition in {"add", "refine", "replace"}:
            title = str(separated.canonical_title or "").strip()
            topic_path = [
                str(part).strip()
                for part in separated.topic_path
                if str(part).strip()
            ]
            if not title or not topic_path:
                raise ValueError(
                    "interactive writing candidate needs a title and project module"
                )
            evidence = await backend.structured_store.knowledge_store.list_evidence(
                candidate_id
            )
            basis = evidence[0].evidence_basis if len(evidence) == 1 else None
            claim_kind = (
                "procedure"
                if separated.candidate_type == "rule"
                else "durable_preference"
                if basis == "user_statement"
                else "implementation_fact"
            )
            knowledge_items = [
                {
                    "title": title,
                    "statement": separated.statement,
                    "topic_path": topic_path,
                    "claim_kind": claim_kind,
                }
            ]
        points.append(
            {
                "candidate_id": candidate_id,
                "disposition": disposition,
                "matched_truth_handles": matched_handles,
                "knowledge_items": knowledge_items,
                "reason": reason,
            }
        )

    decision = ProviderAssimilationDecision.model_validate({"points": points})
    return validate_separated_assimilation_decision(prepared, decision)


def _aggregate_answer_status(
    candidates: list[Any], *, promoted_count: int
) -> str:
    """Derive one session-level status from runtime-validated candidate gates."""

    if not candidates:
        return "NOT_APPLICABLE"
    statuses = [answer_gate_status(candidate) for candidate in candidates]
    if len(set(statuses)) == 1:
        return statuses[0]
    if "ANSWERED" in statuses or promoted_count:
        return "PARTIAL"
    for status in ("STALE", "CONTRADICTED", "PARTIAL", "UNANSWERED"):
        if status in statuses:
            return status
    return "NOT_APPLICABLE"


async def _build_answer_packet(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
    candidate_ids: list[str],
    promotion_counts: Mapping[str, Any],
    runtime_reviewed: bool,
) -> dict[str, Any]:
    """Build the formal packet only from runtime-governed candidate state."""

    if _uses_separated_assimilation(job.semantic_review):
        raw_point_results = promotion_counts.get("points")
        separated_point_results = (
            [dict(item) for item in raw_point_results if isinstance(item, dict)]
            if isinstance(raw_point_results, list)
            else []
        )
        candidates, items = await _separated_answer_packet_state(
            backend,
            candidate_ids=candidate_ids,
            project_name=job.project_name,
            project_root=job.project_root,
            point_results=separated_point_results,
        )
    else:
        candidates, _ignored_items = await _separated_answer_packet_state(
            backend,
            candidate_ids=candidate_ids,
            project_name=job.project_name,
            project_root=job.project_root,
            point_results=[],
        )
        if not candidates:
            candidates = await _distill_candidates(backend, candidate_ids)
        # Compatibility rows can explain an old receipt, but never populate
        # current user-visible knowledge.
        items = []
    promoted_count = (
        int(promotion_counts.get("promoted") or 0)
        if _uses_separated_assimilation(job.semantic_review)
        else 0
    )
    suggested_count = int(promotion_counts.get("suggested") or 0)
    promotion_status = (
        "promoted"
        if promoted_count and promoted_count == suggested_count
        else "partial" if promoted_count else "not_promoted"
    )
    status = (
        _aggregate_answer_status(candidates, promoted_count=promoted_count)
        if runtime_reviewed
        else "UNANSWERED" if candidates else "NOT_APPLICABLE"
    )
    review = dict(job.semantic_review or {})
    question = str(review.get("final_user_request") or "").strip()
    if not question:
        question = "本次会话最终要解决什么问题？"
    if len(items) == 1:
        conclusion = items[0].fact
    elif items:
        conclusion = f"已验证并写入 {len(items)} 条长期记忆，具体内容见下方列表。"
    elif status == "NOT_APPLICABLE":
        conclusion = "本次会话没有需要写入的长期记忆。"
    elif status in {"PARTIAL", "UNANSWERED"}:
        conclusion = "现有证据不足以形成长期记忆，本次未写入。"
    elif status in {"CONTRADICTED", "STALE"}:
        conclusion = "候选证据存在冲突或已失效，本次未写入长期记忆。"
    else:
        conclusion = str(review.get("final_outcome") or "候选未通过晋升策略。").strip()
    bases = sorted(
        {
            str(getattr(candidate, "evidence_basis", "") or "")
            for candidate in candidates
            if getattr(candidate, "evidence_basis", None)
        }
    )
    verified_values = [
        candidate.verified_at
        for candidate in candidates
        if runtime_reviewed and getattr(candidate, "verified_at", None) is not None
    ]
    raw_point_results = promotion_counts.get("points")
    point_results: list[dict[str, Any]] = (
        [item for item in raw_point_results if isinstance(item, dict)]
        if isinstance(raw_point_results, list)
        else []
    )
    return AnswerPacket(
        answer_status=cast(Any, status),
        question=question,
        core_conclusion=conclusion,
        evidence_basis=bases,
        verified_at=max(verified_values) if verified_values else None,
        promotion_status=cast(Any, promotion_status),
        promoted_items=items,
        destination_project=job.project_name,
        knowledge_kind=list(dict.fromkeys(item.kind for item in items)),
        knowledge_category=list(dict.fromkeys(item.category for item in items)),
        point_results=[
            AssimilationPacketPoint(
                candidate_id=str(item.get("candidate_id") or ""),
                answer_status=cast(Any, item.get("answer_status") or "UNANSWERED"),
                disposition=str(item.get("disposition") or "reject"),
                canonical_truth_ids=[
                    str(value) for value in item.get("canonical_truth_ids") or []
                ],
                handoff_id=(
                    str(item["handoff_id"])
                    if item.get("handoff_id") is not None
                    else None
                ),
            )
            for item in point_results
            if str(item.get("candidate_id") or "")
        ],
    ).to_dict()


async def _separated_answer_packet_state(
    backend: LocalMemoryBackend,
    *,
    candidate_ids: list[str],
    project_name: str,
    project_root: str,
    point_results: list[dict[str, Any]],
) -> tuple[list[Any], list[PromotedKnowledgeItem]]:
    """Build the human packet from job results and SQLite current knowledge."""

    from types import SimpleNamespace

    store = backend.structured_store.knowledge_store
    candidates: list[Any] = []
    items: list[PromotedKnowledgeItem] = []
    seen_entry_ids: set[str] = set()
    result_by_candidate = {
        str(item.get("candidate_id") or ""): item for item in point_results
    }
    for candidate_id in candidate_ids:
        candidate = await store.get_candidate(candidate_id)
        if candidate is None:
            continue
        evidence_rows = await store.list_evidence(candidate.id)
        evidence = evidence_rows[0] if len(evidence_rows) == 1 else None
        point_result = dict(result_by_candidate.get(candidate.id) or {})
        truth_ids = [
            str(entry_id)
            for entry_id in point_result.get("canonical_truth_ids") or []
        ]
        candidates.append(
            SimpleNamespace(
                status="auto_confirmed" if truth_ids else candidate.status,
                evidence_basis=evidence.evidence_basis if evidence else None,
                verification_outcome=(
                    evidence.verification_outcome if evidence else "unverified"
                ),
                verification_reason_codes=(
                    list(evidence.verification_reason_codes) if evidence else []
                ),
                verification_refs=(list(evidence.verification_refs) if evidence else []),
                verified_at=evidence.verified_at if evidence else None,
            )
        )
        for entry_id in truth_ids:
            if entry_id in seen_entry_ids:
                continue
            entry = await store.get_entry(
                entry_id,
                project_name=project_name,
                project_root=project_root,
            )
            if entry is None:
                continue
            seen_entry_ids.add(entry_id)
            items.append(
                PromotedKnowledgeItem(
                    title=entry.title,
                    fact=entry.statement,
                    kind="knowledge",
                    category=entry.module_path[-1],
                )
            )
    return candidates, items


async def _separated_evidence_summary(
    backend: LocalMemoryBackend,
    *,
    candidate_ids: list[str],
) -> tuple[dict[str, int], dict[str, int]]:
    """Summarize the runtime-revalidated evidence used by current knowledge."""

    admission = {
        "repository_verified": 0,
        "user_stated": 0,
        "unverified_blocked": 0,
        "contradicted": 0,
        "legacy_or_unknown": 0,
    }
    gate = {
        "ANSWERED": 0,
        "PARTIAL": 0,
        "UNANSWERED": 0,
        "CONTRADICTED": 0,
        "STALE": 0,
        "NOT_APPLICABLE": 0,
    }
    store = backend.structured_store.knowledge_store
    for candidate_id in candidate_ids:
        evidence_rows = await store.list_evidence(candidate_id)
        if len(evidence_rows) != 1:
            admission["legacy_or_unknown"] += 1
            gate["UNANSWERED"] += 1
            continue
        evidence = evidence_rows[0]
        admission[evidence_summary_key(evidence)] += 1
        gate[answer_gate_status(evidence)] += 1
    return admission, gate


def _uses_separated_assimilation(review: Mapping[str, Any] | None) -> bool:
    payload = dict(review or {})
    plan = payload.get("assimilation")
    return isinstance(plan, dict) and plan.get("version") == "separated-v1"


async def _promotion_commit_error(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    promotion_summary: Mapping[str, Any],
) -> str | None:
    """Require every reported write to be current and readable before success."""

    promoted = int(promotion_summary.get("promoted") or 0)
    if promoted <= 0:
        return None
    raw_points = promotion_summary.get("points")
    if not isinstance(raw_points, list):
        return "promotion_points_missing"
    writing_points = [
        item
        for item in raw_points
        if isinstance(item, Mapping)
        and str(item.get("disposition") or "") in {"add", "refine", "replace"}
    ]
    if len(writing_points) != promoted:
        return "promotion_count_mismatch"
    store = backend.structured_store.knowledge_store
    from harness_mem.read_knowledge import search_current_knowledge

    for point in writing_points:
        truth_ids = [
            str(value) for value in point.get("canonical_truth_ids") or [] if value
        ]
        if not truth_ids:
            return "promotion_write_missing"
        for truth_id in truth_ids:
            entry = await store.get_entry(truth_id, project_name=project_name)
            if entry is None:
                return "promotion_write_unreadable"
            results = await search_current_knowledge(
                backend,
                project_name=project_name,
                query=entry.statement,
                limit=100000,
            )
            if not any(item.id == truth_id for item in results):
                return "promotion_write_unreadable"
    return None


async def _completed_promotion_result_error(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
) -> str | None:
    """Reject a completed write claim that current knowledge cannot prove."""

    if job.status != "completed":
        return None
    promotion = dict(job.promotion_summary or {})
    if job.completion_disposition != "promoted" and int(
        promotion.get("promoted") or 0
    ) <= 0:
        return None
    result_error = _candidate_result_error(
        candidate_ids=list(job.output_candidate_ids),
        promotion_summary=promotion,
    )
    if result_error is not None:
        return result_error
    return await _promotion_commit_error(
        backend,
        project_name=job.project_name,
        promotion_summary=promotion,
    )


def _candidate_result_error(
    *,
    candidate_ids: list[str],
    promotion_summary: Mapping[str, Any],
) -> str | None:
    """Require complete non-pending coverage before completion.

    One extracted candidate may legitimately split into several current
    knowledge items or several point decisions.  Completion therefore checks
    that every candidate appears at least once, rather than requiring a
    one-to-one candidate/result mapping.
    """

    if int(promotion_summary.get("missing") or 0) != 0:
        return "assimilation_candidate_missing"
    if int(promotion_summary.get("pending") or 0) != 0:
        return "assimilation_candidate_pending"
    if int(promotion_summary.get("suggested") or 0) != len(candidate_ids):
        return "assimilation_candidate_count_mismatch"
    raw_points = promotion_summary.get("points")
    points = raw_points if isinstance(raw_points, list) else []
    result_ids = [
        str(item.get("candidate_id") or "")
        for item in points
        if isinstance(item, Mapping)
    ]
    if set(result_ids) != set(candidate_ids):
        return "assimilation_candidate_results_incomplete"
    if any(
        str(item.get("disposition") or "") in {"handoff", "defer", "conflict"}
        and not str(item.get("handoff_id") or "").strip()
        for item in points
        if isinstance(item, Mapping)
    ):
        return "assimilation_unfinished_point_missing_handoff"
    return None


def _trusted_assimilation_preflight(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
    review_lease_owner: str,
) -> list[str]:
    """Recheck the trusted review boundary before any current-truth write."""

    current = backend.transcript_store.get_distill_job(job.id)
    now = datetime.now(timezone.utc)
    if current is None or current.status != "reviewing":
        return ["distill_review_not_ready"]
    if current.review_lease_owner != review_lease_owner:
        return ["review_lease_not_owned"]
    if current.review_lease_until is None or current.review_lease_until <= now:
        return ["review_lease_expired"]
    # Atomically extend the owned lease before crossing into the separate
    # canonical-truth transaction.  This is the commit claim: another worker
    # cannot take ownership while the bounded local mutation and job finalize
    # run, and a changed/expired lease fails before any truth write.
    if not backend.transcript_store.renew_distill_review_lease(
        current.id,
        lease_owner=review_lease_owner,
    ):
        return ["review_lease_commit_claim_failed"]
    current = backend.transcript_store.get_distill_job(current.id)
    if current is None:
        return ["distill_review_not_ready"]
    source = backend.transcript_store.get_source(current.source_id)
    if source is None:
        return ["distill_source_missing"]
    if source.source_revision != current.source_revision:
        return ["source_revision_changed"]
    checkpoints = backend.transcript_store.list_distill_checkpoints(current.id)
    if (
        len(checkpoints) != current.expected_chunk_count
        or any(item.status != "completed" for item in checkpoints)
    ):
        return ["distill_chunks_incomplete"]
    try:
        backend.transcript_store.reconstruct(
            current.source_id,
            source_revision=current.source_revision,
        )
    except (KeyError, ValueError):
        return ["source_content_address_invalid"]

    # Re-read the compare-and-swap inputs after reconstruction. This catches a
    # source revision or lease change that raced the content-address check.
    confirmed = backend.transcript_store.get_distill_job(current.id)
    confirmed_source = backend.transcript_store.get_source(current.source_id)
    if confirmed is None or confirmed_source is None:
        return ["distill_source_missing"]
    if (
        confirmed.status != "reviewing"
        or confirmed.review_lease_owner != review_lease_owner
        or confirmed.review_lease_until is None
        or confirmed.review_lease_until <= datetime.now(timezone.utc)
    ):
        return ["review_lease_changed"]
    if (
        confirmed.source_revision != current.source_revision
        or confirmed_source.source_revision != current.source_revision
    ):
        return ["source_revision_changed"]
    return []


def tool_finalize_session_distill(
    project_name: str,
    job_id: str,
    semantic_review: dict,
    _review_lease_owner: str | None = None,
) -> dict:
    """Validate, write current knowledge, and finalize one explicit job."""

    backend = _get_backend()
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None:
        return {
            "success": False,
            "error": "distill job not found",
            "distill_job_id": job_id,
        }
    if job.project_name != project_name:
        return {"success": False, "error": "distill job belongs to another project"}
    recovering_completion = (
        job.status == "completed" and job.completion_disposition is None
    )
    if job.status == "completed" and not recovering_completion:
        current_result_error = asyncio.run(
            _completed_promotion_result_error(backend, job=job)
        )
        if current_result_error is not None:
            return {
                "success": False,
                "project_name": project_name,
                "distill_job_id": job.id,
                "distill_status": job.status,
                "error": "completed result is not present in current knowledge",
                "reason_codes": [current_result_error],
            }
        queue = distill_drainer_metrics(
            backend,
            project_name=project_name,
        )
        answer_packet = dict(job.promotion_summary.get("answer_packet") or {})
        if not answer_packet:
            answer_packet = asyncio.run(
                _build_answer_packet(
                    backend,
                    job=job,
                    candidate_ids=list(job.output_candidate_ids),
                    promotion_counts=dict(job.promotion_summary),
                    runtime_reviewed=_semantic_review_allows_candidate_review(
                        job.semantic_review
                    ),
                )
            )
            job = backend.transcript_store.record_distill_completion_outcome(
                job.id,
                disposition=job.completion_disposition,
                reason_codes=list(job.completion_reason_codes),
                promotion_summary={
                    **dict(job.promotion_summary),
                    "answer_packet": answer_packet,
                },
                source_cleanup_status=job.source_cleanup_status or "retained",
                source_cleanup_receipt_id=job.source_cleanup_receipt_id,
            )
        note = materialize_session_note(job, notes_dir=_session_notes_dir(backend))
        asyncio.run(backend.structured_store.knowledge_store.cleanup_job(job.id))
        source_cleanup = _replay_completed_source_cleanup(backend, job=job)
        return {
            "success": True,
            "idempotent_replay": True,
            "project_name": project_name,
            "distill_job_id": job.id,
            "distill_status": job.status,
            "structural_audit": job.structural_audit,
            "semantic_review": job.semantic_review,
            "session_summary": _session_summary_payload(job),
            "completion": {
                "disposition": job.completion_disposition,
                "reason_codes": job.completion_reason_codes,
            },
            "promotion": dict(job.promotion_summary),
            "answer_packet": answer_packet,
            "queue_effect": {
                "removed_from_pending": True,
                "pending_total_after": queue["pending_total"],
            },
            "source_cleanup": source_cleanup,
            "note": note,
        }
    supplied_assimilation = semantic_review.get("assimilation")
    if (
        isinstance(supplied_assimilation, dict)
        and supplied_assimilation.get("version") == "v1"
    ):
        return {
            "success": False,
            "project_name": project_name,
            "distill_job_id": job.id,
            "distill_status": job.status,
            "error": "legacy assimilation does not write current project knowledge",
            "reason_codes": ["legacy_assimilation_retired"],
        }
    if isinstance(supplied_assimilation, dict) and not _review_lease_owner:
        return {
            "success": False,
            "project_name": project_name,
            "distill_job_id": job.id,
            "distill_status": job.status,
            "error": "trusted_review_lease_required",
            "reason_codes": ["unleased_assimilation_rejected"],
        }
    if recovering_completion:
        candidate_ids = list(job.output_candidate_ids)
        completed = job
        prefinalized_assimilation: dict[str, Any] | None = None
    else:
        prefinalized_assimilation = None
        interactive_lease = False
        checkpoints = backend.transcript_store.list_distill_checkpoints(job.id)
        completed_checkpoints = sum(
            item.status == "completed" for item in checkpoints
        )
        if completed_checkpoints != job.expected_chunk_count:
            raise ValueError("not all distill chunks are complete")
        if isinstance(supplied_assimilation, dict) and supplied_assimilation.get(
            "version"
        ) == "separated-v1":
            candidate_ids = list(supplied_assimilation.get("candidate_ids") or [])
            actual_candidate_ids = asyncio.run(
                separated_job_candidate_ids(
                    backend,
                    project_name=project_name,
                    distill_job_id=job_id,
                    include_candidate_ids=candidate_ids,
                )
            )
            if (
                not candidate_ids
                or len(candidate_ids) != len(set(candidate_ids))
                or set(candidate_ids) != set(actual_candidate_ids)
            ):
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "separated_assimilation_candidate_binding_invalid",
                    "reason_codes": ["separated_candidate_job_binding_invalid"],
                }
        else:
            candidate_ids = asyncio.run(
                separated_job_candidate_ids(
                    backend,
                    project_name=project_name,
                    distill_job_id=job_id,
                )
            )
        handoff_ids = asyncio.run(
            _distill_job_handoff_ids(
                backend,
                project_name=project_name,
                distill_job_id=job_id,
            )
        )
        challenge_error = _validate_zero_candidate_challenge(
            backend,
            job=job,
            semantic_review=semantic_review,
            candidate_ids=candidate_ids,
            handoff_ids=handoff_ids,
        )
        if challenge_error is not None:
            return {
                "success": False,
                "project_name": project_name,
                "distill_job_id": job.id,
                "distill_status": job.status,
                **challenge_error,
            }
        if _review_lease_owner is None:
            lease_owner = f"interactive:{uuid4()}"
            claimed = backend.transcript_store.claim_distill_review(
                job_id,
                lease_owner=lease_owner,
                execution_source="interactive_agent",
            )
            if claimed is None:
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "distill review is already running",
                    "reason_codes": ["review_already_owned"],
                }
            _review_lease_owner = lease_owner
            interactive_lease = True
        if (
            not isinstance(supplied_assimilation, dict)
            and candidate_ids
            and _semantic_review_allows_candidate_review(semantic_review)
        ):
            try:
                supplied_assimilation = asyncio.run(
                    _interactive_assimilation_plan(
                        backend,
                        project_name=project_name,
                        project_root=job.project_root,
                        candidate_ids=candidate_ids,
                    )
                )
            except (TypeError, ValueError, ValidationError) as exc:
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(
                        job_id,
                        lease_owner=_review_lease_owner,
                    )
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": str(exc),
                    "reason_codes": ["interactive_assimilation_incomplete"],
                }
            semantic_review = {
                **semantic_review,
                "assimilation": supplied_assimilation,
            }
        if _uses_separated_assimilation(semantic_review):
            # Revalidate the source and save current knowledge before the job
            # can become completed. A failed write therefore leaves the job
            # available for retry instead of creating a false completion.
            assert _review_lease_owner is not None
            preflight_reason_codes = _trusted_assimilation_preflight(
                backend,
                job=job,
                review_lease_owner=_review_lease_owner,
            )
            if preflight_reason_codes:
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(
                        job_id,
                        lease_owner=_review_lease_owner,
                    )
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "trusted_assimilation_precondition_failed",
                    "reason_codes": preflight_reason_codes,
                }
            try:
                prefinalized_assimilation = asyncio.run(
                    apply_separated_assimilation(
                        backend,
                        project_name=project_name,
                        project_root=job.project_root,
                        candidate_ids=candidate_ids,
                        plan=semantic_review["assimilation"],
                    )
                )
            except (RuntimeError, TypeError, ValueError) as exc:
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(
                        job_id,
                        lease_owner=_review_lease_owner,
                    )
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "current knowledge was not saved",
                    "reason_codes": [str(exc)],
                }
        else:
            prefinalized_assimilation = asyncio.run(
                _settle_distill_candidates(
                    backend,
                    project_name=project_name,
                    candidate_ids=candidate_ids,
                )
            )
        if prefinalized_assimilation is not None:
            result_error = _candidate_result_error(
                candidate_ids=candidate_ids,
                promotion_summary=prefinalized_assimilation,
            )
            if result_error is not None:
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(
                        job_id,
                        lease_owner=_review_lease_owner,
                    )
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "every candidate needs an explicit non-pending result",
                    "reason_codes": [result_error],
                }
            commit_error = asyncio.run(
                _promotion_commit_error(
                    backend,
                    project_name=project_name,
                    promotion_summary=prefinalized_assimilation,
                )
            )
            if commit_error is not None:
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(
                        job_id,
                        lease_owner=_review_lease_owner,
                    )
                return {
                    "success": False,
                    "project_name": project_name,
                    "distill_job_id": job.id,
                    "distill_status": job.status,
                    "error": "current knowledge was not saved",
                    "reason_codes": [commit_error],
                }
        handoff_ids = asyncio.run(
            _distill_job_handoff_ids(
                backend,
                project_name=project_name,
                distill_job_id=job_id,
            )
        )
        try:
            completed = backend.transcript_store.finalize_distill_job(
                job_id,
                semantic_review=semantic_review,
                output_candidate_ids=candidate_ids,
                review_lease_owner=_review_lease_owner,
            )
        except Exception:
            if interactive_lease:
                backend.transcript_store.release_distill_review_lease(
                    job_id,
                    lease_owner=_review_lease_owner,
                )
            raise
    payload: dict[str, Any] = {
        "success": completed.status == "completed",
        "project_name": project_name,
        "distill_job_id": completed.id,
        "distill_status": completed.status,
        "structural_audit": completed.structural_audit,
        "semantic_review": completed.semantic_review,
    }
    if not recovering_completion:
        payload["handoff_ids"] = handoff_ids
    if recovering_completion:
        payload["idempotent_replay"] = True
        payload["completion_recovered"] = True
    if completed.status != "completed":
        payload["error"] = completed.error
        return payload
    semantic_allows_candidate_review = _semantic_review_allows_candidate_review(
        completed.semantic_review
    )
    evidence_admission = {
        "repository_verified": 0,
        "user_stated": 0,
        "unverified_blocked": 0,
        "contradicted": 0,
        "legacy_or_unknown": 0,
    }
    answer_gate = {
        "ANSWERED": 0,
        "PARTIAL": 0,
        "UNANSWERED": 0,
        "CONTRADICTED": 0,
        "STALE": 0,
        "NOT_APPLICABLE": 0,
    }
    assimilation_plan = completed.semantic_review.get("assimilation")
    assimilation_summary: dict[str, Any] | None = None
    if (
        isinstance(assimilation_plan, dict)
        and assimilation_plan.get("version") == "separated-v1"
    ):
        assimilation_summary = prefinalized_assimilation
        if assimilation_summary is None:
            assimilation_summary = asyncio.run(
                apply_separated_assimilation(
                    backend,
                    project_name=project_name,
                    project_root=completed.project_root,
                    candidate_ids=candidate_ids,
                    plan=assimilation_plan,
                )
            )
        payload["auto_review"] = {
            "skipped": True,
            "reason": "separated_autonomous_assimilation_applied",
            "candidate_ids": candidate_ids,
        }
    elif semantic_allows_candidate_review:
        assimilation_summary = prefinalized_assimilation
        payload["auto_review"] = {
            "skipped": True,
            "reason": "current_knowledge_assimilation_required",
            "candidate_ids": candidate_ids,
        }
    else:
        assimilation_summary = prefinalized_assimilation
        payload["auto_review"] = {
            "skipped": True,
            "reason": "semantic_review_blocks_candidate_review",
            "candidate_ids": candidate_ids,
        }
    if assimilation_summary is None:
        assimilation_summary = asyncio.run(
            _settle_distill_candidates(
                backend,
                project_name=project_name,
                candidate_ids=candidate_ids,
            )
        )
    result_error = _candidate_result_error(
        candidate_ids=candidate_ids,
        promotion_summary=assimilation_summary,
    )
    if result_error is not None:
        return {
            **payload,
            "success": False,
            "error": "every candidate needs an explicit non-pending result",
            "reason_codes": [result_error],
        }
    commit_error = asyncio.run(
        _promotion_commit_error(
            backend,
            project_name=project_name,
            promotion_summary=assimilation_summary,
        )
    )
    if commit_error is not None:
        return {
            **payload,
            "success": False,
            "error": "current knowledge was not saved",
            "reason_codes": [commit_error],
        }
    promotion_counts = assimilation_summary
    evidence_admission, answer_gate = asyncio.run(
        _separated_evidence_summary(
            backend,
            candidate_ids=candidate_ids,
        )
    )
    promotion: dict[str, Any] = {
        **promotion_counts,
        "evidence_admission": evidence_admission,
        "answer_gate": answer_gate,
    }
    answer_packet = asyncio.run(
        _build_answer_packet(
            backend,
            job=completed,
            candidate_ids=candidate_ids,
            promotion_counts=promotion_counts,
            runtime_reviewed=semantic_allows_candidate_review,
        )
    )
    promotion["answer_packet"] = answer_packet
    disposition = "promoted" if promotion["promoted"] else "no_candidate"
    challenge_passed = bool(
        not candidate_ids
        and completed.zero_candidate_challenge_version == "v1"
        and completed.semantic_review.get("zero_candidate_challenge")
    )
    reason_codes = (
        ["durable_memory_promoted"]
        if disposition == "promoted"
        else [
            "zero_candidate_challenge_passed"
            if challenge_passed
            else (
                "semantic_review_blocked"
                if not semantic_allows_candidate_review
                else "no_durable_candidate"
            )
        ]
    )
    source_cleanup = {
        "configured": _source_cleanup_allowed(completed),
        "status": "retained",
        "receipt_id": None,
        "reason_codes": (
            ["source_cleanup_after_active_processing"]
            if _source_cleanup_allowed(completed)
            else ["dream_keeps_source"]
        ),
    }
    backend.transcript_store.record_distill_completion_outcome(
        completed.id,
        disposition=disposition,
        reason_codes=reason_codes,
        promotion_summary=promotion,
        source_cleanup_status="retained",
    )
    # Materialize while the privacy-safe user-facing identity and semantic
    # summary are still present. Processed-source cleanup intentionally
    # sanitizes session_id/project_root and raw review details afterwards.
    pre_cleanup = backend.transcript_store.get_distill_job(completed.id) or completed
    note = materialize_session_note(
        pre_cleanup,
        notes_dir=_session_notes_dir(backend),
    )
    if _source_cleanup_allowed(completed):
        source_cleanup = _cleanup_completed_distill_source(
            backend,
            completed=completed,
        )
    stored = backend.transcript_store.record_distill_completion_outcome(
        completed.id,
        disposition=disposition,
        reason_codes=reason_codes,
        promotion_summary=promotion,
        source_cleanup_status=str(source_cleanup["status"]),
        source_cleanup_receipt_id=source_cleanup.get("receipt_id"),
    )
    # Candidate/evidence/proposed-decision detail is retry material. Remove it
    # only after current knowledge/no-write, Answer Packet, Note, and terminal
    # receipt are all durable.
    asyncio.run(backend.structured_store.knowledge_store.cleanup_job(stored.id))
    queue = distill_drainer_metrics(
        backend,
        project_name=project_name,
    )
    payload["completion"] = {
        "disposition": stored.completion_disposition,
        "reason_codes": stored.completion_reason_codes,
    }
    payload["note"] = note
    payload["promotion"] = promotion
    payload["answer_packet"] = answer_packet
    payload["queue_effect"] = {
        "removed_from_pending": True,
        "pending_total_after": queue["pending_total"],
    }
    payload["source_cleanup"] = source_cleanup
    payload["session_summary"] = _session_summary_payload(stored)
    return payload


def _source_cleanup_allowed(job: Any) -> bool:
    """Return whether a completed job came from active user processing."""

    return bool(
        getattr(job, "review_execution_source", None) == "interactive_agent"
        or getattr(job, "client", None) == "codex-archive"
    )


def _source_cleanup_payload(job: Any) -> dict[str, Any]:
    return {
        "configured": _source_cleanup_allowed(job),
        "status": job.source_cleanup_status,
        "receipt_id": job.source_cleanup_receipt_id,
    }


def _replay_completed_source_cleanup(
    backend: LocalMemoryBackend,
    *,
    job: Any,
) -> dict[str, Any]:
    """Finish cleanup for an already completed active job, if needed."""

    if not _source_cleanup_allowed(job):
        return {
            **_source_cleanup_payload(job),
            "reason_codes": ["dream_keeps_source"],
        }
    if job.source_cleanup_status == "deleted":
        note_cleanup = delete_session_notes(_session_notes_dir(backend), job)
        result = {**_source_cleanup_payload(job), "note_cleanup": note_cleanup}
        if note_cleanup.get("failed"):
            result["status"] = "partial_failure"
            result["reason_codes"] = ["session_note_cleanup_failed"]
        return result
    return _cleanup_completed_distill_source(backend, completed=job)


async def _settle_distill_candidates(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidate_ids: list[str],
) -> dict[str, Any]:
    """Record an explicit non-writing result for every separated candidate."""

    from harness_mem.commands.knowledge_assimilation import (
        record_assimilation_result,
    )

    counts: dict[str, Any] = {
        "suggested": len(candidate_ids),
        "promoted": 0,
        "confirmed": 0,
        "no_write": 0,
        "handoff": 0,
        "deferred": 0,
        "conflict": 0,
        "rejected": 0,
        "missing": 0,
        "pending": 0,
    }
    points: list[dict[str, Any]] = []
    store = backend.structured_store.knowledge_store
    for candidate_id in candidate_ids:
        candidate = await store.get_candidate(candidate_id)
        if candidate is None:
            counts["missing"] += 1
            continue
        if candidate.project_name != project_name:
            raise ValueError("distill candidate belongs to another project")
        if candidate.status == "pending":
            await record_assimilation_result(
                backend,
                candidate=candidate,
                point={
                    "disposition": "reject",
                    "reason": "Session review did not admit this point to current knowledge.",
                },
            )
            candidate = await store.get_candidate(candidate_id)
            if candidate is None:
                counts["missing"] += 1
                continue
        if candidate.status == "rejected":
            disposition = "reject"
            counts["rejected"] += 1
        elif candidate.status == "deferred":
            disposition = "defer"
            counts["deferred"] += 1
        elif candidate.status == "conflict":
            disposition = "conflict"
            counts["conflict"] += 1
        else:
            counts["pending"] += 1
            continue
        points.append(
            {
                "candidate_id": candidate.id,
                "answer_status": "UNANSWERED",
                "disposition": disposition,
                "canonical_truth_ids": [],
                "separated_knowledge_ids": [],
                "handoff_id": None,
            }
        )
    return {**counts, "points": points}


def _cleanup_completed_distill_source(
    backend: LocalMemoryBackend,
    *,
    completed: Any,
) -> dict[str, Any]:
    """Run source cleanup after the explicit distill result is durable."""
    source = backend.transcript_store.get_source(completed.source_id)
    if source is None or source.source_revision != completed.source_revision:
        return {
            "configured": True,
            "status": "partial_failure",
            "receipt_id": None,
            "reason_codes": ["source_revision_changed"],
        }
    try:
        from harness_mem.native_source_cleanup import (
            apply_native_source_cleanup,
            plan_native_source_cleanup,
        )
        from harness_mem.processed_source_cleanup import (
            begin_processed_source_cleanup,
            cleanup_processed_source,
        )

        native_plan = plan_native_source_cleanup(source)
        native_preview = native_plan.to_preview()
        if native_plan.retained or not native_plan.supported:
            return {
                "configured": True,
                "status": "retained",
                "receipt_id": None,
                "reason_codes": list(native_preview.get("reason_codes") or []),
                "native": native_preview,
            }
        receipt_id: str | None = None
        if native_plan.supported:
            begun = begin_processed_source_cleanup(
                backend,
                job_id=completed.id,
                native_preview=native_preview,
            )
            if not begun.get("success"):
                return {
                    "configured": True,
                    "status": "partial_failure",
                    "receipt_id": None,
                    "reason_codes": list(begun.get("reason_codes") or []),
                }
            receipt_id = str(begun["receipt_id"])
        native_result = apply_native_source_cleanup(native_plan)
        result = asyncio.run(
            cleanup_processed_source(
                backend,
                job_id=completed.id,
                native_cleanup=native_result,
                receipt_id=receipt_id,
            )
        )
        note_cleanup = (
            delete_session_notes(_session_notes_dir(backend), completed)
            if result.get("status") == "deleted"
            else {"removed": 0, "failed": 0}
        )
        if note_cleanup.get("failed"):
            result["status"] = "partial_failure"
            result.setdefault("reason_codes", []).append(
                "session_note_cleanup_failed"
            )
        result["note_cleanup"] = note_cleanup
        return {
            "configured": True,
            "status": result.get("status", "partial_failure"),
            "receipt_id": result.get("receipt_id"),
            "reason_codes": list(result.get("reason_codes") or []),
            "counts": dict(result.get("counts") or {}),
        }
    except Exception as exc:  # noqa: BLE001 - cleanup must fail closed.
        return {
            "configured": True,
            "status": "partial_failure",
            "receipt_id": None,
            "reason_codes": [f"cleanup_failed:{type(exc).__name__}"],
        }


async def _distill_job_handoff_ids(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str,
) -> list[str]:
    """Return task handoffs explicitly produced by one lossless job."""

    handoffs = await backend.structured_store.get_latest_handoffs(
        project_name,
        limit=100_000,
    )
    return [
        handoff.id
        for handoff in handoffs
        if dict(handoff.context or {}).get("distill_job_id") == distill_job_id
    ]


def _validate_zero_candidate_challenge(
    backend: LocalMemoryBackend,
    *,
    job: SessionDistillJob,
    semantic_review: dict[str, Any],
    candidate_ids: list[str],
    handoff_ids: list[str],
) -> dict[str, Any] | None:
    """Fail closed before an Agent can bury a v1 job as no-candidate."""

    if candidate_ids or handoff_ids or job.zero_candidate_challenge_version != "v1":
        return None

    raw_challenge = semantic_review.get("zero_candidate_challenge")
    if not isinstance(raw_challenge, dict):
        return {
            "error": "zero_candidate_challenge_required",
            "reason_codes": ["zero_candidate_challenge_missing"],
            "next_step": (
                "Inspect the required semantic exchanges, complete the v1 "
                "zero-candidate checks, then retry finalization."
            ),
        }
    try:
        challenge = ZeroCandidateChallenge(**raw_challenge)
    except ValidationError as exc:
        return {
            "error": "zero_candidate_challenge_invalid",
            "reason_codes": ["zero_candidate_challenge_schema_invalid"],
            "validation_errors": exc.errors(include_url=False),
        }
    if challenge.source_revision != job.source_revision:
        return {
            "error": "zero_candidate_challenge_revision_mismatch",
            "reason_codes": ["source_revision_changed"],
        }
    if challenge.conclusion == "candidate_required":
        return {
            "error": "zero_candidate_challenge_requires_candidate",
            "reason_codes": ["durable_signal_requires_candidate"],
            "next_step": (
                "Create a scoped candidate or handoff for the durable signal, "
                "then retry finalization."
            ),
        }
    if semantic_review.get("promotion_decision") != "no_promotion":
        return {
            "error": "zero_candidate_review_inconsistent",
            "reason_codes": ["zero_candidate_requires_no_promotion"],
        }

    evidence = _load_distill_semantic_evidence(
        backend,
        source_id=job.source_id,
        source_revision=job.source_revision,
        detail_level="compact",
        budget_tokens=256,
    )
    if evidence is None:
        return {
            "error": "zero_candidate_evidence_unavailable",
            "reason_codes": ["semantic_evidence_unavailable"],
        }
    required_indexes = [
        int(index)
        for index in evidence.get("zero_candidate_required_exchange_indexes", [])
    ]
    basis = evidence.get("zero_candidate_review_basis")
    if basis == "complete_raw_checkpoint" and not required_indexes:
        checkpoints = backend.transcript_store.list_distill_checkpoints(job.id)
        raw_reviewed = bool(checkpoints) and all(
            checkpoint.status == "completed"
            and not checkpoint.result.get("structural_verified")
            for checkpoint in checkpoints
        )
        if not raw_reviewed:
            return {
                "error": "zero_candidate_raw_review_required",
                "reason_codes": ["complete_raw_checkpoint_not_agent_reviewed"],
            }
        return None

    windows = _load_distill_exchange_windows(
        backend,
        source_id=job.source_id,
        source_revision=job.source_revision,
        indexes=required_indexes,
    )
    expected_refs = {
        int(window["exchange_index"]): str(window["content_sha256"])
        for window in windows
    }
    supplied_refs = {
        item.exchange_index: item.content_sha256
        for item in challenge.inspected_exchange_refs
    }
    missing_or_changed = [
        index
        for index, content_sha256 in expected_refs.items()
        if supplied_refs.get(index) != content_sha256
    ]
    if missing_or_changed or set(expected_refs) != set(required_indexes):
        return {
            "error": "zero_candidate_exchange_proof_incomplete",
            "reason_codes": ["required_exchange_proof_missing_or_changed"],
            "required_exchange_indexes": required_indexes,
            "missing_or_changed_exchange_indexes": missing_or_changed,
        }

    checks = challenge.checks.model_dump()
    required_reasons = evidence.get(
        "zero_candidate_required_exchange_reasons",
        {},
    )
    challenged_signals = {
        reason
        for reasons in required_reasons.values()
        for reason in reasons
        if reason in checks
    }
    incorrectly_absent = sorted(
        signal for signal in challenged_signals if checks.get(signal) == "absent"
    )
    if incorrectly_absent:
        return {
            "error": "zero_candidate_signal_check_inconsistent",
            "reason_codes": ["detected_signal_marked_absent"],
            "signals": incorrectly_absent,
        }
    rationale = challenge.rationale.lower()
    downgraded_signals = sorted(
        signal
        for signal in challenged_signals
        if checks.get(signal) == "not_durable"
    )
    rationale_without_signal_keys = rationale
    for signal in downgraded_signals:
        rationale_without_signal_keys = rationale_without_signal_keys.replace(
            signal.lower(), ""
        )
    has_session_only_explanation = (
        challenge.future_utility == "session_only"
        and sum(character.isalnum() for character in rationale_without_signal_keys)
        >= 12
    )
    unjustified_downgrades = [
        signal for signal in downgraded_signals if signal.lower() not in rationale
    ]
    if downgraded_signals and not has_session_only_explanation:
        unjustified_downgrades = downgraded_signals
    if unjustified_downgrades:
        return {
            "error": "zero_candidate_signal_downgrade_unjustified",
            "reason_codes": ["detected_signal_downgrade_requires_rationale"],
            "signals": unjustified_downgrades,
            "next_step": (
                "Name each downgraded signal key in the rationale and explain why "
                "it is session-only, or create a scoped candidate or handoff."
            ),
        }
    return None


def _semantic_review_allows_candidate_review(review: dict[str, Any]) -> bool:
    """Review answered candidates even when unrelated handoff work remains."""

    decision = review.get("promotion_decision")
    if decision == "promote":
        return _semantic_review_allows_promotion(review)
    # A partial session may describe replaced plans or other historical
    # contradictions while still containing an independently ANSWERED
    # candidate. The candidate's own evidence envelope decides admission;
    # session-level contradictions continue to block Dream/full promotion.
    return bool(
        decision == "partial"
        and review.get("evidence_status") in {"answered", "partial"}
        and review.get("last_turn_status") in {"answered", "unfinished"}
    )


def _completed_job_requires_signal_gate_recheck(job: Any) -> bool:
    """Re-open legacy false negatives without rewriting their audit record."""

    if (
        job.status != "completed"
        or job.pipeline_version == _SIGNAL_GATE_RECHECK_PIPELINE_VERSION
        or job.completion_disposition != "no_candidate"
        or "zero_candidate_challenge_passed" not in job.completion_reason_codes
    ):
        return False
    review = job.semantic_review
    if not str(review.get("session_summary") or "").strip():
        return True
    challenge = review.get("zero_candidate_challenge")
    if not isinstance(challenge, dict) or challenge.get("version") != "v1":
        return False
    checks = challenge.get("checks")
    if not isinstance(checks, dict):
        return False
    rationale = str(challenge.get("rationale") or "").lower()
    return any(
        value == "not_durable" and str(signal).lower() not in rationale
        for signal, value in checks.items()
    )


def _semantic_review_allows_promotion(review: dict[str, Any]) -> bool:
    """Require a fully completed review before the post-distill Dream pass."""

    return bool(
        review.get("promotion_decision") == "promote"
        and review.get("evidence_status") == "answered"
        and review.get("last_turn_status") == "answered"
        and not review.get("contradictions")
        and not review.get("unfinished_work")
    )
