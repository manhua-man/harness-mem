"""Lossless session-distill MCP handlers.

This module owns evidence projection, chunk checkpointing, semantic review,
finalization, and bounded legacy fallback. Public schemas remain unchanged.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from harness_mem.commands.support import (
    SUPPORTED_INGEST_CLIENTS,
    normalize_client_name,
    resolve_project_context,
    resolve_host_source,
    resolve_ingest_client,
)
from harness_mem.commands.distill_lifecycle import distill_drainer_metrics
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.governance_status import CANDIDATE_LAYER_STATUSES, TRUTH_LAYER_STATUSES
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import sha256_text
from harness_mem.mcp.distill_projection import (
    build_distill_compact_outline,
    build_distill_semantic_outline,
    render_distill_exchange_windows,
    split_distill_semantic_content,
)

from .handler_facade_proxy import tool_handlers_facade as _core


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
    if observation is None:
        return None
    if observation.metadata.get("source_revision") != source_revision:
        return None

    parser_content = observation.raw_content
    if detail_level == "full":
        content, projection_summary = build_distill_semantic_outline(parser_content)
        projection_summary = {
            **projection_summary,
            "detail_level": "full",
            "budget_tokens": max(256, int(budget_tokens or 3000)),
            "budget_state": "full_requested",
            "budget_reason": "caller explicitly requested complete semantic evidence",
        }
    else:
        content, projection_summary = build_distill_compact_outline(
            parser_content,
            budget_tokens=budget_tokens,
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
        return []
    return render_distill_exchange_windows(observation.raw_content, indexes)


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
    resolved_budget_tokens = max(256, min(int(budget_tokens or 3000), 12000))
    # The caller budget applies to the whole MCP result, not only the semantic
    # text. Reserve room for provenance, job state, hashes, and drilldown hints.
    semantic_budget_tokens = (
        resolved_budget_tokens
        if detail_level == "full"
        else max(256, resolved_budget_tokens - 1100)
    )
    requested_exchange_indexes = sorted(
        {int(index) for index in (drilldown_exchange_indexes or []) if int(index) >= 1}
    )[:8]
    requested_drilldown_indexes = sorted(
        {int(index) for index in (drilldown_chunk_indexes or []) if int(index) >= 0}
    )[:8]
    requested_drilldown_query = str(drilldown_query or "").strip()[:200]
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
    if requested_job_id and requested_job and (
        requested_job.agent_offer_day != now.date().isoformat()
        or requested_job.agent_offer_count <= 0
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
            "selection_source": "explicit" if requested_job_id else "queue_policy",
            "distill_status": lossless_job.status,
            "source_id": lossless_job.source_id,
            "source_revision": lossless_job.source_revision,
            "expected_chunk_count": lossless_job.expected_chunk_count,
            "completed_chunk_count": lossless_job.completed_chunk_count,
            "evidence_mode": evidence_mode,
            "detail_level": detail_level,
            "budget_tokens": resolved_budget_tokens,
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
                semantic_evidence = _load_distill_semantic_evidence(
                    backend,
                    source_id=lossless_job.source_id,
                    source_revision=lossless_job.source_revision,
                    detail_level=detail_level,
                    budget_tokens=semantic_budget_tokens,
                )
                if semantic_evidence is not None:
                    checkpoints = backend.transcript_store.list_distill_checkpoints(
                        lossless_job.id
                    )
                    structurally_verified = sum(
                        bool(checkpoint.result.get("structural_verified"))
                        for checkpoint in checkpoints
                    )
                    base_payload.update(
                        {
                            "chunks": [],
                            "chunk_count": 0,
                            "semantic_evidence": semantic_evidence,
                            "structural_checkpoint_summary": {
                                "expected": lossless_job.expected_chunk_count,
                                "completed": lossless_job.completed_chunk_count,
                                "runtime_verified": structurally_verified,
                            },
                            "distill_instructions": [
                                "Read the complete indexed semantic outline in order.",
                                "Runtime already hash-verified and checkpointed every raw chunk.",
                                "Select semantic windows with drilldown_exchange_indexes, then verify candidates with raw drilldown.",
                                "Create only warranted candidates through govern_memory(action=suggest), then call finalize_session_distill.",
                            ],
                        }
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
            semantic_evidence = _load_distill_semantic_evidence(
                backend,
                source_id=lossless_job.source_id,
                source_revision=lossless_job.source_revision,
                detail_level=detail_level,
                budget_tokens=semantic_budget_tokens,
            )
            if semantic_evidence is not None:
                updated_job = _checkpoint_distill_structural_projection(
                    backend,
                    job_id=lossless_job.id,
                    source_revision=lossless_job.source_revision,
                    semantic_content_sha256=semantic_evidence["content_sha256"],
                )
                if updated_job.status == "reviewing":
                    base_payload.update(
                        {
                            "distill_status": updated_job.status,
                            "completed_chunk_count": updated_job.completed_chunk_count,
                            "chunks": [],
                            "chunk_count": 0,
                            "semantic_evidence": semantic_evidence,
                            "structural_checkpoint_summary": {
                                "expected": updated_job.expected_chunk_count,
                                "completed": updated_job.completed_chunk_count,
                                "runtime_verified": updated_job.completed_chunk_count,
                            },
                            "distill_instructions": [
                                "Read the complete indexed semantic outline in order.",
                                "Runtime already hash-verified and checkpointed every raw chunk.",
                                "Select semantic windows with drilldown_exchange_indexes, then verify candidates with raw drilldown.",
                                "Create only warranted candidates, then call finalize_session_distill.",
                            ],
                        }
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
            "Treat them as a searchable audit view, not as a lossless session-distill packet.",
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


def tool_finalize_session_distill(
    project_name: str,
    job_id: str,
    semantic_review: dict,
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
        return {
            "success": True,
            "idempotent_replay": True,
            "project_name": project_name,
            "distill_job_id": job.id,
            "distill_status": job.status,
            "structural_audit": job.structural_audit,
            "semantic_review": job.semantic_review,
            "completion": {
                "disposition": job.completion_disposition,
                "reason_codes": job.completion_reason_codes,
            },
            "promotion": dict(job.promotion_summary),
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
        }
    if recovering_completion:
        candidate_ids = list(job.output_candidate_ids)
        completed = job
    else:
        candidate_ids = asyncio.run(
            _distill_job_candidate_ids(
                backend,
                project_name=project_name,
                distill_job_id=job_id,
            )
        )
        completed = backend.transcript_store.finalize_distill_job(
            job_id,
            semantic_review=semantic_review,
            output_candidate_ids=candidate_ids,
        )
    payload: dict[str, Any] = {
        "success": completed.status == "completed",
        "project_name": project_name,
        "distill_job_id": completed.id,
        "distill_status": completed.status,
        "structural_audit": completed.structural_audit,
        "semantic_review": completed.semantic_review,
    }
    if recovering_completion:
        payload["idempotent_replay"] = True
        payload["completion_recovered"] = True
    if completed.status != "completed":
        payload["error"] = completed.error
        return payload
    semantic_allows_promotion = _semantic_review_allows_promotion(
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
    if semantic_allows_promotion:
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
    else:
        payload["auto_review"] = {
            "skipped": True,
            "reason": "semantic_review_blocks_promotion",
            "candidate_ids": candidate_ids,
        }
    try:
        if semantic_allows_promotion:
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

    promotion_counts = asyncio.run(
        _settle_distill_candidates(
            backend,
            project_name=project_name,
            candidate_ids=candidate_ids,
        )
    )
    promotion: dict[str, Any] = {
        **promotion_counts,
        "evidence_admission": evidence_admission,
    }
    disposition = "promoted" if promotion["promoted"] else "no_candidate"
    reason_codes = (
        ["durable_memory_promoted"]
        if disposition == "promoted"
        else [
            "semantic_review_blocked"
            if not semantic_allows_promotion
            else "no_durable_candidate"
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
    queue = distill_drainer_metrics(
        backend,
        project_name=project_name,
        daily_job_budget=config.distill_auto_daily_job_budget,
    )
    payload["completion"] = {
        "disposition": stored.completion_disposition,
        "reason_codes": stored.completion_reason_codes,
    }
    payload["promotion"] = promotion
    payload["queue_effect"] = {
        "removed_from_pending": True,
        "pending_total_after": queue["pending_total"],
    }
    payload["source_cleanup"] = source_cleanup
    return payload


def _load_completion_config(project_root: str) -> tuple[MergedConfig, str | None]:
    """Load completion policy without stranding an already-reviewed job."""

    if not project_root or not Path(project_root).is_dir():
        return MergedConfig(), "completion_project_root_unavailable"
    try:
        return load_merged_config(project_root), None
    except (ConfigError, OSError):
        # A malformed or temporarily unreadable Config_File must not leave the
        # distill job completed but missing its terminal outcome. Default-off
        # source cleanup is the fail-closed fallback.
        return MergedConfig(), "completion_config_invalid"


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


def _semantic_review_allows_promotion(review: dict[str, Any]) -> bool:
    """Require an internally consistent, completed review before promotion."""

    return bool(
        review.get("promotion_decision") == "promote"
        and review.get("evidence_status") == "answered"
        and review.get("last_turn_status") == "answered"
        and not review.get("contradictions")
        and not review.get("unfinished_work")
    )
