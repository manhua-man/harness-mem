"""Lossless session distillation MCP handlers.

This module owns evidence projection, chunk checkpointing, semantic review,
finalization, and bounded legacy fallback.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
import json
from datetime import datetime, timezone
from functools import wraps
from inspect import signature
import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping, cast, get_args
from uuid import NAMESPACE_URL, uuid4, uuid5

from pydantic import ValidationError
from harness_mem.core.schemas import EvidenceRef
from harness_mem.core.schemas.assimilation import AssimilationDisposition
from harness_mem.core.schemas.evidence import EvidenceBasis, VerificationOutcome

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    SUPPORTED_INGEST_CLIENTS,
    normalize_client_name,
    resolve_host_source,
    resolve_ingest_client,
)
from harness_mem.commands.distill_lifecycle import distill_drainer_metrics
from harness_mem.commands.distill_result import DEFERRED_REVIEW_PIPELINE, deferred_review, distill_unfinished_work
from harness_mem.commands.separated_assimilation import (
    apply_separated_assimilation,
    prepare_interactive_assimilation,
    separated_job_candidate_ids,
    is_committed_job_replay,
    _subject as separated_evidence_subject,
)
from harness_mem.commands.evidence_admission import (
    answer_gate_status,
    evidence_summary_key,
)
from harness_mem.adapters.projection_repair import load_source_observation_projection
from harness_mem.diagnostic_events import (
    diagnostic_parent_id,
    emit_current_stage,
    DiagnosticRun,
)
from harness_mem.core.schemas.session_distill import (
    AssimilationPacketPoint,
    AnswerPacket,
    PromotedKnowledgeItem,
    SessionDistillJob,
    SessionSemanticReview,
    ZeroCandidateChallenge,
)
from harness_mem.core.schemas.source_report import readable_knowledge_statement
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.session_notes import delete_session_notes, materialize_session_note
from harness_mem.transcript_chunking import sha256_text
from harness_mem.mcp.distill_projection import (
    DISTILL_INCREMENTAL_PROJECTION,
    _parse_exchanges,
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
_MANUAL_SOURCE_RECHECK_PIPELINE_VERSION = "lossless-distill-v1-manual-source-recheck-v2"


def _manual_completion_proven(backend: LocalMemoryBackend, job: SessionDistillJob) -> bool:
    from harness_mem.commands.session_inventory import completion_proven, current_entries

    return completion_proven(job, current_entries(Path(backend.data_dir), job.project_name))


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
    """Project compact Agent results; measure explicit/internal diagnostic views."""

    handler_signature = signature(handler)

    @wraps(handler)
    def wrapped(*args, **kwargs):
        result = handler(*args, **kwargs)
        if not isinstance(result, dict):
            return result
        if not bool(result.get("success")):
            # A nested prepare may have produced a template before optional
            # context loading failed. Failed results are never call-ready.
            return {key: value for key, value in result.items() if key != "finalize_contract"}
        bound = handler_signature.bind_partial(*args, **kwargs)
        compact = (
            bound.arguments.get("detail_level", "compact") == "compact"
            and bound.arguments.get("_distill_source", "agent") == "agent"
        )
        if compact:
            result = _compact_prepare_result(result)
        include_current = bool(bound.arguments.get("include_current"))
        if (
            result.get("success") and result.get("distill_status") == "reviewing"
            and "current_knowledge_status" not in result and "current_knowledge" not in result
            and bound.arguments.get("_distill_source", "agent") == "agent"
            and not bound.arguments.get("_batch_selected")
            and not any(bound.arguments.get(key) for key in (
                "native_evidence", "drilldown_exchange_indexes",
                "drilldown_chunk_indexes", "drilldown_query",
            ))
        ):
            from harness_mem.commands.distill_current_knowledge import manual_knowledge_context

            result.update(asyncio.run(manual_knowledge_context(
                _get_backend(), result, include_current=include_current,
                scope=bound.arguments.get("scope", "project"),
            )))
            if include_current and result["current_knowledge_status"] == "unavailable":
                result.update(success=False, error="current memory is unavailable")
                result.pop("finalize_contract", None)
                return result
        if compact:
            return result
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


def _compact_finalize_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return verified saved results once, leaving failure/recovery detail intact."""
    if not result.get("success") or result.get("distill_status") != "completed":
        return result
    compact = {
        key: value for key, value in result.items()
        if key in {
            "success", "project_name", "distill_job_id", "distill_status",
            "session_id", "idempotent_replay", "organization_status",
            "knowledge_changes", "removed_count", "not_written", "unfinished_work",
            "readback_verified", "native_evidence",
            "resume_deferred",
            "batch_id", "batch_progress", "next_after_finalize",
        }
    }
    summary = result.get("session_summary") or {}
    if summary.get("session_id"):
        compact.setdefault("session_id", summary["session_id"])
    if isinstance(result.get("note"), dict):
        compact["note"] = {
            key: value for key, value in result["note"].items()
            if key in {"path", "latest_path", "sha256"}
        }
    # Cleanup failures are actionable even after knowledge has been saved.
    cleanup = result.get("source_cleanup") or {}
    if cleanup.get("status") not in {None, "retained", "deleted"}:
        compact["source_cleanup"] = cleanup
    return compact


def _finalize_call_contract(job_id: str) -> dict[str, Any]:
    """Project a source-generic call template, never candidate evidence or a write."""
    allowed_values = {
        "evidence_basis": list(get_args(EvidenceBasis)),
        "verification_outcome": list(get_args(VerificationOutcome)),
        "assimilation_disposition": list(get_args(AssimilationDisposition)),
        **{
            name: list(get_args(SessionSemanticReview.model_fields[name].annotation))
            for name in ("last_turn_status", "evidence_status", "promotion_decision")
        },
    }
    points = []
    for basis, role, content in (
        ("user_statement", "user", "<Exact durable user statement checked against the fully read source; preserve explicit correction wording and unchanged scope.>"),
        ("source_report", "assistant", "<Source-checked assistant proposal, attributed to this source speaker and period; not external truth or user approval.>"),
    ):
        points.append({
            "content": content,
            "canonical_title": "<Title of this independent checked point>",
            "topic_path": ["<Whole category name>"],
            "evidence_basis": basis,
            "verification_outcome": "verified",
            "verification_refs": [{
                "kind": basis,
                "exchange_index": "<Integer exchange_index from the checked source window>",
                "content_sha256": "<Exact content_sha256 from that source window>",
                "role": role,
            }],
            "assimilation_disposition": "add",
            "review": {
                "support": "supported", "use": "standing_decision" if basis == "user_statement" else "reusable_knowledge",
                "reason": "<Why the complete source supports this useful point and the selected disposition>",
                "conditions": [], "undecided_state": None,
                "evidence": [{
                    "target": "claim", "ref": 1, "message_index": 1,
                    "quote": "<Exact supporting excerpt from the cited message>",
                }],
            },
        })
    targets = [{
        "title": "<Exact full old title from the selected current row>",
        "statement": "<Entire old statement from that same current row>",
        "project_name": "<Exact owner project_name from that same current row>",
    }]
    return {
        "method": "finish",
        "template_only": True,
        "instructions": [
            "This is an instruction template, not verified content or an automatic decision. Replace every placeholder after checking the complete actual source; keep only relevant durable points.",
            "The two independent points illustrate a user statement and an assistant proposal report. Neither is required to exist. Add/verified are example choices only; assess every point and outcome yourself.",
            "A session can yield several independent memories. Each item should answer one later question on its own and retain the conditions that change what to do or how to verify it. Use the session summary for useful one-time incident context and unfinished_work for concrete remaining actions. Keep reusable lessons from failures as separate points when they answer distinct questions.",
            "Use the writing project's current_module_catalog and current_knowledge before choosing topic_path. Reuse the fitting functional path. Work and incident names belong in titles and statements; introduce a path only for a distinct function. Check focused search when the prepared comparison is limited. Preserve enough source-verified detail to use a result alone: a locatable entry point, exact command and target set, write trigger, recovery conditions, and specific acceptance checks. Do not repeat answers or infer authorization from a comparison.",
            "Source reports retain speaker, period and source scope; they do not establish external current truth, execution or user approval.",
            "A source_report point can also cite user_statement as supporting context. Bind exact review.evidence for every ref and a primary claim quote from the report itself.",
            "Before saving an operational outcome, check the actual action and its returned result when the source contains them. A binding, preview or planned action can only support what it displays. Preserve the exact verified operation and any later correction or missing result in the statement.",
            "Use repository evidence for facts you independently checked against current files. Cite project-relative paths, or an absolute file under the user's evidence.repository_roots. Keep dated accounts as source_report when their external claim is not established.",
            "Each point's review is your content judgment. Fill conditions with necessary literal phrases from the final statement and undecided_state with any explicit still-applicable unresolved state; empty/null only after checking. Runtime binds final text and source/target versions. Do not duplicate review as final_scope_judgment.",
            "For a save or confirmation, bind the claim and each retained condition or undecided state in review.evidence. Each item points to verification_refs by its one-based ref number and quotes a unique, exact supporting span. For a conversation, use the one-based message_index within the cited role of that exchange. For a repository file, omit message_index. For a condition, set target=condition and condition to the exact phrase in review.conditions. Cite only sources that support this point. The runtime checks the bytes and stores a reference; it does not judge that a quoted sentence entails the claim.",
            "For an observed operation in a durable claim, use review.operations with a literal phrase in the output, the claim's one-based ref, call_id, call_line, result_line, and exact call_quote/result_quote. Use inspection for readback, execution for a supported command, and interaction only for an actual UI action. Use the native_evidence reader for the paired records. Retain attributed wording and the known boundary when the action or result is unavailable.",
            "Before drafting points, read the complete conversation and follow native_evidence.review_questions through next_offset=null when offered. Inspect the paired records for relevant questions. Look for validation and rejected inputs, what is kept or retried on failure, and when the behavior applies. Add missed questions from the source yourself. Bind a historical implementation or receipt detail with review.operations observed_as=inspection and keep its answer in the literal output phrase.",
            "If finalization returns source_conditions_need_review, check each cited condition or operational detail in its original scope. Keep applicable steps, responsibilities, and exclusions in the writing point. Use condition_exclusions keyed by the returned id with a concrete reason for an inapplicable, superseded, or session-only clause; then retry this same job.",
            "For refine/replace set review.preserves_meaning=true only after checking all complete targets: preserve still-applicable facts, evidence, causes, conditions, permissions and scope. Source-report replacements also need review.same_topic=true. Unsupported or unclear points stay unfinished.",
            "For each confirm/refine/replace point, select exact current targets yourself and put the array at memory_points[i].target_knowledge, never at the top level of finish. Copy full old title, statement and project_name, and module only when present on the selected row; context does not select ownership.",
            "Merge targeted_point_fragment.memory_points[0] into the complete affected args_template.memory_points[i] and fill the actual checked disposition; do not replace the complete point or put the fragment wrapper inside it. Add points omit target_knowledge.",
        ],
        "required_fields": {
            "arguments": ["job_id", "semantic_review", "memory_points"],
            "memory_point": [
                "content", "canonical_title", "topic_path", "evidence_basis",
                "verification_outcome", "verification_refs", "assimilation_disposition",
            ],
            "semantic_review": [
                name for name, field in SessionSemanticReview.model_fields.items() if field.is_required()
            ],
        },
        "allowed_values": allowed_values,
        "args_template": {
            "job_id": job_id,
            "memory_points": points,
            "semantic_review": {
                "session_summary": "<Source-grounded session summary independent of memory promotion>",
                "final_user_request": "<Actual final user request>",
                "final_outcome": "<Actual supported session outcome>",
                "last_turn_status": "<Choose from allowed_values.last_turn_status>",
                "contradictions": [],
                "unfinished_work": [],
                "evidence_status": "<Choose from allowed_values.evidence_status>",
                "promotion_decision": "<Choose from allowed_values.promotion_decision>",
            },
        },
        "target_knowledge_path": "memory_points[i].target_knowledge",
        "target_knowledge_example": deepcopy(targets),
        "targeted_point_fragment": {
            "memory_points": [{
                "assimilation_disposition": "<Choose the checked confirm/refine/replace disposition>",
                "target_knowledge": deepcopy(targets),
            }],
        },
        "optional_contracts": "SessionSemanticReview and AgentKnowledgeReview define additional review fields.",
    }


def _compact_prepare_result(result: dict[str, Any]) -> dict[str, Any]:
    """Remove protocol duplication, never source text or continuation state."""
    if not result.get("success"):
        return {key: value for key, value in result.items() if key != "finalize_contract"}
    continuation = {
        key: value for key, value in result.items()
        if key in {
            "project_name", "project_root", "distill_job_id", "distill_status",
            "session_id", "source_id", "source_revision", "batch_id",
            "batch_progress", "batch_stopped", "next_after_finalize",
        }
    }
    if result.get("distill_status") == "completed":
        from harness_mem.commands.distill_result import current_distill_result

        backend = _get_backend()
        job = backend.transcript_store.get_distill_job(result["distill_job_id"])
        try:
            if job is None:
                raise ValueError("completed job is missing")
            saved = asyncio.run(current_distill_result(backend, job))
        except ValueError:
            return {
                **continuation, "success": False,
                "error": "current knowledge cannot prove the completion result",
                "reason_codes": ["promotion_write_unreadable"],
            }
        return _compact_finalize_result({**result, **saved})
    compact = {
        key: value for key, value in result.items()
        if key not in {
            "project_resolution_source", "client", "resolved_client", "host_client",
            "source_kind", "adapter_available", "scope", "limit", "ingest",
            "selection_source", "budget_tokens", "structural_checkpoint_summary",
            "distill_instructions", "semantic_decision_exchange_count",
            "zero_candidate_exchange_refs", "zero_candidate_challenge_template",
            "agent_execution", "response_budget", "chunk_count",
            "semantic_drilldown_exchange_count", "raw_drilldown_chunk_count",
            "finalize_contract",
        }
    }
    evidence = result.get("semantic_evidence")
    if isinstance(evidence, dict):
        # Use complete indexed windows once, without their budgeted outline.
        # Earlier assistant messages must also remain readable: the existing
        # window digest covers the final outcome and remains the evidence ref.
        backend = _get_backend()
        observation_id = str(uuid5(NAMESPACE_URL, f"{result['source_id']}:observation"))
        observation = asyncio.run(backend.verbatim_store.get(observation_id))
        if observation is None or observation.metadata.get("source_revision") != result["source_revision"]:
            return {
                **continuation, "success": False,
                "error": "complete semantic evidence is unavailable",
                "reason_codes": ["semantic_evidence_unavailable"],
            }
        count = int(evidence.get("output_exchange_count") or 0)
        windows = _load_distill_exchange_windows(
            backend, source_id=result["source_id"],
            source_revision=result["source_revision"],
            indexes=list(range(1, count + 1)),
        )
        if len(windows) != count:
            return {
                **continuation, "success": False,
                "error": "complete exchange references are unavailable",
                "reason_codes": ["semantic_exchange_refs_incomplete"],
            }
        compact["semantic_evidence"] = {
            key: value for key, value in evidence.items()
            if key in {
                "output_exchange_count", "zero_candidate_required_exchange_indexes",
                "zero_candidate_required_exchange_reasons", "zero_candidate_review_basis",
            }
        }
        _header, exchanges, _summary = _parse_exchanges(observation.raw_content)
        compact["semantic_decision_exchanges"] = [
            {key: value for key, value in window.items()
             if key in {"exchange_index", "content_sha256", "content"}
             or key in {"risk_flags", "memory_signals"} and value}
            for window in windows
        ]
        for window in compact["semantic_decision_exchanges"]:
            preceding = exchanges[window["exchange_index"] - 1]["assistant"][:-1]
            if preceding:
                window["preceding_assistant_messages"] = list(preceding)
        if not count:
            # Parser bodies without exchange boundaries remain fully readable.
            compact["semantic_evidence"].update({
                "content": observation.raw_content,
                "content_sha256": sha256_text(observation.raw_content),
            })
    if not compact.get("chunks"):
        compact.pop("chunks", None)
    if result.get("distill_mode") == "lossless_chunks":
        compact["next_step"] = (
            "checkpoint" if compact.get("chunks")
            else "finish" if result.get("distill_status") == "reviewing"
            else "prepare"
        )
    if (
        compact.get("next_step") == "finish"
        and result.get("evidence_mode") == "semantic"
        and isinstance(evidence, dict)
        and result.get("completed_chunk_count") == result.get("expected_chunk_count")
        and isinstance(result.get("project_name"), str) and result["project_name"].strip()
        and isinstance(result.get("distill_job_id"), str) and result["distill_job_id"].strip()
    ):
        compact["finalize_contract"] = _finalize_call_contract(result["distill_job_id"])
    return compact


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
    observation = load_source_observation_projection(
        backend, source_id=source_id, source_revision=source_revision,
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
    observation = load_source_observation_projection(
        backend, source_id=source_id, source_revision=source_revision,
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
        }
    )


def _checkpoint_distill_structural_projection(
    backend: LocalMemoryBackend,
    *,
    job_id: str,
    source_revision: str,
    semantic_content_sha256: str,
    execution_source: str = "interactive_agent",
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
            execution_source=execution_source,
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
    native_evidence: dict[str, Any] | None = None,
    run_ingest: bool = True,
    defer_job_id: str | None = None,
    defer_reason: str | None = None,
    session_id: str | None = None,
    distill_job_id: str | None = None,
    batch_sessions: list[dict] | None = None,
    batch_id: str | None = None,
    archived_only: bool = False,
    retry_failures: bool = False,
    pause: bool = False,
    continue_batch: bool = False,
    cleanup_processed: bool = False,
    apply_cleanup: bool = False,
    target_knowledge: list[dict[str, Any]] | None = None,
    current_query: str | None = None,
    include_current: bool = False,
    _distill_source: str = "agent",
    _batch_selected: bool = False,
    _native_transcript_path: str | None = None,
) -> dict:
    """Prepare complete evidence for automatic processing or memory review.

    This intentionally stops before synthesis. The model should read the
    returned observations, decide what deserves a pending candidate, then call
    govern_memory(action=suggest). The lower-level sync step may call ingest_sessions.
    Public preparation reviews an existing memory or job, or runs an explicit
    historical batch. Hooks and workers call this shared core directly for daily
    remembering and do not ask users to select sessions.
    """
    if native_evidence is not None:
        # Supplementary evidence is an exact existing-job read. Do not ingest,
        # claim work, checkpoint, or advance a batch just to inspect tool output.
        if (not isinstance(native_evidence, dict) or not distill_job_id
                or session_id or batch_id or batch_sessions is not None or target_knowledge is not None
                or include_current or current_query is not None or defer_job_id or full_rescan
                or pause or continue_batch or retry_failures or cleanup_processed or apply_cleanup
                or archived_only or drilldown_exchange_indexes or drilldown_chunk_indexes or drilldown_query
                or _distill_source != "agent"):
            return {"success": False, "error": "native_evidence requires one existing distill_job_id without a processing action"}
        from harness_mem.adapters.native_tool_evidence import native_tool_evidence
        from harness_mem.adapters.source_inspection import normalized_root

        backend = _get_backend()
        job = backend.transcript_store.get_distill_job(distill_job_id)
        if (job is None or project_name and project_name != job.project_name
                or project_root and normalized_root(project_root) != normalized_root(job.project_root)):
            return {"success": False, "error": "native evidence job is unavailable or outside the selected scope"}
        evidence = native_tool_evidence(backend, job, native_evidence)
        return {"success": evidence["status"] == "read", "distill_job_id": job.id,
                "source_id": job.source_id, "source_revision": job.source_revision,
                "native_evidence": evidence, "processing_unchanged": True}
    if archived_only and (not batch_sessions or batch_id is not None or _distill_source != "agent"):
        return {"success": False, "error": "archived_only requires a new manual batch selection"}
    if cleanup_processed or apply_cleanup:
        # Cleanup is an explicit action on an existing frozen selection. It
        # must never prepare another source or enable automatic processing.
        if (not cleanup_processed or not batch_id or batch_sessions is not None
                or session_id or distill_job_id or target_knowledge is not None
                or include_current or current_query is not None
                or pause or continue_batch or retry_failures
                or _distill_source != "agent"):
            return {"success": False, "error": "cleanup requires cleanup_processed and one existing batch_id, without another processing action"}
        from harness_mem.commands.manual_distill import cleanup_manual_batch
        from harness_mem.commands.session_inventory import resolve_session_scope

        backend = _get_backend()
        try:
            resolved = resolve_session_scope(
                Path(backend.data_dir), project_root=project_root,
                project_name=project_name, batch_id=batch_id,
            )
            if resolved is None:
                raise ValueError("the selected batch has no verified source scope")
            resolved_name, resolved_root = resolved
            return cleanup_manual_batch(
                backend, project_name=resolved_name, project_root=resolved_root,
                batch_id=batch_id, apply=apply_cleanup,
            )
        except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
            return {"success": False, "error": str(exc)}
    if include_current and current_query is not None:
        return {"success": False, "error": "include_current and current_query are mutually exclusive"}
    if current_query is not None:
        options = dict(locals())
        from harness_mem.read_knowledge import search_current_knowledge
        from harness_mem.mcp.read_projection import project_memory_entries

        if not current_query.strip() or not (session_id or distill_job_id) or batch_id or batch_sessions:
            return {"success": False, "error": "current_query requires a nonempty topic and one session or job"}
        backend = _get_backend()
        if backend.runtime_state == "degraded_fallback" or backend.runtime_error:
            return {"success": False, "error": "current memory is unavailable"}
        try:
            current = asyncio.run(search_current_knowledge(
                backend, project_name=project_name if scope == "project" else None,
                query=current_query.strip(),
            ))
            rows = project_memory_entries(current, include_project=True, include_modules=True)
            # Reuse exact current-target ownership and source preparation. This
            # only selects context; every actual replacement still needs an
            # explicit point, exact targets and the existing evidence gate.
            options["current_query"] = None
            if rows and target_knowledge is None:
                options["target_knowledge"] = rows
            result = tool_prepare_session_distill(**options)
        except (OSError, ValueError) as exc:
            return {"success": False, "error": str(exc)}
        return {**result, "current_knowledge": rows, "current_knowledge_query": current_query.strip()}
    if target_knowledge is not None:
        from harness_mem.commands.knowledge_assimilation import resolve_knowledge_target_project

        try:
            owner = asyncio.run(resolve_knowledge_target_project(
                _get_backend().structured_store.knowledge_store, target_knowledge,
            ))
            if project_name and project_name != owner:
                raise ValueError("selected correction target does not match the supplied project")
        except ValueError as exc:
            return {"success": False, "error": str(exc)}
        if batch_id or batch_sessions or not (session_id or distill_job_id):
            return {"success": False, "error": "target_knowledge requires one correction session or job"}
        project_name, scope = owner, "project"
    if (batch_id is not None or batch_sessions is not None or pause or continue_batch
            or (retry_failures and not session_id and not distill_job_id)):
        from harness_mem.commands.manual_distill import prepare_manual_batch
        from harness_mem.commands.session_inventory import resolve_session_scope
        if scope not in {"project", "all"} or session_id or distill_job_id or _distill_source != "agent":
            return {"success": False, "error": "manual batch requires a selected-source scope without another session selector"}
        if (pause or continue_batch) and (batch_sessions is not None or not batch_id):
            return {"success": False, "error": "pause and continue use the existing batch_id only"}
        if sum(bool(flag) for flag in (pause, continue_batch, retry_failures)) > 1:
            return {"success": False, "error": "pause, continue, and retry are separate actions"}
        backend = _get_backend()
        try:
            device_selection = batch_id is None and (scope == "all" or (
                not project_root and not project_name and batch_sessions
                and all(item.get("scope") == "all" for item in batch_sessions)
            ))
            resolved = ("global", None) if device_selection else resolve_session_scope(
                Path(backend.data_dir), project_root=project_root,
                project_name=project_name, sessions=batch_sessions, batch_id=batch_id,
            )
            if resolved is None:
                return {"success": False, "error": "the selected source has no project binding"}
        except (OSError, ValueError, KeyError) as exc:
            return {"success": False, "error": str(exc)}
        resolved_name, resolved_root = resolved
        try:
            return prepare_manual_batch(
                backend, project_name=resolved_name,
                project_root=resolved_root, batch_id=batch_id, sessions=batch_sessions,
                archived_only=archived_only,
                retry_failures=retry_failures, pause=pause, continue_batch=continue_batch,
                prepare=tool_prepare_session_distill,
                prepare_options={"evidence_mode": evidence_mode, "detail_level": detail_level,
                                 "budget_tokens": budget_tokens, "chunk_limit": chunk_limit,
                                 "drilldown_exchange_indexes": drilldown_exchange_indexes,
                                 "drilldown_chunk_indexes": drilldown_chunk_indexes,
                                 "drilldown_query": drilldown_query},
            )
        except (OSError, ValueError, KeyError) as exc:
            return {"success": False, "error": str(exc)}
    if not project_root and not project_name and not (distill_job_id or session_id):
        # A shared MCP server's cwd or active project is not the caller's
        # workspace. Discovery lets the Agent carry native bindings internally.
        from harness_mem.commands.session_inventory import collect_session_inventory
        discovered = collect_session_inventory(Path(_core._observer_data_dir()), lightweight=True).payload()
        return {**discovered, "prepared": False,
                "next_step": "Select the returned native sessions for processing; no project or directory setup is required."}
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
    from harness_mem.commands.session_inventory import discover_session_projects, resolve_session_scope
    backend = _get_backend()
    if target_knowledge is not None and requested_session_id and not requested_job_id:
        from harness_mem.commands.session_inventory import prepare_correction_source

        try:
            assert project_name is not None
            correction_job = prepare_correction_source(
                backend, project_name=project_name, client=normalized_client,
                session_id=requested_session_id, project_root=project_root, run_ingest=run_ingest,
            )
        except (OSError, ValueError, KeyError) as exc:
            return {"success": False, "error": str(exc)}
        requested_job_id = correction_job.id
    if (requested_session_id and scope == "all" and not project_root and not project_name
            and not requested_job_id and run_ingest and not retry_failures and _distill_source == "agent"):
        # A known device session needs the same frozen-source checks as a
        # selected inventory reference, not a whole-device packet in the model.
        from harness_mem.commands.session_inventory import collect_session_inventory

        inventory = collect_session_inventory(
            Path(backend.data_dir), lightweight=True, session_id=requested_session_id,
            clients=None if normalized_client in {"auto", "agent"} else [normalized_client],
        )
        if len(inventory.rows) != 1:
            return {
                "success": False,
                "error": "selected session is unavailable" if not inventory.rows else
                         "session identity is ambiguous; select a host or an inspected source reference",
                "session_id": requested_session_id,
            }
        return tool_prepare_session_distill(
            client=normalized_client, scope="all", batch_sessions=inventory.rows,
            chunk_limit=chunk_limit, evidence_mode=evidence_mode, detail_level=detail_level,
            budget_tokens=resolved_budget_tokens,
            include_current=include_current,
            drilldown_exchange_indexes=requested_exchange_indexes,
            drilldown_chunk_indexes=requested_drilldown_indexes,
            drilldown_query=requested_drilldown_query,
        )
    project_scope: tuple[str, Path | None] | None
    try:
        selected_source_job = backend.transcript_store.get_distill_job(requested_job_id) if requested_job_id else None
        if requested_job_id and selected_source_job is None:
            raise ValueError("selected session task is unavailable")
        if selected_source_job is not None and (not project_root or _batch_selected):
            if project_name and project_name != selected_source_job.project_name:
                raise ValueError("selected job does not match the supplied context")
            project_scope = (selected_source_job.project_name,
                             Path(selected_source_job.project_root) if selected_source_job.project_root else None)
        else:
            project_scope = resolve_session_scope(Path(backend.data_dir), project_name=project_name,
                                                  project_root=project_root)
    except (OSError, ValueError, KeyError) as exc:
        return {"success": False, "error": str(exc)}
    if project_scope is None:
        discovered = discover_session_projects(Path(backend.data_dir))
        discovered["projects"] = [{key: value for key, value in project.items() if key != "sessions"}
                                  for project in discovered["projects"]]
        return {**discovered, "prepared": False,
                "next_step": "Use native project bindings to select sessions; do not ask the user for directories."}
    resolved_project_name, resolved_root = project_scope
    resolved_project_root = str(resolved_root) if resolved_root is not None else ""
    project_resolution_source = "project_root" if project_root else "native_binding"

    from harness_mem.adapters.source_inspection import normalized_root

    def job_in_scope(job: SessionDistillJob | None) -> bool:
        if job is None or job.project_name != resolved_project_name:
            return False
        if normalized_root(job.project_root) != normalized_root(resolved_root or ""):
            return False
        revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
        if revision is None:
            return False
        # Completed source pruning is independently verified by the replay gate.
        if revision.metadata.get("evidence_state") == "source_pruned" and job.status == "completed":
            return True
        return bool(
            revision.project_name == job.project_name
            and revision.client == job.client and revision.session_id == job.session_id
            and normalized_root(revision.project_root) == normalized_root(resolved_root or "")
        )

    # Reject explicit out-of-scope selectors before ingest, leases or recovery.
    for selected_id in (requested_job_id, defer_job_id):
        if selected_id and not job_in_scope(backend.transcript_store.get_distill_job(selected_id)):
            return {"success": False, "error": "selected job does not belong to this source workspace"}

    effective_limit = None if limit is None else max(1, int(limit))
    effective_observation_limit = (
        None if observation_limit is None else max(0, int(observation_limit))
    )

    ingest_payload: dict[str, Any] = {
        "success": True,
        "skipped": True,
        "reason": "run_ingest=false",
    }
    if run_ingest and requested_job_id is None:
        ingest_payload = _ingest_sessions(
            project_name=resolved_project_name,
            client=normalized_client,
            limit=effective_limit,
            full_rescan=full_rescan,
            scope=scope,
            project_root=resolved_project_root,
            session_id=requested_session_id,
            native_transcript_path=_native_transcript_path,
        )

    if requested_job_id:
        selected_job = backend.transcript_store.get_distill_job(requested_job_id)
        if job_in_scope(selected_job):
            assert selected_job is not None
            if _distill_source == "autonomous_worker":
                from harness_mem.commands.manual_distill import is_manual_distill_job

                if is_manual_distill_job(backend, selected_job):
                    return {"success": False, "error": "session belongs to manual processing",
                            "reason_codes": ["manual_session_owned"]}
            elif _distill_source == "agent" and selected_job.status != "completed":
                from harness_mem.commands.manual_distill import paused_batch_error

                paused_error = paused_batch_error(backend, selected_job)
                if paused_error:
                    return {"success": False, "error": paused_error, "reason_codes": [paused_error],
                            "distill_job_id": selected_job.id}
                try:
                    backend.transcript_store.reserve_manual_distill_job(selected_job.id)
                    backend.transcript_store.retain_distill_source(selected_job.id)
                except ValueError as exc:
                    return {"success": False, "error": str(exc), "reason_codes": ["review_already_owned"]}
    deferred_id: str | None = None
    if defer_job_id:
        deferred = backend.transcript_store.get_distill_job(defer_job_id)
        if not job_in_scope(deferred):
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
    if (requested_session_id or requested_job_id) and not _batch_selected:
        recovery_ids = {
            job.id for job in backend.transcript_store.list_distill_jobs(project_name=resolved_project_name)
            if job_in_scope(job)
            and (not requested_job_id or job.id == requested_job_id)
            and (not requested_session_id or job.session_id == requested_session_id)
        }
        backend.transcript_store.reconcile_distill_jobs(
            project_name=resolved_project_name,
            recovery_budget=3,
            job_ids=recovery_ids,
        )
    if requested_session_id:
        matching_jobs = [
            job
            for job in backend.transcript_store.list_distill_jobs(
                project_name=resolved_project_name,
                limit=100_000,
            )
            if job.session_id == requested_session_id and job_in_scope(job)
        ]
        if not matching_jobs:
            return {
                "success": False,
                "error": "session_id is not available for this project",
                "session_id": requested_session_id,
                "ingest": ingest_payload,
                "reason_codes": [
                    str(item.get("code")) for item in ingest_payload.get("error_details", [])
                    if isinstance(item, dict) and item.get("code")
                ] or ["session_source_unavailable"],
            }
        session_job = max(
            [job for job in matching_jobs if job.id == requested_job_id]
            if requested_job_id else matching_jobs,
            key=lambda item: (item.created_at, item.updated_at),
        )
        recheck_pipeline: str | None = None
        if requested_job_id is None:
            if (
                retry_failures and _distill_source == "agent" and session_job.status == "completed"
                and session_job.pipeline_version != _MANUAL_SOURCE_RECHECK_PIPELINE_VERSION
                and not deferred_review(session_job)
                and (session_job.promotion_summary.get("unfinished_work")
                     or session_job.semantic_review.get("unfinished_work"))
            ):
                recheck_pipeline = _MANUAL_SOURCE_RECHECK_PIPELINE_VERSION
            elif _completed_job_requires_signal_gate_recheck(session_job):
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
                manual_recheck=_distill_source == "agent",
            )
            if _distill_source == "agent":
                # A manual evidence retry must not newly authorize source cleanup.
                session_job = backend.transcript_store.retain_distill_source(session_job.id)
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
        not job_in_scope(requested_job)
    ):
        return {
            "success": False,
            "error": "distill_job_id does not belong to this project",
            "distill_job_id": requested_job_id,
        }
    if requested_job and _distill_source == "autonomous_worker":
        from harness_mem.commands.manual_distill import is_manual_distill_job

        if is_manual_distill_job(backend, requested_job):
            return {"success": False, "error": "session belongs to manual processing",
                    "reason_codes": ["manual_session_owned"]}
    deferred = deferred_review(requested_job) if requested_job else {}
    if (requested_job and requested_job.status == "completed" and retry_failures
            and _distill_source == "agent" and not _batch_selected
            and (deferred or (requested_job.pipeline_version != _MANUAL_SOURCE_RECHECK_PIPELINE_VERSION
            and (distill_unfinished_work(requested_job)
                 or _completed_job_requires_signal_gate_recheck(requested_job)
                 or asyncio.run(_completed_promotion_result_error(backend, job=requested_job)) is not None
                 or not _manual_completion_proven(backend, requested_job)
                 or (requested_job.semantic_review.get("last_turn_status") == "unknown"
                     and requested_job.semantic_review.get("promotion_decision") in {"promote", "partial"}
                     and "semantic_review_blocked" in requested_job.completion_reason_codes
                     and requested_job.promotion_summary.get("answer_gate", {}).get("ANSWERED", 0)))))):
        # Retry the selected immutable source, not the newest job sharing its
        # session id. Keep the old receipt and all of its decisions intact.
        selected_source = backend.transcript_store.get_source(requested_job.source_id)
        if selected_source is None or selected_source.source_revision != requested_job.source_revision:
            return {"success": False, "error": "selected source revision is no longer current",
                    "reason_codes": ["source_revision_changed"]}
        from harness_mem.commands.manual_distill import manual_job_guard, paused_batch_error

        guard_error = paused_batch_error(backend, requested_job) or manual_job_guard(backend, requested_job)
        if guard_error:
            return {"success": False, "error": guard_error, "reason_codes": [guard_error]}
        try:
            requested_job = backend.transcript_store.enqueue_distill_job(
                requested_job.source_id,
                pipeline_version=(DEFERRED_REVIEW_PIPELINE + requested_job.id
                                  if deferred else _MANUAL_SOURCE_RECHECK_PIPELINE_VERSION),
                manual_recheck=True,
                expected_revision=requested_job.source_revision,
            )
        except (KeyError, ValueError) as exc:
            return {"success": False, "error": str(exc), "reason_codes": ["manual_source_unavailable"]}
        requested_job = backend.transcript_store.reserve_manual_distill_job(requested_job.id)
        requested_job = backend.transcript_store.retain_distill_source(requested_job.id)
        requested_job_id = requested_job.id
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
        source_cleanup = (
            {"configured": False, "status": "retained", "receipt_id": requested_job.source_cleanup_receipt_id,
             "reason_codes": ["manual_source_retained"]}
            if _distill_source == "agent" else _replay_completed_source_cleanup(backend, job=requested_job)
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
    lossless_jobs = [job for job in lossless_jobs if job_in_scope(job)]
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
        if _distill_source == "agent":
            try:
                lossless_job = backend.transcript_store.reserve_manual_distill_job(lossless_job.id)
                lossless_job = backend.transcript_store.retain_distill_source(lossless_job.id)
            except ValueError as exc:
                return {"success": False, "error": str(exc), "reason_codes": ["review_already_owned"]}
        elif _distill_source == "autonomous_worker":
            from harness_mem.commands.manual_distill import is_manual_distill_job

            if is_manual_distill_job(backend, lossless_job):
                return {"success": False, "error": "session belongs to manual processing",
                        "reason_codes": ["manual_session_owned"]}
        base_payload: dict[str, Any] = {
            "success": True,
            "project_name": resolved_project_name,
            "project_root": resolved_project_root,
            "project_resolution_source": project_resolution_source,
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
        if _distill_source == "agent" and lossless_job.client in {"codex", "codex-archive"}:
            from harness_mem.adapters.native_tool_evidence import native_tool_evidence

            base_payload["native_evidence"] = native_tool_evidence(backend, lossless_job)
        if lossless_job.pipeline_version.startswith(DEFERRED_REVIEW_PIPELINE):
            previous = backend.transcript_store.get_distill_job(
                lossless_job.pipeline_version.removeprefix(DEFERRED_REVIEW_PIPELINE)
            )
            if previous is not None:
                pending = deferred_review(previous).get("resume_deferred", {}).get("pending", [])
                points = [point for point in previous.promotion_summary.get("points") or []
                          if point.get("disposition") in {"defer", "conflict"}]
                for item, point in zip(pending, points):
                    if point.get("handoff_id"):
                        handoff = asyncio.run(backend.structured_store.get_task_handoff(point["handoff_id"]))
                        if (handoff and handoff.project_name == previous.project_name
                                and handoff.context.get("distill_job_id") == previous.id):
                            item["previous_proposal"] = handoff.summary
                base_payload["deferred_review"] = {
                    "pending": pending,
                    "instructions": "Review only unresolved points. Preserve already verified knowledge from the previous review.",
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
                            "Submit the reviewed memory points with the session judgment.",
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
                    "Submit the supported memory points together with the session judgment.",
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
                        "Submit the supported memory points and the session judgment for the selected job.",
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
                "Submit the supported memory points and the session judgment for the selected job.",
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
                    execution_source="interactive_agent" if _distill_source == "agent" else _distill_source,
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
            execution_source="interactive_agent" if _distill_source == "agent" else _distill_source,
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
                    "Checkpoint each chunk after reading it completely.",
                    "Continue the same batch to get the next chunk or the final review.",
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
        observation_root = observation.metadata.get("project_root")
        if not observation_root or normalized_root(observation_root) != normalized_root(resolved_root or ""):
            continue
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
        "project_resolution_source": project_resolution_source,
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
    existing = backend.transcript_store.get_distill_job(job_id)
    from harness_mem.commands.manual_distill import paused_batch_error

    paused_error = paused_batch_error(backend, existing)
    if paused_error:
        return {"success": False, "distill_job_id": job_id, "error": paused_error,
                "reason_codes": [paused_error]}
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
            "Use Distill.prepare with the original batch_id to review the complete session."
            if job.status == "reviewing"
            else "Use Distill.prepare with the original batch_id to read the next chunk."
        ),
    }


def _session_summary_payload(job: SessionDistillJob) -> dict[str, Any]:
    """Return the human-readable result independently from memory promotion."""

    from harness_mem.commands.distill_result import distill_display_review

    review = distill_display_review(job)
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
    final_scope_contract: Any = None,
    agent_reviews: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Delegate manual proposal validation to the existing assimilation owner."""
    topic_judgments = {}
    if final_scope_contract is not None and final_scope_contract is not _FINAL_SCOPE_UNSET:
        for candidate_id in candidate_ids:
            decision = _parse_final_judgment(final_scope_contract, candidate_id)
            if isinstance(decision, dict):
                continue  # The ordinary final-scope gate reports invalid/missing judgments.
            supplied = [verdict.report_topic_judgments for verdict in decision.points
                        if verdict.report_topic_judgments]
            if supplied:
                if any(value != supplied[0] for value in supplied[1:]):
                    raise ValueError("report topic judgments differ between outputs")
                topic_judgments[candidate_id] = supplied[0]
    return await prepare_interactive_assimilation(
        backend,
        project_name=project_name,
        project_root=project_root,
        candidate_ids=candidate_ids,
        topic_judgments_by_candidate=topic_judgments,
        agent_reviews=agent_reviews,
    )


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
        conclusion = "本次未新增或替换长期记忆。"
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
                # Preserve the same verified attribution descriptor used by
                # the evidence summary. Losing it here falsely downgrades a
                # committed report to UNANSWERED in the packet and Note.
                source_report=candidate.source_report,
            )
        )
        if point_result.get("disposition") not in {"add", "refine", "replace"}:
            continue
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
                    fact=readable_knowledge_statement(entry.statement, entry.source_report),
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
        key = evidence_summary_key(evidence)
        admission[key] = admission.get(key, 0) + 1
        candidate = await store.get_candidate(candidate_id)
        subject = separated_evidence_subject(candidate, evidence) if candidate is not None else evidence
        gate[answer_gate_status(subject)] += 1
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
    reviewed_phrases: Mapping[str, list[str]] | None = None,
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
        phrases = set((reviewed_phrases or {}).get(str(point.get("candidate_id")), []))
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
            phrases.difference_update({phrase for phrase in phrases if phrase in entry.statement})
        if phrases:
            return "reviewed_source_detail_missing_from_current_knowledge"
    emit_current_stage("readback_verified", details={"writing_points": len(writing_points)})
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
        reviewed_phrases=job.semantic_review.get("_reviewed_source_phrases"),
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


def _submit_memory_points(
    backend: Any, *, project_name: str, job_id: str,
    points: list[dict[str, Any]], semantic_review: dict,
    _review_lease_owner: str | None = None,
) -> dict:
    """Stage a complete decision batch through the existing candidate owner.

    This is no new truth writer: finalization still owns evidence admission,
    review leases, current-target CAS, source revalidation and readback.
    """
    from harness_mem.mcp.governance_handlers import tool_suggest_memory_entry, _distill_candidate_id
    from harness_mem.commands.knowledge_assimilation import normalize_knowledge_targets
    from harness_mem.core.schemas.assimilation import AgentKnowledgeReview

    job = backend.transcript_store.get_distill_job(job_id)
    digest = hashlib.sha256(json.dumps(points, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()
    if job is not None and job.project_name == project_name and job.status == "completed":
        if job.semantic_review.get("_submitted_memory_points_sha256") != digest:
            raise ValueError("completed memory_points replay differs from the submitted batch")
        # The original core still reopens current truth, retired targets and
        # sources. A lost response must not require staging new candidates.
        return dict(job.semantic_review)
    if job is None or job.project_name != project_name or job.status != "reviewing":
        raise ValueError("memory_points requires this project's prepared reviewing job")
    if job.review_lease_owner and job.review_lease_owner != _review_lease_owner:
        raise ValueError("distill review is already owned")
    if not isinstance(points, list) or any(not isinstance(point, dict) for point in points):
        raise ValueError("memory_points must be an array of point objects")
    SessionSemanticReview.model_validate(semantic_review)
    prepared = []
    agent_reviews: dict[str, dict[str, Any]] = {}
    reviewed_phrases: dict[str, list[str]] = {}
    candidate_ids: set[str] = set()
    source_transcript: str | None = None
    native_trace_material: dict[str, Any] | None = None
    existing_bodies = set()
    if job.pipeline_version.startswith(DEFERRED_REVIEW_PIPELINE):
        existing_bodies = {
            " ".join((entry.source_report.text if entry.source_report else entry.statement).split()).casefold()
            for entry in asyncio.run(backend.structured_store.knowledge_store.list_entries(project_name))
        }
    for point in points:
        args = dict(point)
        agent_review = None
        if "review" in args:
            agent_review = AgentKnowledgeReview.model_validate(args.pop("review"))
            args.setdefault("assimilation_reason", agent_review.reason)
        if (args.get("assimilation_disposition") == "add"
                and " ".join(str(args.get("content") or "").split()).casefold() in existing_bodies):
            raise ValueError("existing knowledge is already saved; review only the unresolved points")
        if (args.get("assimilation_disposition") in {"add", "confirm", "refine", "replace"}
                and args.get("verification_outcome") != "verified"):
            raise ValueError(
                "writing memory_points require verification_outcome='verified' after checking their typed source refs; "
                "not_applicable/unverified/contradicted cannot request add/confirm/refine/replace. "
                "Use an explicit non-writing disposition only when that is your source-supported decision. "
                "No candidates were staged; the prepared job remains open."
            )
        state_item = args.pop("retained_state_item", None)
        if state_item is not None and (
            not isinstance(state_item, str) or not state_item.strip()
            or state_item not in semantic_review.get("unfinished_work", [])
            or state_item != args.get("content")
            or args.get("evidence_basis") != "user_statement"
            or args.get("assimilation_disposition") not in {"add", "confirm", "refine", "replace"}
        ):
            raise ValueError("retained_state_item must exactly match both the verified state content and unfinished_work item")
        if "project_name" in args or "distill_job_id" in args:
            raise ValueError("point ownership comes from the prepared job")
        args.setdefault("source", f"prepared native session {job.session_id}")
        args.setdefault("category", " / ".join(args.get("topic_path") or ["Memory"]))
        args.update(project_name=project_name, distill_job_id=job_id)
        signature(tool_suggest_memory_entry).bind(**args)
        # Parse the whole batch before staging its first candidate. Invalid
        # later points cannot cause any earlier point to be written as truth.
        refs = [EvidenceRef.from_dict(ref) for ref in args.get("verification_refs") or []]
        if not refs or not isinstance(args.get("topic_path"), list):
            raise ValueError("each memory point requires typed evidence refs and a topic_path array")
        if any(ref.bindings for ref in refs):
            raise ValueError("source bindings are derived by the runtime; supply exact quotes in review.evidence")
        if agent_review is not None and (agent_review.evidence is not None or agent_review.operations):
            from harness_mem.commands.manual_condition_review import bind_review_evidence

            if args.get("assimilation_disposition") not in _FINAL_WRITING:
                raise ValueError("review.evidence applies to writing and confirmation points")
            if source_transcript is None:
                observation = load_source_observation_projection(
                    backend, source_id=job.source_id, source_revision=job.source_revision,
                )
                source_transcript = observation.raw_content if observation is not None else ""
            if agent_review.operations and native_trace_material is None:
                from harness_mem.adapters.native_tool_evidence import native_tool_evidence

                trace_ids = {
                    operation["call_id"]
                    for point in points for review in [point.get("review")]
                    if isinstance(review, dict) and isinstance(review.get("operations"), list)
                    for operation in review["operations"]
                    if isinstance(operation, dict) and isinstance(operation.get("call_id"), str)
                }
                native_trace_material = native_tool_evidence(backend, job, trace_ids=trace_ids)
            refs = bind_review_evidence(
                review=agent_review, statement=str(args["content"]).strip(), refs=refs,
                transcript=source_transcript, project_root=job.project_root, native=native_trace_material,
            )
            args["verification_refs"] = refs
        if any(ref.kind == "source_report" and (
            ref.locator is not None or ref.locator_sha256 is not None or ref.chunk_index is not None
        ) for ref in refs):
            raise ValueError(
                "source_report refs use kind, exchange_index, content_sha256 and role from the prepared source; "
                "locator/locator_sha256/chunk_index are not valid for these exchange refs. "
                "Do not put a quoted source passage in locator. "
                "No candidates were staged; correct the refs and retry this prepared job."
            )
        if args.get("target_knowledge") is not None:
            try:
                if not isinstance(args["target_knowledge"], list):
                    raise ValueError("target_knowledge is not an array")
                normalize_knowledge_targets(args["target_knowledge"])
            except (ValueError, TypeError) as exc:
                raise ValueError(
                    "target_knowledge must be an array of old search-result objects, "
                    "e.g. [{title: old_title, statement: old_statement, project_name: owner}]. "
                    "Use statement for the old body, not content; include module only if returned. "
                    "No candidates were staged; correct the target shape and retry this prepared job."
                ) from exc
        candidate_id = _distill_candidate_id(
            backend, project_name=project_name, distill_job_id=job_id,
            candidate_kind="memory", payload={"category": args["category"], "content": args["content"],
                                              "source": args["source"], "tags": args.get("tags") or []},
        )
        if candidate_id in candidate_ids:
            raise ValueError("memory_points contains duplicate candidate identities")
        candidate_ids.add(candidate_id)
        if agent_review is not None:
            agent_reviews[candidate_id] = agent_review.model_dump(mode="json", exclude={"evidence", "operations"})
            if agent_review.evidence is not None:
                reviewed_phrases[candidate_id] = list(dict.fromkeys([
                    *agent_review.conditions, *(item.phrase for item in agent_review.operations),
                    *([agent_review.undecided_state] if agent_review.undecided_state else []),
                ]))
        prepared.append((args, state_item))
    review = dict(semantic_review)
    review["_submitted_memory_points_sha256"] = digest
    review["_memory_point_reviews"] = agent_reviews
    review["_reviewed_source_phrases"] = reviewed_phrases
    state_refs = list(review.get("retained_state_refs") or [])
    for args, state_item in prepared:
        result = tool_suggest_memory_entry(**args)
        if not result.get("success"):
            raise ValueError(str(result.get("error") or "candidate staging failed"))
        if state_item is not None:
            state_refs.append({"candidate_id": result["entry_id"], "unfinished_work_item": state_item})
    from harness_mem.commands.separated_assimilation import retire_pending_extraction_attempt
    if candidate_ids:
        asyncio.run(retire_pending_extraction_attempt(
            backend, project_name=project_name, distill_job_id=job_id,
            keep_candidate_ids=sorted(candidate_ids),
        ))
    review["_submitted_memory_point_ids"] = sorted(candidate_ids)
    if state_refs:
        review["retained_state_refs"] = state_refs
    return review


def _validate_retained_state_refs(
    backend: Any, *, project_name: str, job_id: str, review: dict,
) -> None:
    """A state label cannot suppress an unrelated or unverified work item."""
    if not review.get("retained_state_refs"):
        # Legacy validation and completed-job replay remain owned by the core;
        # a replay intentionally accepts an empty semantic_review.
        return
    parsed = SessionSemanticReview.model_validate(review)
    refs = parsed.model_dump().get("retained_state_refs") or []
    if not refs:
        return
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None or job.project_name != project_name:
        raise ValueError("retained state job is missing or belongs to another project")
    if job.status == "completed":
        if refs != job.semantic_review.get("retained_state_refs"):
            raise ValueError("completed retained-state bindings cannot change")
        return
    store = backend.structured_store.knowledge_store
    for ref in refs:
        if ref["unfinished_work_item"] not in parsed.unfinished_work:
            raise ValueError("retained state must name an existing unfinished_work item")
        candidate = asyncio.run(store.get_candidate(ref["candidate_id"]))
        if (candidate is None or candidate.project_name != project_name
                or candidate.statement != ref["unfinished_work_item"]
                or candidate.assimilation_disposition not in {"add", "confirm", "refine", "replace"}):
            raise ValueError("retained state requires this job's writing or confirmed candidate")
        evidence = asyncio.run(store.list_evidence(candidate.id))
        if not any(item.distill_job_id == job_id and item.evidence_basis == "user_statement"
                   and item.verification_outcome == "verified" for item in evidence):
            raise ValueError("retained state requires a verified user-statement binding to this job")


_FINAL_SCOPE_UNSET = object()
_FINAL_WRITING = frozenset({"add", "refine", "replace", "confirm"})


def _final_scope_contract(review: Mapping[str, Any], explicit: Any) -> Any:
    if explicit is not _FINAL_SCOPE_UNSET:
        return explicit
    if "final_scope_judgment" in review:
        return review.get("final_scope_judgment")
    return _FINAL_SCOPE_UNSET


def _judgment_refusal(code: str, message: str) -> dict[str, str | list[str]]:
    return {"error": message, "reason_codes": [code]}


def _parse_final_judgment(contract: Any, candidate_id: str) -> Any:
    from pydantic import ValidationError

    from harness_mem.autonomous.models import CandidateVerificationDecision

    raw = contract
    if isinstance(raw, dict) and "points" not in raw:
        if candidate_id not in raw:
            return _judgment_refusal(
                "final_scope_judgment_required",
                "final scope judgment is missing; current knowledge was not written",
            )
        raw = raw[candidate_id]
    if isinstance(raw, str):
        return _judgment_refusal(
            "final_scope_proof_string_rejected",
            "a proof string is not a final semantic judgment; current knowledge was not written",
        )
    if raw is None:
        return _judgment_refusal(
            "final_scope_judgment_required",
            "final scope judgment is missing; current knowledge was not written",
        )
    if isinstance(raw, CandidateVerificationDecision):
        return raw
    try:
        return CandidateVerificationDecision.model_validate(raw)
    except (TypeError, ValueError, ValidationError) as exc:
        return _judgment_refusal(
            "final_scope_judgment_rejected",
            f"final knowledge scope judgment rejected the output: {exc}",
        )


def _copy_update_meaning(
    point: dict[str, Any], decision: Any, *, payload: Mapping[str, Any],
) -> None:
    """Copy only the shared verdict proved against the original obligations."""
    from harness_mem.commands.separated_assimilation import (
        judged_update_payload, needs_update_meaning,
    )

    if not needs_update_meaning(payload):
        return
    stamped, blocked = judged_update_payload(payload, decision)
    if blocked:
        raise ValueError(f"final knowledge scope judgment rejected the output: {blocked}")
    for key in ("update_meaning_judgment", "retained_conditions", "undecided_state", "report_preservation_inventory"):
        if key in stamped:
            point[key] = stamped[key]
        else:
            point.pop(key, None)


async def _consume_supplied_final_scope(
    backend: Any,
    *,
    project_name: str,
    project_root: str | None,
    candidate_ids: list[str],
    plan: dict[str, Any],
    contract: Any,
    agent_reviews: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Prove every new writing point before apply, including public omission.

    An explicit null, a proof string, or a negative verdict does not write.
    Source reopen failure is a different reason from a rejected judgment.
    """

    points = list(plan.get("points") or [])
    writing = [
        point for point in points
        if isinstance(point, dict) and str(point.get("disposition") or "") in _FINAL_WRITING
    ]
    from harness_mem.commands.knowledge_assimilation import is_committed_knowledge_point

    uncommitted = []
    for point in writing:
        candidate = await backend.structured_store.knowledge_store.get_candidate(str(point["candidate_id"]))
        if candidate is not None and await is_committed_knowledge_point(
                backend, candidate=candidate, point=point):
            continue
        uncommitted.append(point)
    writing = uncommitted
    if not writing:
        return None
    if contract is _FINAL_SCOPE_UNSET:
        # Internal normalized plans can already carry the actual semantic
        # decisions. A caller's stored proof strings never substitute for one.
        contract = {str(point["candidate_id"]): point["final_scope_judgment"]
                    for point in writing if point.get("final_scope_judgment") is not None}
        if len(contract) != len(writing):
            contract = None
    if contract is None:
        return _judgment_refusal(
            "final_scope_judgment_required",
            "final scope judgment is missing; current knowledge was not written",
        )
    if isinstance(contract, str):
        return _judgment_refusal(
            "final_scope_proof_string_rejected",
            "a proof string is not a final semantic judgment; current knowledge was not written",
        )
    from harness_mem.commands.evidence_admission import reopen_knowledge_sources
    from harness_mem.commands.separated_assimilation import (
        final_scope_payload,
        prepare_separated_assimilation,
        prove_supplied_final_scope,
    )

    try:
        prepared = await prepare_separated_assimilation(
            backend,
            project_name=project_name,
            project_root=project_root or "",
            candidate_ids=candidate_ids,
        )
    except (TypeError, ValueError) as exc:
        return _judgment_refusal("final_scope_judgment_rejected", str(exc))
    store = backend.structured_store.knowledge_store
    for point in writing:
        candidate_id = str(point.get("candidate_id") or "")
        decision = _parse_final_judgment(contract, candidate_id)
        if isinstance(decision, dict):
            return decision
        if str(point.get("disposition") or "") in {"refine", "replace", "confirm"}:
            target_ids = [str(value) for value in point.get("matched_truth_ids") or []]
            if str(point.get("disposition") or "") in {"refine", "replace"} and not target_ids:
                return _judgment_refusal(
                    "native_source_reopen_incomplete",
                    "native source reopen is incomplete; current knowledge was not written",
                )
            for target_id in target_ids:
                sources = await store.list_sources(target_id)
                validation, reopened = await reopen_knowledge_sources(
                    backend,
                    project_name=project_name,
                    sources=sources,
                    project_root=project_root,
                )
                complete = (
                    validation.verification_outcome == "verified"
                    and bool(sources)
                    and len(reopened) == len(sources)
                    and all(item.content and not item.truncated for item in reopened)
                )
                if not complete:
                    # A current, independently quoted user decision can correct
                    # an old ordinary entry after its former evidence changed or
                    # disappeared. Confirmations and source-report revisions
                    # still require their historical source checks. The final
                    # judgment below binds the full old snapshot and its version;
                    # apply revalidates the new evidence before the CAS write.
                    from harness_mem.core.schemas.assimilation import AgentKnowledgeReview

                    checked_review = (agent_reviews or {}).get(candidate_id)
                    checked_review = (AgentKnowledgeReview.model_validate(checked_review)
                                      if checked_review is not None else None)
                    new_evidence = await store.list_evidence(candidate_id)
                    old_entry = await store.get_entry(target_id, project_name=project_name)
                    freshly_supported_correction = bool(
                        str(point.get("disposition")) in {"refine", "replace"}
                        and checked_review is not None and checked_review.support == "supported"
                        and checked_review.preserves_meaning is True
                        and old_entry is not None and old_entry.source_report is None
                        and len(new_evidence) == 1
                        and new_evidence[0].evidence_basis == "user_statement"
                        and new_evidence[0].verification_outcome == "verified"
                        and new_evidence[0].verification_refs
                        and all(ref.kind == "user_statement" and ref.role == "user" and ref.bindings
                                for ref in new_evidence[0].verification_refs)
                        and any(binding.target == "claim" for ref in new_evidence[0].verification_refs
                                for binding in ref.bindings)
                    )
                    if not freshly_supported_correction:
                        return _judgment_refusal(
                            "native_source_reopen_incomplete",
                            "native source reopen is incomplete; current knowledge was not written",
                        )
        try:
            # Current-Agent review can supply the same complete ORIGINAL
            # report inventory used by native final verification. Rebuild it
            # against all current targets below; a supplied hash or one
            # predecessor's inventory cannot certify another predecessor.
            inventories = [verdict.report_preservation_inventory for verdict in decision.points
                           if verdict.report_preservation_inventory is not None]
            if inventories:
                if (any(value != inventories[0] for value in inventories[1:])
                        or point.get("report_preservation_inventory") is not None
                        and point["report_preservation_inventory"] != inventories[0]):
                    raise ValueError("report_original_inventory_binding_changed")
                point["report_preservation_inventory"] = inventories[0]
            payload = final_scope_payload(prepared, point)
            proof = prove_supplied_final_scope(payload=payload, judgment=decision)
            _copy_update_meaning(point, decision, payload=payload)
        except (TypeError, ValueError) as exc:
            text = str(exc)
            if "target snapshot is unavailable" in text:
                return _judgment_refusal("native_source_reopen_incomplete", text)
            return _judgment_refusal("final_scope_judgment_rejected", text)
        evidence_items = await store.list_evidence(candidate_id)
        if len(evidence_items) != 1:
            return _judgment_refusal(
                "final_scope_judgment_rejected",
                "final scope evidence binding is incomplete; current knowledge was not written",
            )
        evidence = evidence_items[0]
        codes = [
            *evidence.verification_reason_codes,
            "autonomous_final_scope_required",
            proof,
            "source_scope_durable",
            "future_scope_durable",
        ]
        for verdict in decision.points:
            codes.append(f"source_use_{verdict.source_use}")
            codes.append(f"future_scope_{verdict.future_scope}")
        evidence.verification_reason_codes = list(dict.fromkeys(str(code) for code in codes))
        await store.save_evidence(evidence)
    return None


def tool_finalize_session_distill(
    project_name: str,
    job_id: str,
    semantic_review: dict,
    _review_lease_owner: str | None = None,
    memory_points: list[dict[str, Any]] | None = None,
    final_scope_judgment: Any = _FINAL_SCOPE_UNSET,
    condition_exclusions: dict[str, str] | None = None,
) -> dict:
    """Finalize one job while recording a content-free diagnostic lifecycle."""
    caller_has_lease = _review_lease_owner is not None
    staging_lease_owner = None

    try:
        early_backend = _get_backend()
        early_job = early_backend.transcript_store.get_distill_job(job_id)
    except Exception:
        early_backend = None
        early_job = None
    if early_job is not None and early_backend is not None:
        from harness_mem.commands.manual_distill import paused_batch_error

        paused_error = paused_batch_error(early_backend, early_job)
        if paused_error:
            return {"success": False, "distill_job_id": job_id, "error": paused_error,
                    "reason_codes": [paused_error]}
        supplied_plan = semantic_review.get("assimilation")
        if (memory_points is not None and not caller_has_lease and isinstance(supplied_plan, dict)
                and not (early_job.status == "completed" and early_job.completion_disposition is None)
                and not asyncio.run(is_committed_job_replay(
                    early_backend, project_name=project_name, distill_job_id=job_id, plan=supplied_plan))):
            # An internal staging lease is concurrency protection, not authority
            # for a caller-supplied plan to discard points and enable cleanup.
            return {"success": False, "distill_job_id": job_id, "error": "trusted_review_lease_required",
                    "reason_codes": ["unleased_assimilation_rejected"]}
    backend = None
    data_dir = DEFAULT_DATA_DIR
    project_root: str | None = None
    try:
        backend = _get_backend()
        data_dir = Path(backend.data_dir)
        job = backend.transcript_store.get_distill_job(job_id)
        if job is not None:
            project_root = job.project_root
    except Exception:
        # The core path remains the authority for its existing error behavior;
        # diagnostics must not turn backend setup failures into new failures.
        backend = None
    diagnostic = DiagnosticRun(
        data_dir,
        operation="distill",
        project_name=project_name,
        project_root=project_root,
        parent_run_id=diagnostic_parent_id(),
        references={"job_id": job_id},
    )
    diagnostic.emit("accepted", "running")
    diagnostic.emit("started", "running")
    result: dict[str, Any]
    native_review_status: dict[str, Any] | None = None
    try:
        with diagnostic.activate_children():
            try:
                if memory_points is not None:
                    if any("review" in point for point in memory_points) and (
                            final_scope_judgment is not _FINAL_SCOPE_UNSET
                            or "final_scope_judgment" in semantic_review
                            or "assimilation" in semantic_review):
                        raise ValueError("use each memory point's review or an existing explicit final plan, not both")
                    if not caller_has_lease and job is not None and job.status == "reviewing":
                        staging_lease_owner = f"interactive:{uuid4()}"
                        claimed = (backend or _get_backend()).transcript_store.claim_distill_review(
                            job_id, lease_owner=staging_lease_owner, execution_source="interactive_agent",
                        )
                        if claimed is None:
                            staging_lease_owner = None
                            raise ValueError("distill review is already running")
                        _review_lease_owner = staging_lease_owner
                        if job.project_name == project_name:
                            from harness_mem.commands.manual_condition_review import review_source_conditions

                            observation = load_source_observation_projection(
                                backend or _get_backend(), source_id=job.source_id,
                                source_revision=job.source_revision,
                            )
                            native_records = None
                            if job.client in {"codex", "codex-archive"} and any(
                                isinstance(point.get("review"), dict) and point["review"].get("evidence")
                                for point in memory_points
                            ):
                                from harness_mem.adapters.native_tool_evidence import native_tool_evidence

                                native_review = native_tool_evidence(
                                    backend or _get_backend(), job, include_records=True,
                                )
                                native_review_status = {
                                    key: native_review[key] for key in ("status", "reason_codes")
                                    if key in native_review
                                }
                                needs_native_operations = any(
                                    isinstance(point.get("review"), dict) and point["review"].get("operations")
                                    for point in memory_points
                                )
                                frozen_evidence_only = all(
                                    point.get("evidence_basis") in {"user_statement", "source_report", "repository"}
                                    for point in memory_points
                                )
                                reasons = set(native_review.get("reason_codes", ()))
                                # Authored quotes bind the immutable transcript, and
                                # repository quotes bind their own file digest. A live
                                # rollout is supplementary material for those claims.
                                # Native operation claims still require its exact
                                # call/result revision to be readable and inactive.
                                if (needs_native_operations and native_review.get("status") != "available"
                                        or not frozen_evidence_only and reasons & {
                                            "native_evidence_source_changed", "native_evidence_source_active",
                                        }
                                        or reasons & {
                                            "native_evidence_binding_changed", "native_evidence_captured_revision_invalid",
                                            "native_evidence_source_excluded", "native_evidence_liveness_unknown",
                                        }):
                                    raise ValueError(native_review["reason_codes"][0])
                                native_records = native_review.get("records")
                            review_source_conditions(
                                revision=job.source_revision,
                                transcript=observation.raw_content if observation is not None else "",
                                project_root=job.project_root, points=memory_points,
                                exclusions=condition_exclusions or {},
                                native_records=native_records,
                            )
                    semantic_review = _submit_memory_points(
                        backend or _get_backend(), project_name=project_name, job_id=job_id,
                        points=memory_points, semantic_review=semantic_review,
                        _review_lease_owner=_review_lease_owner,
                    )
                else:
                    # Reserve the exact-batch receipt to the actual staging
                    # path; an ordinary caller cannot manufacture its proof.
                    semantic_review = {key: value for key, value in semantic_review.items()
                                       if key not in {"_submitted_memory_points_sha256", "_submitted_memory_point_ids",
                                                      "_memory_point_reviews", "_reviewed_source_phrases"}}
                _validate_retained_state_refs(
                    backend or _get_backend(), project_name=project_name, job_id=job_id,
                    review=semantic_review,
                )
            except (ValueError, TypeError, ValidationError) as exc:
                from harness_mem.commands.manual_condition_review import ConditionReviewRequired

                result = {"success": False, "distill_job_id": job_id, "error": str(exc),
                          "reason_codes": ["memory_point_or_state_binding_invalid"]}
                if isinstance(exc, ConditionReviewRequired):
                    result.update(reason_codes=["source_conditions_need_review"], condition_checks=exc.findings,
                                  next_step="Check each source question. Bind retained native details with review.operations and other retained conditions with review.evidence. Supply concrete condition_exclusions for inapplicable, superseded, duplicate or session-only details; retry this job.")
            else:
                result = _tool_finalize_session_distill_core(
                    project_name=project_name,
                    job_id=job_id,
                    semantic_review=semantic_review,
                    _review_lease_owner=_review_lease_owner,
                    _backend=backend,
                    final_scope_judgment=final_scope_judgment,
                )
    except Exception as exc:  # pragma: no cover - defensive wrapper boundary.
        diagnostic.emit(
            "failed",
            "failed",
            error={
                "kind": "distill_exception",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        )
        raise
    finally:
        if staging_lease_owner is not None:
            (backend or _get_backend()).transcript_store.release_distill_review_lease(
                job_id, lease_owner=staging_lease_owner,
            )
    session_id = result.get("session_id")
    if backend is not None and result.get("success") and result.get("distill_status") == "completed":
        from harness_mem.commands.distill_result import current_distill_result

        completed_job = backend.transcript_store.get_distill_job(job_id)
        try:
            if completed_job is None:
                raise ValueError("completed job is missing")
            result.update(asyncio.run(current_distill_result(backend, completed_job)))
            if result.get("knowledge_changes") and int(completed_job.promotion_summary.get("promoted") or 0) > 0:
                # A fresh SQLite + ordinary-search check replaces a redundant
                # Agent round trip, never the existing verification itself.
                readback_error = asyncio.run(_completed_promotion_result_error(
                    backend, job=completed_job,
                ))
                if readback_error is not None:
                    raise ValueError(readback_error)
                result["readback_verified"] = True
        except ValueError:
            result = {"success": False, "project_name": project_name,
                      "distill_job_id": job_id, "distill_status": "completed",
                      "error": "current knowledge cannot prove the completion result",
                      "reason_codes": ["promotion_write_unreadable"]}
    session_summary = result.get("session_summary")
    if isinstance(session_summary, dict):
        session_id = session_id or session_summary.get("session_id")
    references = {
        "job_id": result.get("distill_job_id") or job_id,
        "session_id": session_id,
    }
    references = {key: value for key, value in references.items() if value is not None}
    if result.get("success") and result.get("distill_status") == "completed":
        diagnostic.emit("completed", "completed", references=references)
    elif result.get("success") is False:
        diagnostic.emit(
            "failed",
            "failed",
            references=references,
            error=result.get("error") or result.get("reason_codes"),
        )
    else:
        diagnostic.emit("deferred", "deferred", references=references)
    if backend is not None:
        from harness_mem.commands.manual_distill import record_manual_finalize_failure
        record_manual_finalize_failure(backend, job_id, result)
    # The durable job retains the full packet for Note/recovery readers. MCP
    # callers receive it once at the top level, not again under promotion.
    if "answer_packet" in result and isinstance(result.get("promotion"), dict):
        result = {**result, "promotion": {
            key: value for key, value in result["promotion"].items()
            if key not in {"answer_packet", "readback"}
        }}
    if native_review_status is not None:
        result["native_evidence"] = native_review_status
    return result if caller_has_lease else _compact_finalize_result(result)


def _tool_finalize_session_distill_core(
    project_name: str,
    job_id: str,
    semantic_review: dict,
    _review_lease_owner: str | None = None,
    _backend: Any | None = None,
    final_scope_judgment: Any = _FINAL_SCOPE_UNSET,
) -> dict:
    """Validate, write current knowledge, and finalize one explicit job."""

    backend = _backend or _get_backend()
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None:
        return {
            "success": False,
            "error": "distill job not found",
            "distill_job_id": job_id,
        }
    if job.project_name != project_name:
        return {"success": False, "error": "distill job belongs to another project"}
    if job.retain_source:
        from harness_mem.commands.manual_distill import manual_job_guard
        guard_error = manual_job_guard(backend, job)
        if guard_error:
            return {"success": False, "error": "manual batch must stop before writing", "reason_codes": [guard_error]}
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
    if recovering_completion:
        # Recovery may only replay the review already committed with this job,
        # never accept a replacement plan from the caller without a lease.
        semantic_review = dict(job.semantic_review)
    try:
        SessionSemanticReview.model_validate(semantic_review)
    except (TypeError, ValidationError):
        return {
            "success": False,
            "project_name": project_name,
            "distill_job_id": job.id,
            "distill_status": job.status,
            "error": "session review is incomplete or invalid; no memory was changed",
            "reason_codes": ["semantic_review_invalid"],
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
    if (isinstance(supplied_assimilation, dict) and not _review_lease_owner
            and not recovering_completion and not asyncio.run(is_committed_job_replay(
                backend, project_name=project_name, distill_job_id=job_id,
                plan=supplied_assimilation,
            ))):
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
        if not isinstance(supplied_assimilation, dict):
            reviewed_ids = asyncio.run(separated_job_candidate_ids(
                backend, project_name=project_name, distill_job_id=job_id,
                include_reviewed=True,
            ))
            staged_ids = semantic_review.get("_submitted_memory_point_ids") or []
            fresh_batch = (bool(candidate_ids) and sorted(staged_ids) == sorted(candidate_ids)
                           and bool(semantic_review.get("_submitted_memory_points_sha256")))
            if set(reviewed_ids) - set(candidate_ids) and not fresh_batch:
                return {
                    "success": False, "project_name": project_name,
                    "distill_job_id": job.id, "distill_status": job.status,
                    "error": "prior_review_requires_assimilation_replay",
                    "reason_codes": ["reviewed_candidate_plan_required"],
                    "candidate_ids": reviewed_ids,
                    "next_step": (
                        "Retry with semantic_review.assimilation (separated-v1) "
                        "replaying the exact prior Review points, including original "
                        "reason, knowledge items and matched_truth_ids. The runtime "
                        "must verify the committed change, current knowledge, sources "
                        "and ordinary search; do not create replacement candidates."
                    ),
                }
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
                        final_scope_contract=_final_scope_contract(semantic_review, final_scope_judgment),
                        agent_reviews=semantic_review.get("_memory_point_reviews"),
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
            judgment_error = asyncio.run(
                _consume_supplied_final_scope(
                    backend,
                    project_name=project_name,
                    project_root=job.project_root,
                    candidate_ids=candidate_ids,
                    plan=semantic_review["assimilation"],
                    contract=_final_scope_contract(semantic_review, final_scope_judgment),
                    agent_reviews=semantic_review.get("_memory_point_reviews"),
                )
            )
            if judgment_error is not None:
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
                    "error": judgment_error["error"],
                    "reason_codes": list(judgment_error["reason_codes"]),
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
                    reviewed_phrases=semantic_review.get("_reviewed_source_phrases"),
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
        # All callers persist original project work after actual write/readback
        # checks. The current Agent must not depend on a background-worker step
        # to make a final Note's unfinished actions durable and resumable.
        from harness_mem.commands.distill_result import retained_state_items
        retained_states = retained_state_items(
            semantic_review, (prefinalized_assimilation or {}).get("points") or [],
        )
        original_work = list(dict.fromkeys(
            str(item).strip() for item in semantic_review.get("unfinished_work") or []
            if str(item).strip() and str(item).strip() not in retained_states
        ))
        covered_work: set[str] = set()
        for handoff_id in handoff_ids:
            existing_handoff = asyncio.run(backend.structured_store.get_task_handoff(handoff_id))
            if (existing_handoff is not None and existing_handoff.project_name == project_name
                    and existing_handoff.context.get("distill_job_id") == job.id
                    and existing_handoff.status != "done"):
                covered_work.update(str(item).strip() for item in
                                    existing_handoff.next_steps or [existing_handoff.summary])
        original_work = [item for item in original_work if item not in covered_work]
        if original_work:
            from harness_mem.mcp.governance_handlers import tool_create_task_handoff
            try:
                saved = tool_create_task_handoff(
                    project_name=project_name, task_id=f"distill-follow-up-{job.id}",
                    summary=str(semantic_review.get("final_outcome") or "Original session follow-up").strip()[:1000],
                    status="in_progress", next_steps=original_work, blockers=[], distill_job_id=job.id,
                )
                handoff = asyncio.run(backend.structured_store.get_task_handoff(saved["handoff_id"]))
                if (not saved.get("success") or handoff is None
                        or handoff.project_name != project_name
                        or handoff.context.get("distill_job_id") != job.id
                        or handoff.next_steps != original_work or handoff.status != "in_progress"):
                    raise ValueError("unfinished_handoff_readback_failed")
            except (OSError, ValueError, KeyError, sqlite3.Error):
                if interactive_lease:
                    backend.transcript_store.release_distill_review_lease(job_id, lease_owner=_review_lease_owner)
                return {"success": False, "project_name": project_name,
                        "distill_job_id": job.id, "distill_status": job.status,
                        "error": "Unfinished work could not be saved; the source is retained. Verified knowledge may already be saved.",
                        "reason_codes": ["unfinished_handoff_not_saved"], "unfinished_work": original_work}
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
        "readback": {"verified": True, "source_revision": completed.source_revision,
                     "mode": "current_knowledge" if promotion_counts.get("promoted") else "no_write",
                     "handoff_ids": asyncio.run(_distill_job_handoff_ids(backend, project_name=project_name, distill_job_id=completed.id))},
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
    unfinished_work = asyncio.run(_distill_job_unfinished_work(backend, completed))
    if unfinished_work:
        promotion["unfinished_work"] = unfinished_work
    disposition = (
        "promoted" if promotion["promoted"]
        else "deferred" if promotion.get("deferred")
        else "conflict" if promotion.get("conflict")
        else "handoff" if promotion["readback"]["handoff_ids"]
        else "no_candidate"
    )
    challenge_passed = bool(
        not candidate_ids
        and completed.zero_candidate_challenge_version == "v1"
        and completed.semantic_review.get("zero_candidate_challenge")
    )
    reason_codes = (
        ["durable_memory_promoted"]
        if disposition == "promoted"
        else ["unresolved_work_preserved"] if disposition in {"deferred", "conflict", "handoff"}
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
            else [_source_retention_reason(completed)]
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

    if getattr(job, "retain_source", False):
        return False
    summary = getattr(job, "promotion_summary", {}) or {}
    review = getattr(job, "semantic_review", {}) or {}
    points = [*(summary.get("points") or []), *((review.get("assimilation") or {}).get("points") or [])]
    if any(point.get("disposition") in {"defer", "conflict"} for point in points):
        return False
    return bool(
        getattr(job, "review_execution_source", None) == "interactive_agent"
        or getattr(job, "client", None) == "codex-archive"
    )


def _source_retention_reason(job: Any) -> str:
    if getattr(job, "retain_source", False):
        return "manual_batch_keeps_source"
    if (getattr(job, "review_execution_source", None) == "interactive_agent"
            or getattr(job, "client", None) == "codex-archive"):
        return "unresolved_work_keeps_source"
    return "dream_keeps_source"


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
            "reason_codes": [_source_retention_reason(job)],
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


async def _distill_job_unfinished_work(backend: LocalMemoryBackend, job: SessionDistillJob) -> list[str]:
    """Read only this project's active job-bound handoffs before making the Note."""
    work: list[str] = []
    for handoff_id in job.promotion_summary.get("readback", {}).get("handoff_ids") or await _distill_job_handoff_ids(
        backend, project_name=job.project_name, distill_job_id=job.id
    ):
        handoff = await backend.structured_store.get_task_handoff(handoff_id)
        if (handoff is None or handoff.project_name != job.project_name
                or handoff.context.get("distill_job_id") != job.id
                or handoff.status == "done"):
            continue
        work.extend(handoff.next_steps or [handoff.summary])
    return list(dict.fromkeys(str(item).strip() for item in work if str(item).strip()))


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
        # A complete source and explicit no-write review already settle the
        # ordinary case. Do not require another eight-way questionnaire just
        # to finish a session that contributes no durable knowledge.
        if semantic_review.get("promotion_decision") == "no_promotion":
            return None
        if (semantic_review.get("promotion_decision") == "partial"
                and semantic_review.get("unfinished_work")):
            # Complete source review may produce only original-task follow-up.
            # The common finalizer persists and reads back that handoff before
            # completing the job; it need not invent a durable memory candidate.
            return None
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
    # A partial session may describe replaced plans or other historical
    # contradictions while still containing an independently ANSWERED
    # candidate. The candidate's own evidence envelope decides admission;
    # session-level contradictions continue to block Dream/full promotion.
    return bool(
        decision in {"promote", "partial"}
        and review.get("evidence_status") in {"answered", "partial"}
        # An unknown final reply does not invalidate an independently verified
        # user decision earlier in a complete source. Dream remains stricter.
        and review.get("last_turn_status") in {"answered", "unfinished", "unknown"}
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
