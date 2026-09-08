"""Current-knowledge wake helpers used by Hooks and MCP."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness_mem.commands.distill_lifecycle import (
    build_distill_maintenance_offer,
    distill_drainer_metrics,
    pending_distill_jobs,
)
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas.context_assembly_plan import ContextAssemblyPlan, LayerId
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


_SURFACED_LAYERS: tuple[LayerId, ...] = ("L0", "L1", "L2")
_SIGNAL_TARGET_BY_WHY = {
    "essential:current_knowledge": "knowledge_entry",
    "active:recently_surfaced": "knowledge_entry",
}


async def _apply_surface_side_effects(
    backend: LocalMemoryBackend,
    plan: ContextAssemblyPlan,
    *,
    retrieval_id: str | None = None,
) -> dict[str, Any]:
    """Record one content-free wake signal for each surfaced knowledge item."""

    seen_ids: set[str] = set()
    recorded_ids: set[str] = set()
    attempted = 0
    recorded = 0
    for layer_id in _SURFACED_LAYERS:
        layer = plan.layer(layer_id)
        entries = layer.entries
        if layer_id in {"L1", "L2"}:
            entries = [
                entry
                for entry in entries
                if entry.truth_status == "confirmed_current"
            ]
        for entry in entries[: layer.budget.max_entries]:
            target_kind = _SIGNAL_TARGET_BY_WHY.get(entry.why_included)
            if target_kind is None:
                continue
            record_id = next(
                (source_id for source_id in entry.source_ids if source_id),
                "",
            )
            if not record_id or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            attempted += 1
            signal = await record_retrieval_signal(
                backend,
                project_name=plan.project_name,
                signal_type="wake_surfaced",
                target_kind=target_kind,
                target_id=record_id,
                context={
                    "source": "wake",
                    "surface": "wake",
                    "retrieval_id": retrieval_id,
                },
            )
            if signal is not None:
                recorded += 1
                recorded_ids.add(record_id)
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
) -> str:
    """Return only current knowledge for the host session-start Hook."""

    plan = await assemble_context_plan(backend, project_name=project_name)
    if apply_surface_side_effects:
        await _apply_surface_side_effects(backend, plan)
    return await backend.structured_store.knowledge_store.render_markdown(
        project_name,
        include_details=False,
    )


__all__ = ["build_wake_injection"]
