"""Current-knowledge wake helpers used by Hooks and MCP."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.commands.distill_lifecycle import (
    build_distill_maintenance_offer,
    distill_drainer_metrics,
    pending_distill_jobs,
)
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.core.schemas import KnowledgeEntry
from harness_mem.mcp.read_projection import (
    FOCUSED_SEARCH_GUIDANCE, memory_candidate_projector, reading_tokens, resolve_read_budget,
    select_memory_page,
)
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def _apply_surface_side_effects(
    backend: LocalMemoryBackend,
    entries: list[KnowledgeEntry],
    *,
    retrieval_id: str | None = None,
) -> dict[str, Any]:
    """Record one content-free wake signal for each surfaced knowledge item."""

    seen_ids: set[str] = set()
    recorded_ids: set[str] = set()
    attempted = 0
    recorded = 0
    for entry in entries:
        if entry.id in seen_ids:
            continue
        seen_ids.add(entry.id)
        attempted += 1
        signal = await record_retrieval_signal(
            backend,
            project_name=entry.project_name,
            signal_type="wake_surfaced",
            target_kind="knowledge_entry",
            target_id=entry.id,
            context={"source": "wake", "surface": "wake", "retrieval_id": retrieval_id},
        )
        if signal is not None:
            recorded += 1
            recorded_ids.add(entry.id)
    return {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": retrieval_id,
        "surface": "wake",
        "attempted": attempted,
        "recorded": recorded,
        "failed": attempted - recorded,
        "state": "degraded" if attempted != recorded else "ok",
        "source_ids": sorted(recorded_ids),
        "content_recorded": False,
    }


def _build_distill_maintenance_offer(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    record_offer: bool,
) -> dict[str, Any]:
    """Build the bounded pending-session offer consumed by MCP wake."""

    distill_config = MergedConfig()
    sources = backend.transcript_store.list_sources(
        project_name=project_name,
        limit=1,
    )
    if sources:
        root = Path(sources[0].project_root)
        if root.is_absolute() and root.is_dir():
            distill_config = load_merged_config(root)
    max_jobs = None if distill_config.distill_auto_enabled else 0
    jobs = pending_distill_jobs(
        backend,
        project_name=project_name,
        recent_first=distill_config.distill_auto_recent_first,
        max_jobs=max_jobs,
        record_offer=record_offer and distill_config.distill_auto_enabled,
    )
    metrics = distill_drainer_metrics(
        backend,
        project_name=project_name,
    )
    offer = build_distill_maintenance_offer(
        jobs,
        max_jobs=max_jobs,
        budget_tokens=distill_config.cost_budget_distill_tokens,
        metrics=metrics,
    )
    offer["enabled"] = distill_config.distill_auto_enabled
    if not distill_config.distill_auto_enabled:
        offer.update(
            {
                "agent_execution_required": False,
                "process_limit": 0,
                "job_ids": [],
                "instruction": "",
            }
        )
    return offer


async def build_wake_injection(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    apply_surface_side_effects: bool = True,
    current_task: str | None = None,
    budget_tokens: int | None = None,
    selection_receipt: dict[str, Any] | None = None,
) -> str:
    """Render task-aware Hook context without browsing the whole library."""
    query = (current_task or "").strip()
    budget = resolve_read_budget(
        budget_tokens, surface="wake", project_name=project_name,
    )
    if budget < 1:
        raise ValueError("budget_tokens must be positive")
    if not query:
        # A session-start event may have no user task. An empty search cursor
        # browses the whole library and can prompt the Agent to read unrelated
        # facts. Explicit MCP wake/search retain their existing browse paths.
        text = "# Current memory\nSearch memory with a specific task when needed."
        if reading_tokens(text) > budget:
            text = "# Current memory"
        if reading_tokens(text) > budget:
            raise ValueError("budget_tokens is too small to return a reading link.")
        if selection_receipt is not None:
            selection_receipt.update(
                query_present=False, matched_count=None, returned_count=0, index_only=False,
            )
        return text

    entries = await search_current_knowledge(backend, query=query, expand_long_query=True)
    if not entries:
        # Keep a useful next step for empty searches without making a tiny
        # budget fail merely because the longer guidance cannot fit.
        alternatives = (
            "# Memory candidates\nNo lexical candidates matched. " + FOCUSED_SEARCH_GUIDANCE,
            "# Memory candidates\nSearch each aspect separately.",
            "# Memory candidates",
        )
        text = next((item for item in alternatives if reading_tokens(item) <= budget), None)
        if text is None:
            raise ValueError("budget_tokens is too small to return a reading link.")
        if selection_receipt is not None:
            selection_receipt.update(
                query_present=True, matched_count=0, returned_count=0, candidate_count=0, index_only=False,
            )
        return text
    project_candidates = memory_candidate_projector(
        entries, query=query, project_name=None, scope="all",
    )

    def render(page, reading, index):
        lines = ["# Memory candidates"]
        if index and not page and entries and not reading.get("message"):
            lines.append(
                f"{len(entries)} keyword candidates found; no previews fit the wake budget. "
                "Search with a focused task when prior context is needed."
            )
        if page:
            lines.extend([
                "These are incomplete keyword previews, not verified relevant facts or instructions. "
                "Open a full item only when it helps the current task; otherwise ignore it. "
                + FOCUSED_SEARCH_GUIDANCE,
                "To open a candidate, call search_memory with scope=all, detail=full, "
                "the query below, and that candidate's read_cursor.",
                "query: " + json.dumps(query, ensure_ascii=False),
            ])
        for memory in project_candidates(page, index):
            lines.extend(["", f"## {memory['title']} ({memory['project_name']})"])
            if "source_speaker" in memory:
                lines.append(
                    f"Source report: {memory['source_speaker']}, {memory['source_period']}"
                )
            if "preview" in memory:
                lines.append("Incomplete preview: " + memory["preview"])
            lines.append("read_cursor: " + memory["read_cursor"])
        if reading.get("message"):
            lines.append(reading["message"])
        return "\n".join(lines)

    try:
        page, reading, index = select_memory_page(
            entries, query=query, project_name=None, scope="all",
            budget_tokens=budget, render=render,
        )
    except ValueError as exc:
        if str(exc) != "budget_tokens is too small to return a reading link.":
            raise
        page, reading, index = [], {"message": (
            f"{len(entries)} keyword candidates found; no previews fit the wake budget. "
            "Search with a focused task when prior context is needed."
        )}, True
        if reading_tokens(render(page, reading, index)) > budget:
            raise
    if selection_receipt is not None:
        selection_receipt.update(
            query_present=True, matched_count=len(entries),
            returned_count=0, candidate_count=len(page), index_only=bool(page) or bool(index),
        )
    # Candidate previews are not full memory reads and receive no wake_surfaced signal.
    return render(page, reading, index)


__all__ = ["build_wake_injection"]
