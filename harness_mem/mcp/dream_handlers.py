"""Dream maintenance MCP handlers.

Dream remains an explicit, audited maintenance surface.  This module owns
ledger formatting, budget parsing, execution, and undo responses.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
from pathlib import Path
from typing import Any

from harness_mem.commands.dream import (
    dream_auto_tick,
    dream_once,
    latest_dream_ledger,
    undo_dream_item,
)
from harness_mem.commands.replay_window import ReplayBudget
from harness_mem.commands.support import find_project_root, get_active_project
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config

from .handler_facade_proxy import tool_handlers_facade as _core


def _get_backend():
    return _core._get_backend()


def _run_command_to_payload(coro: Any) -> dict[str, Any]:
    output = io.StringIO()
    with contextlib.redirect_stdout(output):
        exit_code = asyncio.run(coro)
    return {
        "success": exit_code == 0,
        "exit_code": exit_code,
        "output": output.getvalue().strip(),
    }


_RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3}


def _highest_risk(values: list[str]) -> str:
    if not values:
        return "none"
    return max(values, key=lambda value: _RISK_RANK.get(value, 0))


def _maintenance_summary(
    *,
    candidate_counts: dict[str, int],
    risk_level: str,
    auto_applied: bool,
    needs_human_review: bool,
    undo_available: bool,
    message: str,
) -> dict[str, Any]:
    summary = {
        "candidate_counts": candidate_counts,
        "risk_level": risk_level,
        "auto_applied": auto_applied,
        "needs_human_review": needs_human_review,
        "undo_available": undo_available,
        "message": message,
    }
    return {"maintenance_summary": dict(summary), **summary}


def _dream_run_summary(run_payload: dict[str, Any] | None) -> dict[str, Any]:
    if not run_payload:
        return _maintenance_summary(
            candidate_counts={
                "processed": 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0,
                "pending_review": 0,
            },
            risk_level="none",
            auto_applied=False,
            needs_human_review=False,
            undo_available=False,
            message="No dream ledger exists yet; no maintenance has been applied.",
        )
    summary = {
        key: int(value or 0)
        for key, value in (run_payload.get("handling_summary") or {}).items()
    }
    items = run_payload.get("items") or []
    risk_level = _highest_risk(
        [str(item.get("risk") or "none") for item in items if isinstance(item, dict)]
    )
    undo_available = any(
        isinstance(item, dict)
        and item.get("final_action") == "applied"
        and bool(item.get("undo"))
        and not (item.get("result") or {}).get("undone_at")
        for item in items
    )
    failed = int(summary.get("failed", 0) or 0)
    archived = int(summary.get("archived", 0) or 0)
    rejected = int(summary.get("rejected", 0) or 0)
    applied = int(summary.get("applied", 0) or 0)
    return _maintenance_summary(
        candidate_counts=summary,
        risk_level=risk_level,
        auto_applied=applied > 0,
        needs_human_review=failed > 0 or archived > 0 or rejected > 0,
        undo_available=undo_available,
        message=(
            "Dream applied maintenance with undo metadata in the ledger."
            if applied
            else "No maintenance was applied in this dream run."
        ),
    )


def _resolve_project_for_dream(project_name: str | None) -> str | None:
    return (project_name or "").strip() or get_active_project()


def _dream_budget_from_payload(budget: dict | None) -> ReplayBudget | None:
    if not budget:
        return None
    budget_kwargs: dict[str, int] = {}
    for key in (
        "max_observations",
        "max_pending_candidates",
        "max_historical_truths",
        "max_low_success_skills",
        "max_repeat_search_hits",
        "max_total_tokens",
        "signal_lookback_days",
    ):
        if key in budget and budget[key] is not None:
            budget_kwargs[key] = budget[key]
    return ReplayBudget(**budget_kwargs)


def _resolve_project_root_for_dream(
    project_name: str,
    project_root: str | None,
) -> str | None:
    """Resolve a real project root without borrowing an unrelated cwd."""

    if project_root:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError(f"project root does not exist: {root}")
        return str(root)
    discovered = find_project_root(project_name)
    return str(discovered.resolve()) if discovered is not None else None


def tool_dream_ledger(
    project_name: str | None = None,
    run_id: str | None = None,
) -> dict:
    """Return the latest v3.1 DreamRun ledger, or one run by id."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    backend = _get_backend()
    payload = asyncio.run(
        latest_dream_ledger(
            backend,
            project_name=resolved,
            run_id=run_id,
        )
    )
    return {**payload, **_dream_run_summary(payload.get("run"))}


def tool_dream_run(
    project_name: str | None = None,
    project_root: str | None = None,
    budget: dict | None = None,
) -> dict:
    """Run one v3.1 dream maintenance pass and return its ledger payload."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    try:
        root = _resolve_project_root_for_dream(resolved, project_root)
        config = load_merged_config(root) if root is not None else MergedConfig()
    except ConfigError as exc:
        return {"success": False, "error": str(exc), **_dream_run_summary(None)}
    backend = _get_backend()
    try:
        run = asyncio.run(
            dream_once(
                backend,
                project_name=resolved,
                project_root=root,
                config=config,
                source="agent",
                budget=_dream_budget_from_payload(budget),
            )
        )
    except Exception as exc:  # noqa: BLE001 - MCP tool should not crash JSON-RPC.
        return {
            "success": False,
            "error": str(exc) or exc.__class__.__name__,
            **_dream_run_summary(None),
        }
    run_payload = run.to_dict()
    return {
        "success": True,
        "project_name": resolved,
        "run": run_payload,
        **_dream_run_summary(run_payload),
    }


def tool_dream_auto_tick(
    project_name: str | None = None,
    project_root: str | None = None,
) -> dict:
    """Host/client auto tick for v3.1 dream."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    try:
        root = _resolve_project_root_for_dream(resolved, project_root)
        if root is None:
            raise ConfigError(
                f"project root is required for automatic Dream: {resolved}"
            )
        config = load_merged_config(root)
    except ConfigError as exc:
        return {"success": False, "error": str(exc), **_dream_run_summary(None)}
    backend = _get_backend()
    payload = asyncio.run(
        dream_auto_tick(
            backend,
            project_name=resolved,
            project_root=root,
            config=config,
            source="agent",
        )
    )
    if payload.get("status") == "completed" and payload.get("summary"):
        run_summary = {
            "processed": int(payload["summary"].get("processed", 0) or 0),
            "applied": int(payload["summary"].get("applied", 0) or 0),
            "rejected": int(payload["summary"].get("rejected", 0) or 0),
            "archived": int(payload["summary"].get("archived", 0) or 0),
            "failed": int(payload["summary"].get("failed", 0) or 0),
            "pending_review": int(payload["summary"].get("pending_review", 0) or 0),
        }
        return {
            **payload,
            **_maintenance_summary(
                candidate_counts=run_summary,
                risk_level="medium" if run_summary.get("processed", 0) else "none",
                auto_applied=run_summary.get("applied", 0) > 0,
                needs_human_review=run_summary.get("failed", 0) > 0,
                undo_available=run_summary.get("applied", 0) > 0,
                message="Dream auto tick completed one dream run and wrote a ledger.",
            ),
        }
    return {
        **payload,
        **_maintenance_summary(
            candidate_counts={
                "processed": 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0,
                "pending_review": 0,
            },
            risk_level="none",
            auto_applied=False,
            needs_human_review=False,
            undo_available=False,
            message=str(payload.get("reason") or "No dream maintenance ran."),
        ),
    }


def tool_undo_dream_item(
    project_name: str | None = None,
    run_id: str | None = None,
    item_id: str | None = None,
) -> dict:
    """Undo one applied DreamItem by replaying its stored undo metadata."""
    resolved = _resolve_project_for_dream(project_name)
    if not resolved:
        return {
            "success": False,
            "error": "project_name is required when no active project is set",
            **_dream_run_summary(None),
        }
    if not run_id or not item_id:
        return {
            "success": False,
            "error": "run_id and item_id are required",
            **_dream_run_summary(None),
        }
    backend = _get_backend()
    payload = asyncio.run(
        undo_dream_item(
            backend,
            project_name=resolved,
            run_id=run_id,
            item_id=item_id,
        )
    )
    return {
        **payload,
        **_maintenance_summary(
            candidate_counts={
                "processed": 1 if payload.get("item") else 0,
                "applied": 0,
                "rejected": 0,
                "archived": 0,
                "failed": 0 if payload.get("success") else 1,
                "pending_review": 0,
            },
            risk_level="low" if payload.get("success") else "medium",
            auto_applied=False,
            needs_human_review=not bool(payload.get("success")),
            undo_available=False,
            message=(
                "Undo completed; ledger item records undone_at."
                if payload.get("success")
                else "Undo failed; inspect the returned item and error."
            ),
        ),
    }
