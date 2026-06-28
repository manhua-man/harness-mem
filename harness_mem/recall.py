"""Explainable recall result builders.

The builders here wrap existing harness-mem retrieval outputs. They do not
perform storage reads or ranking themselves; callers pass the already selected
items and this module creates a stable, inspectable response contract.
"""

from __future__ import annotations

from typing import Any

from harness_mem.core.schemas.recall_result import (
    RecallEvidence,
    RecallPlanning,
    RecallResult,
    RecallSource,
    RecallStep,
    validate_recall_effort,
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _status_from_counts(*counts: int, answer_ready: bool = False) -> str:
    total = sum(max(0, count) for count in counts)
    if total == 0:
        return "empty"
    return "answered" if answer_ready else "partial"


def _entry_excerpt(row: dict[str, Any]) -> str:
    return _text(row.get("content") or row.get("evidence") or row.get("preview"))[:500]


def _metadata_with_score_details(
    row: dict[str, Any],
    base: dict[str, Any],
) -> dict[str, Any]:
    metadata = dict(base)
    score_details = row.get("score_details")
    if isinstance(score_details, dict) and score_details:
        metadata["score_details"] = dict(score_details)
    return metadata


def _evidence_from_search_rows(
    *,
    memory_entries: list[dict[str, Any]],
    relation_facts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
) -> list[RecallEvidence]:
    evidence: list[RecallEvidence] = []
    for row in memory_entries:
        evidence.append(
            RecallEvidence(
                source_id=_text(row.get("id")),
                source_kind="memory_entry",
                content_excerpt=_entry_excerpt(row),
                title=_text(row.get("category")),
                score=_float_or_none(row.get("score")),
                reason="search_memory:memory_entry",
                truth_status=_text(row.get("truth_status") or "confirmed_current"),
                source_ref=_text(row.get("source")),
                metadata=_metadata_with_score_details(
                    row,
                    {
                        "memory_type": row.get("memory_type"),
                        "confidence": row.get("confidence"),
                        "valid_to": row.get("valid_to"),
                    },
                ),
            )
        )
    for row in relation_facts:
        evidence.append(
            RecallEvidence(
                source_id=_text(row.get("id")),
                source_kind="relation_fact",
                content_excerpt=_entry_excerpt(row),
                title=(
                    f"{_text(row.get('source_entity'))} --"
                    f"{_text(row.get('relation_type'))}-> {_text(row.get('target_entity'))}"
                ),
                score=_float_or_none(row.get("score")),
                reason="search_memory:relation_fact",
                truth_status=_text(row.get("truth_status") or "confirmed_current"),
                source_ref=_text(row.get("source")),
                metadata=_metadata_with_score_details(
                    row,
                    {
                        "relation_type": row.get("relation_type"),
                        "confidence": row.get("confidence"),
                        "valid_to": row.get("valid_to"),
                    },
                ),
            )
        )
    for row in observations:
        evidence.append(
            RecallEvidence(
                source_id=_text(row.get("id")),
                source_kind="observation",
                content_excerpt=_entry_excerpt(row),
                score=_float_or_none(row.get("score")),
                reason="search_memory:observation",
                truth_status="raw_evidence",
                source_ref=_text(row.get("session_id")),
                metadata=_metadata_with_score_details(
                    row,
                    {"content_type": row.get("content_type")},
                ),
            )
        )
    return [item for item in evidence if item.source_id]


def _sources_from_drilldown_hints(hints: list[dict[str, Any]]) -> list[RecallSource]:
    sources: list[RecallSource] = []
    seen: set[tuple[str, str]] = set()
    for hint in hints or []:
        source_id = _text(hint.get("source_id"))
        read_surface = _text(hint.get("read_surface"))
        if not source_id:
            continue
        key = (source_id, read_surface)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            RecallSource(
                source_id=source_id,
                source_kind=_text(hint.get("source_kind") or "unknown"),
                read_surface=read_surface,
                locator=dict(hint.get("locator") or {}),
                label=_text(hint.get("why") or hint.get("why_included")),
                metadata={
                    key: value
                    for key, value in hint.items()
                    if key not in {"source_id", "source_kind", "read_surface", "locator"}
                },
            )
        )
    return sources


def _stage_status(ran: bool, result_count: int = 0) -> str:
    if not ran:
        return "skipped"
    return "ok" if result_count else "empty"


def _search_steps(
    *,
    project_name: str | None,
    effective_query: str,
    requested_mode: str,
    effective_mode: str,
    evidence_count: int,
    counts: tuple[int, int, int],
    context: dict[str, Any] | None,
    warnings: list[str] | None,
) -> list[RecallStep]:
    memory_count, relation_count, observation_count = counts
    vector_ran = effective_mode == "hybrid"
    vector_requested = requested_mode in {"auto", "hybrid"}
    fallback_reason = next((warning for warning in warnings or [] if warning), None)
    return [
        RecallStep(
            tier="filter",
            query=effective_query,
            status="ok",
            result_count=evidence_count,
            why="Applied project/scope/current-truth filters before ranking.",
            metadata={
                "project_name": project_name,
                "current_only_default": True,
            },
        ),
        RecallStep(
            tier="fts",
            query=effective_query,
            status=_stage_status(True, evidence_count),
            result_count=evidence_count,
            why="Full-text ranking was available for the SQLite read model.",
            metadata={
                "requested_mode": requested_mode,
                "effective_mode": effective_mode,
            },
        ),
        RecallStep(
            tier="vector",
            query=effective_query,
            status=_stage_status(vector_ran, evidence_count),
            result_count=evidence_count if vector_ran else 0,
            why=(
                "Vector ranking contributed to hybrid retrieval."
                if vector_ran
                else "Vector ranking was skipped or fell back to FTS."
            ),
            metadata={
                "requested": vector_requested,
                "fallback_reason": fallback_reason,
            },
        ),
        RecallStep(
            tier="merge",
            query=effective_query,
            status=_stage_status(evidence_count > 0, evidence_count),
            result_count=evidence_count,
            why="Merged selected source kinds into one recall evidence list.",
            metadata={
                "memory_entry_count": memory_count,
                "relation_fact_count": relation_count,
                "observation_count": observation_count,
            },
        ),
        RecallStep(
            tier="hydrate",
            query=effective_query,
            status=_stage_status(evidence_count > 0, evidence_count),
            result_count=evidence_count,
            why="Hydrated selected source ids into legacy response arrays.",
        ),
        RecallStep(
            tier="context",
            query=effective_query,
            status="ok" if context else "skipped",
            result_count=len((context or {}).get("context_plan", {}).get("layers", [])),
            why=(
                "L0-L4 context assembly explains selected project context."
                if context
                else "No project-scoped context assembly was available."
            ),
        ),
    ]


def build_search_recall_result(
    *,
    project_name: str | None,
    query: str,
    effective_query: str,
    requested_mode: str,
    effective_mode: str,
    memory_entries: list[dict[str, Any]],
    relation_facts: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    drilldown_hints: list[dict[str, Any]],
    context: dict[str, Any] | None,
    answer_ready_context: dict[str, Any] | None,
    warnings: list[str] | None = None,
    effort: str = "dynamic",
) -> RecallResult:
    evidence = _evidence_from_search_rows(
        memory_entries=memory_entries,
        relation_facts=relation_facts,
        observations=observations,
    )
    answer_ready = bool((answer_ready_context or {}).get("safe_to_answer"))
    counts = (len(memory_entries), len(relation_facts), len(observations))
    steps = _search_steps(
        project_name=project_name,
        effective_query=effective_query,
        requested_mode=requested_mode,
        effective_mode=effective_mode,
        evidence_count=len(evidence),
        counts=counts,
        context=context,
        warnings=warnings,
    )
    return RecallResult(
        answer=None,
        why=(
            f"Selected {len(evidence)} evidence item(s) for query {query!r} "
            f"using {effective_mode} retrieval."
        ),
        evidence=evidence,
        sources=_sources_from_drilldown_hints(drilldown_hints),
        steps=steps,
        planning=RecallPlanning(
            selected_effort=validate_recall_effort(effort),
            reason="Wrap existing harness-mem search/context outputs in an auditable contract.",
            expected_shape={
                "memory_entry_count": len(memory_entries),
                "relation_fact_count": len(relation_facts),
                "observation_count": len(observations),
            },
        ),
        tier_path=[step.tier for step in steps if step.status != "skipped"],
        status=_status_from_counts(*counts, answer_ready=answer_ready),
        warnings=list(warnings or []),
        drilldown_hints=list(drilldown_hints or []),
        context=context,
        metadata={
            "project_name": project_name,
            "query": query,
            "effective_query": effective_query,
            "source_surface": "search_memory",
            "answer_ready_context": answer_ready_context,
        },
    )


def build_trace_recall_result(
    *,
    project_name: str,
    source_entity: str,
    relation_type: str | None,
    paths: list[dict[str, Any]],
    effort: str = "medium",
) -> RecallResult:
    evidence: list[RecallEvidence] = []
    sources: list[RecallSource] = []
    for path_index, path in enumerate(paths, start=1):
        for edge in path.get("edges") or []:
            edge_id = _text(edge.get("id"))
            if not edge_id:
                continue
            evidence.append(
                RecallEvidence(
                    source_id=edge_id,
                    source_kind="relation_fact",
                    content_excerpt=_text(edge.get("evidence")),
                    title=(
                        f"{_text(edge.get('source_entity'))} --"
                        f"{_text(edge.get('relation_type'))}-> {_text(edge.get('target_entity'))}"
                    ),
                    score=_float_or_none(edge.get("edge_score") or edge.get("score")),
                    reason=f"trace_relations:path_{path_index}",
                    truth_status=_text(edge.get("truth_status") or "confirmed_current"),
                    source_ref=_text(edge.get("source")),
                    metadata={
                        "path_index": path_index,
                        "path_score": path.get("score"),
                        "relation_family": edge.get("relation_family"),
                    },
                )
            )
            sources.append(
                RecallSource(
                    source_id=edge_id,
                    source_kind="relation_fact",
                    read_surface="mcp.trace_relations",
                    label=f"path {path_index}",
                    metadata={"entities": path.get("entities")},
                )
            )
    return RecallResult(
        why=(
            f"Traced {len(paths)} relation path(s) from {source_entity!r}"
            + (f" filtered by {relation_type!r}." if relation_type else ".")
        ),
        evidence=evidence,
        sources=sources,
        steps=[
            RecallStep(
                tier="relation_trace",
                query=source_entity,
                status="ok",
                result_count=len(paths),
                why="Bounded typed-edge traversal over accepted relation facts.",
                metadata={"relation_type": relation_type},
            )
        ],
        planning=RecallPlanning(
            selected_effort=validate_recall_effort(effort),
            reason="Use typed relation edges when the question asks for dependency, cause, or history.",
            expected_shape={"source_entity": source_entity, "relation_type": relation_type},
        ),
        tier_path=["relation_trace"],
        status="partial" if paths else "empty",
        metadata={
            "project_name": project_name,
            "source_surface": "trace_relations",
            "source_entity": source_entity,
        },
    )


__all__ = ["build_search_recall_result", "build_trace_recall_result"]
