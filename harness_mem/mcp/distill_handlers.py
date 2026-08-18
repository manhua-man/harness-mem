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

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    SUPPORTED_INGEST_CLIENTS,
    normalize_client_name,
    resolve_project_context,
    resolve_host_source,
    resolve_ingest_client,
)
from harness_mem.commands.distill_lifecycle import distill_drainer_metrics
from harness_mem.commands.assimilation import apply_assimilation
from harness_mem.commands.separated_assimilation import (
    apply_separated_assimilation,
    separated_job_candidate_ids,
)
from harness_mem.commands.evidence_admission import answer_gate_status
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.adapters.projection_repair import repair_source_observation_projection
from harness_mem.governance_status import CANDIDATE_LAYER_STATUSES, TRUTH_LAYER_STATUSES
from harness_mem.core.schemas.session_distill import (
    AssimilationPacketPoint,
    AnswerPacket,
    PromotedKnowledgeItem,
    SessionDistillJob,
    ZeroCandidateChallenge,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.session_notes import materialize_session_note
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


def _session_notes_dir(backend: LocalMemoryBackend) -> Path:
    override = str(os.environ.get("HARNESS_MEM_SESSION_NOTES_DIR") or "").strip()
    if override:
        return Path(override).expanduser().resolve()
    if Path(backend.data_dir).resolve() != DEFAULT_DATA_DIR.resolve():
        return Path(backend.data_dir) / "session_notes"
    return Path.home() / ".codex" / "hm-distill" / "sessions"


def _get_backend():
    return _core._get_backend()


def _observer_data_dir():
    return _core._observer_data_dir()


def _cost_surface_budgets(project_name):
    return _core._cost_surface_budgets(project_name)


def _record_state_event(*args, **kwargs):
    return _core._record_state_event(*args, **kwargs)


def _run_command_to_payload(coro):
    return _core._run_command_to_payload(coro)


async def _gather_project_status(*args, **kwargs):
    return await _core._gather_project_status(*args, **kwargs)


def _ingest_sessions(*args, **kwargs):
    return _core._ingest_sessions(*args, **kwargs)


async def auto_review_candidates(*args, **kwargs):
    return await _core.auto_review_candidates(*args, **kwargs)


async def dream_auto_tick(*args, **kwargs):
    return await _core.dream_auto_tick(*args, **kwargs)


async def _recent_project_observations(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
) -> list[Any]:
    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    return sorted(
        project_observations,
        key=lambda observation: (
            observation.timestamp or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )[:limit]


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
    ][:8]
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
    limit: int = 5,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
    observation_limit: int = 5,
    max_chars_per_observation: int = 6000,
    chunk_limit: int = 1,
    evidence_mode: str = "raw",
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
    """Prepare a compact evidence packet for AI-led /hm:distill.

    This intentionally stops before synthesis. The model should read the
    returned observations, decide what deserves a pending candidate, then call
    govern_memory(action=suggest). The lower-level sync step may call ingest_sessions, but
    /hm:distill is the user-facing flow.
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
    )[:8]
    requested_drilldown_indexes = sorted(
        {int(index) for index in (drilldown_chunk_indexes or []) if int(index) >= 0}
    )[:8]
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

    effective_limit = max(1, min(int(limit), 50))
    effective_observation_limit = max(1, min(int(observation_limit), 20))
    effective_max_chars = max(500, min(int(max_chars_per_observation), 20000))

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
    distill_config = (
        load_merged_config(Path(resolved_project_root))
        if resolved_project_root
        and Path(resolved_project_root).is_absolute()
        and Path(resolved_project_root).is_dir()
        else MergedConfig()
    )
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
    backend.transcript_store.rebalance_distill_jobs(
        resolved_project_name,
        target_active=distill_config.distill_auto_target_backlog,
        recent_first=distill_config.distill_auto_recent_first,
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
        if (
            requested_job_id is None
            and _completed_job_requires_signal_gate_recheck(session_job)
        ):
            session_job = backend.transcript_store.enqueue_distill_job(
                session_job.source_id,
                pipeline_version=_SIGNAL_GATE_RECHECK_PIPELINE_VERSION,
                active_limit=distill_config.distill_auto_target_backlog,
                recent_first=distill_config.distill_auto_recent_first,
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
            "source_cleanup": {
                "status": requested_job.source_cleanup_status,
                "receipt_id": requested_job.source_cleanup_receipt_id,
            },
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
                limit=100,
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
    if (
        requested_job_id
        and requested_job
        and _distill_source != "autonomous_worker"
        and (
            requested_job.agent_offer_day != now.date().isoformat()
            or requested_job.agent_offer_count <= 0
        )
    ):
        return {
            "success": False,
            "error": "distill_job_id was not offered for Agent processing today",
            "distill_job_id": requested_job_id,
            "distill_status": requested_job.status,
            "agent_offer_day": requested_job.agent_offer_day,
        }
    if lossless_jobs:
        # Daily automation is recent-first: one malformed historical session
        # cannot head-of-line block every newer task.  Old work is still
        # reached once the recent lane is drained.
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
                        "Consume this job on the next Agent-capable wake or /hm:distill run.",
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
                ][:8]
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
            limit=max(1, min(int(chunk_limit), 3)),
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
    counts = asyncio.run(_gather_project_status(backend, resolved_project_name))

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
        "status": counts,
        "observation_limit": effective_observation_limit,
        "max_chars_per_observation": effective_max_chars,
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


def _knowledge_projection(candidate: Any) -> tuple[str, str, str, str]:
    """Project a governed candidate into one ID-free, user-readable fact."""

    if hasattr(candidate, "content"):
        fact = str(candidate.content).strip()
        category = str(getattr(candidate, "category", "knowledge") or "knowledge")
        kind = str(getattr(candidate, "memory_type", "memory") or "memory")
        title = str(getattr(candidate, "canonical_title", "") or "").strip()
        if not title:
            title = f"{category}：{fact.split('。', 1)[0].split('.', 1)[0][:80]}"
        return title, fact, kind, category
    if hasattr(candidate, "pattern"):
        fact = str(candidate.pattern).strip()
        trigger = str(getattr(candidate, "trigger", "") or "").strip()
        title = str(getattr(candidate, "canonical_title", "") or "").strip()
        if not title:
            title = trigger[:80] or fact.split("。", 1)[0].split(".", 1)[0][:80]
        return title, fact, "rule", "rule"
    source = str(getattr(candidate, "source_entity", "") or "").strip()
    target = str(getattr(candidate, "target_entity", "") or "").strip()
    relation = str(getattr(candidate, "relation_type", "relation") or "relation")
    fact = f"{source} {relation} {target}".strip()
    return f"{source} {relation} {target}"[:80], fact, "relation", relation


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
        candidates = await _distill_candidates(backend, candidate_ids)
        promoted_candidates = [
            candidate
            for candidate in candidates
            if str(getattr(candidate, "status", "")) in TRUTH_LAYER_STATUSES
        ]
        items = []
        for candidate in promoted_candidates:
            title, fact, kind, category = _knowledge_projection(candidate)
            items.append(
                PromotedKnowledgeItem(
                    title=title or category,
                    fact=fact,
                    kind=kind,
                    category=category,
                )
            )
    promoted_count = int(promotion_counts.get("promoted") or 0)
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


def _uses_separated_assimilation(review: Mapping[str, Any] | None) -> bool:
    payload = dict(review or {})
    plan = payload.get("assimilation")
    return isinstance(plan, dict) and plan.get("version") == "separated-v1"


def tool_finalize_session_distill(
    project_name: str,
    job_id: str,
    semantic_review: dict,
    _review_lease_owner: str | None = None,
) -> dict:
    """Validate and finalize one explicit job, then auto-review and run Dream."""

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
    config, config_reason_code = _load_completion_config(job.project_root)
    recovering_completion = (
        job.status == "completed" and job.completion_disposition is None
    )
    if job.status == "completed" and not recovering_completion:
        queue = distill_drainer_metrics(
            backend,
            project_name=project_name,
            daily_job_budget=config.distill_auto_daily_job_budget,
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
            "source_cleanup": {
                "configured": bool(
                    config.distill_delete_source_after_complete
                    or job.source_cleanup_receipt_id
                    or job.source_cleanup_status
                    in {"deleted", "partial_failure", "unsupported"}
                ),
                "status": job.source_cleanup_status,
                "receipt_id": job.source_cleanup_receipt_id,
            },
            "note": note,
        }
    if recovering_completion:
        candidate_ids = list(job.output_candidate_ids)
        completed = job
    else:
        checkpoints = backend.transcript_store.list_distill_checkpoints(job.id)
        completed_checkpoints = sum(
            item.status == "completed" for item in checkpoints
        )
        if completed_checkpoints != job.expected_chunk_count:
            raise ValueError("not all distill chunks are complete")
        supplied_assimilation = semantic_review.get("assimilation")
        if isinstance(supplied_assimilation, dict) and supplied_assimilation.get(
            "version"
        ) == "separated-v1":
            candidate_ids = list(supplied_assimilation.get("candidate_ids") or [])
            actual_candidate_ids = asyncio.run(
                separated_job_candidate_ids(
                    backend,
                    project_name=project_name,
                    distill_job_id=job_id,
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
                _distill_job_candidate_ids(
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
        completed = backend.transcript_store.finalize_distill_job(
            job_id,
            semantic_review=semantic_review,
            output_candidate_ids=candidate_ids,
            review_lease_owner=_review_lease_owner,
        )
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
    semantic_allows_dream = _semantic_review_allows_promotion(
        completed.semantic_review
    )
    dream_result: dict[str, Any] | None = None
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
    elif isinstance(assimilation_plan, dict) and assimilation_plan.get("version") == "v1":
        assimilation_summary = asyncio.run(
            apply_assimilation(
                backend,
                project_name=project_name,
                candidate_ids=candidate_ids,
                plan=assimilation_plan,
            )
        )
        payload["auto_review"] = {
            "skipped": True,
            "reason": "autonomous_assimilation_applied",
            "candidate_ids": candidate_ids,
        }
    elif semantic_allows_candidate_review:
        summary = asyncio.run(
            auto_review_candidates(
                backend,
                project_name=project_name,
                apply=True,
                candidate_ids=candidate_ids,
            )
        )
        auto_review_payload = summary.to_dict()
        payload["auto_review"] = auto_review_payload
        evidence_admission = dict(auto_review_payload["evidence_admission"])
        answer_gate = dict(auto_review_payload["answer_gate"])
    else:
        payload["auto_review"] = {
            "skipped": True,
            "reason": "semantic_review_blocks_candidate_review",
            "candidate_ids": candidate_ids,
        }
    try:
        if semantic_allows_dream:
            dream_result = asyncio.run(
                dream_auto_tick(
                    backend,
                    project_name=project_name,
                    project_root=completed.project_root,
                    config=config,
                    source="agent",
                )
            )
            payload["dream"] = dream_result
    except Exception as exc:  # noqa: BLE001 - completed distill remains auditable.
        dream_result = {
            "success": False,
            "status": "failed",
            "project_name": project_name,
            "error": f"{type(exc).__name__}: {exc}"[:512],
        }
        payload["dream"] = dream_result

    promotion_counts = (
        assimilation_summary
        if assimilation_summary is not None
        else asyncio.run(
            _settle_distill_candidates(
                backend,
                project_name=project_name,
                candidate_ids=candidate_ids,
            )
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
    if dream_result is not None and dream_result.get("success") is False:
        reason_codes.append("dream_postprocess_failed")
    if config_reason_code is not None:
        reason_codes.append(config_reason_code)

    source_cleanup = {
        "configured": config.distill_delete_source_after_complete,
        "status": "retained",
        "receipt_id": None,
        "reason_codes": ["retention_default"],
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
    if config.distill_delete_source_after_complete:
        source_cleanup = _cleanup_completed_distill_source(
            backend,
            completed=completed,
            dream_result=dream_result,
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
        daily_job_budget=config.distill_auto_daily_job_budget,
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


def _load_completion_config(project_root: str) -> tuple[MergedConfig, str | None]:
    """Load completion policy without stranding an already-reviewed job."""

    safe_fallback = MergedConfig(distill_delete_source_after_complete=False)
    if not project_root or not Path(project_root).is_dir():
        return safe_fallback, "completion_project_root_unavailable"
    try:
        return load_merged_config(project_root), None
    except (ConfigError, OSError):
        # A malformed or temporarily unreadable Config_File must not leave the
        # distill job completed but missing its terminal outcome. Even though
        # the normal default is cleanup-on-success, unreadable policy cannot
        # authorize deletion, so recovery remains fail-safe and retains source.
        return safe_fallback, "completion_config_invalid"


async def _settle_distill_candidates(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    candidate_ids: list[str],
) -> dict[str, int]:
    """Make one distill job terminal without leaving a daily review burden."""

    promoted = 0
    rejected = 0
    missing = 0
    for candidate_id in candidate_ids:
        candidate: Any | None = await backend.structured_store.get_memory_entry(
            candidate_id
        )
        update_status = backend.structured_store.update_memory_entry_status
        if candidate is None:
            candidate = await backend.structured_store.get_rule_candidate(candidate_id)
            update_status = backend.structured_store.update_rule_candidate_status
        if candidate is None:
            candidate = await backend.structured_store.get_relation_fact(candidate_id)
            update_status = backend.structured_store.update_relation_fact_status
        if candidate is None:
            missing += 1
            continue
        status = str(getattr(candidate, "status", "pending"))
        if status in TRUTH_LAYER_STATUSES:
            promoted += 1
            continue
        if status in CANDIDATE_LAYER_STATUSES and status != "rejected":
            await update_status(candidate_id, "rejected")
            status = "rejected"
        if status == "rejected":
            rejected += 1
    return {
        "suggested": len(candidate_ids),
        "promoted": promoted,
        "rejected": rejected,
        "pending": 0,
        "missing": missing,
    }


def _cleanup_completed_distill_source(
    backend: LocalMemoryBackend,
    *,
    completed: Any,
    dream_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """Run the content-free source-cleanup saga after automatic post-processing."""

    if dream_result is not None and dream_result.get("success") is False:
        return {
            "configured": True,
            "status": "retained",
            "receipt_id": None,
            "reason_codes": ["dream_postprocess_failed"],
        }
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
        if native_plan.retained:
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


async def _distill_job_candidate_ids(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    distill_job_id: str,
) -> list[str]:
    """Return only candidates explicitly produced by one lossless job."""

    entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100_000,
        status="pending",
    )
    rules = await backend.structured_store.list_rule_candidates(
        project_name,
        status="pending",
    )
    facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100_000,
        status="pending",
    )
    return [
        str(getattr(candidate, "id"))
        for candidate in [*entries, *rules, *facts]
        if getattr(candidate, "distill_job_id", None) == distill_job_id
    ]


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
    # A partial session may describe superseded plans or other historical
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
