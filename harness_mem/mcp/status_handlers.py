"""Project-status MCP handlers.

The public status contract remains assembled by ``tool_handlers``; this module
owns workspace bootstrap, runtime health aggregation, and compact/full views.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
from pathlib import Path
from typing import Any

from harness_mem.commands import support as _support
from harness_mem.commands.integration_cmds import SUPPORTED_HOOK_CLIENTS
from harness_mem.commands.distill_lifecycle import distill_drainer_metrics
from harness_mem.commands.support import (
    find_project_root,
    get_active_project,
    normalize_client_name,
    resolve_project_context,
    set_active_project,
)
from harness_mem.guided_flow import build_guided_flow, guided_flow_drilldown_hint
from harness_mem.governance_status import TRUTH_LAYER_STATUSES
from harness_mem.integration_health import build_integration_health
from harness_mem.mcp.read_handlers import (
    _action,
    _is_historical_truth,
    _is_superseded_truth,
    _retrieval_profile_status,
)
from harness_mem.mcp.response_views import (
    STATUS_CONTRACT_VERSION,
    STATUS_DETAIL_LEVELS,
    build_status_dx_metadata,
    render_project_status,
    status_triage_hints,
)
from harness_mem.runtime_cost import cost_budget_policy, surface_cost_report
from harness_mem.runtime_health import runtime_health_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.version import runtime_version_payload

from .handler_facade_proxy import tool_handlers_facade as _core


def cmd_install_hook_suite(*args, **kwargs):
    """Dispatch through the facade so existing monkeypatch/import seams remain stable."""
    return _core.cmd_install_hook_suite(*args, **kwargs)


def _get_backend():
    return _core._get_backend()


def _observer_data_dir():
    return _core._observer_data_dir()


def _cost_surface_budgets(project_name):
    return _core._cost_surface_budgets(project_name)


async def _gather_project_status(
    backend: LocalMemoryBackend, project_name: str
) -> dict[str, Any]:

    observations = await backend.verbatim_store.list(limit=100000)
    project_observations = [
        observation
        for observation in observations
        if observation.metadata.get("project_name") == project_name
    ]
    memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
    )
    all_memory_entries = await backend.structured_store.list_memory_entries(
        project_name,
        limit=100000,
        include_history=True,
    )
    handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=5)
    confirmed_rules = await backend.structured_store.list_confirmed_rules(project_name)
    all_confirmed_rules = await backend.structured_store.list_confirmed_rules(
        project_name,
        include_history=True,
    )
    all_relation_facts = await backend.structured_store.list_relation_facts(
        project_name,
        limit=100000,
        include_history=True,
    )
    pending_rules = await backend.structured_store.list_rule_candidates(
        project_name,
        status="pending",
    )
    pending_entries = await backend.structured_store.list_memory_entries(
        project_name,
        status="pending",
        limit=100000,
    )
    pending_facts = await backend.structured_store.list_relation_facts(
        project_name,
        status="pending",
        limit=100000,
    )
    truth_entries = []
    truth_rules = []
    truth_facts = []
    for truth_status in TRUTH_LAYER_STATUSES:
        truth_entries.extend(
            await backend.structured_store.list_memory_entries(
                project_name,
                status=truth_status,
                limit=100000,
                include_provisional=True,
            )
        )
        truth_rules.extend(
            await backend.structured_store.list_rule_candidates(
                project_name,
                status=truth_status,
            )
        )
        truth_facts.extend(
            await backend.structured_store.list_relation_facts(
                project_name,
                status=truth_status,
                limit=100000,
                include_provisional=True,
            )
        )
    data_dir = _support.DEFAULT_DATA_DIR
    profile = await LocalProjectProfileStore(data_dir).get(project_name)
    runtime_report = await runtime_health_report(
        backend,
        data_dir=_observer_data_dir(),
        project_name=project_name,
        profile=profile,
        project_root=find_project_root(project_name),
        repo_root=Path(__file__).resolve().parents[2],
    )
    cost_report = surface_cost_report(
        _observer_data_dir(),
        project_name=project_name,
        days=7,
        limit=100,
        surface_budgets=_cost_surface_budgets(project_name),
    )
    active_retrieval_profile = profile.retrieval_profile if profile else None
    pending_distill = distill_drainer_metrics(
        backend,
        project_name=project_name,
    )
    return {
        "observation_count": len(project_observations),
        "memory_entry_count": len(memory_entries),
        "task_handoff_count": len(handoffs),
        "confirmed_rule_count": len(confirmed_rules),
        "pending_candidate_count": len(pending_rules)
        + len(pending_entries)
        + len(pending_facts),
        "durable_truth_count": len(truth_entries)
        + len(truth_rules)
        + len(truth_facts)
        + len(confirmed_rules),
        "pending_distill": pending_distill,
        "temporal_summary": {
            "historical_memory_entry_count": sum(
                1 for entry in all_memory_entries if _is_historical_truth(entry)
            ),
            "historical_confirmed_rule_count": sum(
                1 for rule in all_confirmed_rules if _is_historical_truth(rule)
            ),
            "historical_relation_fact_count": sum(
                1 for fact in all_relation_facts if _is_historical_truth(fact)
            ),
            "historical_total": sum(
                1
                for record in [
                    *all_memory_entries,
                    *all_confirmed_rules,
                    *all_relation_facts,
                ]
                if _is_historical_truth(record)
            ),
            "superseded_total": sum(
                1
                for record in [
                    *all_memory_entries,
                    *all_confirmed_rules,
                    *all_relation_facts,
                ]
                if _is_superseded_truth(record)
            ),
        },
        "retrieval_profiles": _retrieval_profile_status(
            active_profile=active_retrieval_profile,
            memory_entry_count=len(memory_entries),
        ),
        "runtime_versions": runtime_version_payload(),
        "job_health": runtime_report.get("job_health", {}),
        "retrieval_health": runtime_report.get("retrieval_health", {}),
        "cost_budget": {
            "policy": cost_budget_policy(_cost_surface_budgets(project_name)),
            "summary": cost_report.get("summary", {}),
            "recent_high_output_calls": cost_report.get("recent_high_output_calls", [])[
                :5
            ],
            "top_opportunities": cost_report.get("top_opportunities", [])[:5],
        },
        "install_drift": runtime_report.get("version_drift", {}),
    }


_STATUS_BOOTSTRAP_HOSTS = frozenset(SUPPORTED_HOOK_CLIENTS)


def _bootstrap_status_workspace(
    *,
    project_name: str | None,
    project_root: str | None,
    host_client: str | None,
) -> tuple[str | None, Path | None, str | None, dict[str, Any]]:
    """Resolve and idempotently bootstrap context supplied by a live Agent."""

    root_context = (
        resolve_project_context(
            None,
            project_root=project_root,
            required=False,
            action_label="get_project_status",
        )
        if project_root
        else None
    )
    resolved_root = root_context.project_root if root_context is not None else None
    resolved_project = project_name or (
        root_context.project_name if root_context is not None else get_active_project()
    )
    host = normalize_client_name(host_client) if host_client else None

    bootstrap = {
        "attempted": False,
        "host_client": host or "unknown",
        "hooks_status": "not_requested",
    }
    if resolved_project is None or resolved_root is None:
        return resolved_project, resolved_root, host, bootstrap

    asyncio.run(
        _support.ensure_project_profile(resolved_project, project_root=resolved_root)
    )
    set_active_project(resolved_project)

    if host not in _STATUS_BOOTSTRAP_HOSTS:
        bootstrap["hooks_status"] = "unknown_host"
        return resolved_project, resolved_root, host, bootstrap

    bootstrap["attempted"] = True
    install_output = io.StringIO()
    install_errors = io.StringIO()
    with (
        contextlib.redirect_stdout(install_output),
        contextlib.redirect_stderr(install_errors),
    ):
        install_status = cmd_install_hook_suite(host, str(resolved_root), False)
    if install_status == 0:
        output = install_output.getvalue()
        bootstrap["hooks_status"] = (
            "installed"
            if "installed:" in output or "updated:" in output
            else "existing"
        )
    else:
        bootstrap["hooks_status"] = "failed"
        error = install_errors.getvalue().strip()
        if error:
            bootstrap["reason"] = error
    return resolved_project, resolved_root, host, bootstrap


def tool_get_project_status(
    project_name: str | None = None,
    project_root: str | None = None,
    host_client: str | None = None,
    detail_level: str = "compact",
) -> dict:
    """Return active project and memory counts without requiring CLI status."""
    if detail_level not in STATUS_DETAIL_LEVELS:
        return {
            "success": False,
            "error": "detail_level must be one of: compact, full",
            "contract_version": STATUS_CONTRACT_VERSION,
            "detail_level": detail_level,
        }
    resolved_project, resolved_root, resolved_host, integration_bootstrap = (
        _bootstrap_status_workspace(
            project_name=project_name,
            project_root=project_root,
            host_client=host_client,
        )
    )
    active_project = get_active_project()
    if not resolved_project:
        guided_flow = build_guided_flow(
            phase="needs-project",
            project_name=None,
            active_project=active_project,
        )
        flow_hint = guided_flow_drilldown_hint(guided_flow)
        return render_project_status(
            {
                "success": False,
                "active_project": active_project,
                "phase": "needs-project",
                "suggested_slash": None,
                "reason": "Open the intended workspace or provide project_name before status can resolve memory context.",
                "error": "project_name or workspace context is required",
                "why_this_result": "No project was supplied and no workspace context is available.",
                "next_actions": [
                    _action(
                        "set_active_project",
                        "set_active_project",
                        "Set the active project once so wake/search/status can resolve project-scoped memory.",
                    )
                ],
                "degraded_reason": "missing_project",
                "guided_flow": guided_flow,
                "drilldown_hints": [flow_hint],
            },
            detail_level=detail_level,
        )

    backend = _get_backend()
    counts = asyncio.run(_gather_project_status(backend, resolved_project))
    triage = status_triage_hints(counts)
    guided_flow = build_guided_flow(
        phase=str(triage.get("phase") or "unknown"),
        observation_count=int(counts.get("observation_count", 0) or 0),
        pending_candidate_count=int(counts.get("pending_candidate_count", 0) or 0),
        memory_entry_count=int(counts.get("memory_entry_count", 0) or 0),
        project_name=resolved_project,
        active_project=active_project,
    )
    dx_metadata = build_status_dx_metadata(
        counts,
        triage,
        project_name=resolved_project,
    )
    flow_hint = guided_flow_drilldown_hint(guided_flow)
    dx_metadata["drilldown_hints"] = [
        flow_hint,
        *list(dx_metadata.get("drilldown_hints") or []),
    ]
    integration_health = asyncio.run(
        build_integration_health(
            backend,
            project_name=resolved_project,
            project_root=resolved_root or find_project_root(resolved_project),
            configured_host=resolved_host,
        )
    )
    payload = {
        "success": True,
        "project_name": resolved_project,
        "project_root": str(resolved_root) if resolved_root is not None else None,
        "integration_bootstrap": integration_bootstrap,
        "active_project": active_project,
        "truth_runtime_state": backend.runtime_state,
        "truth_runtime_error": backend.runtime_error,
        "truth_runtime_recovery_hint": backend.runtime_recovery_hint,
        **counts,
        **triage,
        **dx_metadata,
        "guided_flow": guided_flow,
        "integration_health": integration_health,
    }
    return render_project_status(payload, detail_level=detail_level)
