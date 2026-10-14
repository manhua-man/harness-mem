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
from harness_mem.mcp.read_projection import project_memory_entries, resolve_read_budget, select_memory_page
from harness_mem.read_knowledge import list_current_knowledge, search_current_knowledge
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
) -> str:
    """Render the same task-aware current-knowledge selection used by MCP."""
    query = (current_task or "").strip()
    entries = (
        await search_current_knowledge(backend, query=query)
        if query else await list_current_knowledge(backend)
    )

    def render(page, reading, index):
        lines = ["# Current memory"]
        if "available_count" in reading:
            lines.append(
                f"{reading['available_count']} current memories available. "
                "Use search_memory with the current task to find relevant knowledge."
            )
        for memory in project_memory_entries(page, include_project=True):
            lines.extend(["", f"## {memory['title']} ({memory['project_name']})"])
            if not index:
                lines.append(memory["statement"])
        if reading.get("message"):
            lines.append(reading["message"])
        if reading.get("continuation"):
            call = reading["continuation"]
            lines.extend([
                "", "Continue reading: " + call["tool"] + " "
                + json.dumps(call["arguments"], ensure_ascii=False),
            ])
        return "\n".join(lines)

    page, reading, index = select_memory_page(
        entries, query=query, project_name=None, scope="all",
        budget_tokens=resolve_read_budget(
            budget_tokens, surface="wake", project_name=project_name,
        ),
        availability_only=not query, render=render,
    )
    if apply_surface_side_effects and not index and page:
        await _apply_surface_side_effects(backend, page)
    return render(page, reading, index)


__all__ = ["build_wake_injection"]
