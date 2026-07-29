"""Official daily-memory guided flow (v5.13).

Stable onboarding / drilldown narrative for MCP surfaces. Non-canonical:
hints and step order only; never writes truth.
"""

from __future__ import annotations

from typing import Any, Literal

GUIDED_FLOW_ID = "daily-memory-loop"
GUIDED_FLOW_VERSION = "5.13"

EntryKind = Literal["context", "mcp", "slash"]


def build_guided_flow(
    *,
    phase: str,
    observation_count: int = 0,
    pending_candidate_count: int = 0,
    memory_entry_count: int = 0,
    project_name: str | None = None,
    active_project: str | None = None,
) -> dict[str, Any]:
    """Return the official recommended operator flow for the current project phase."""
    steps = _steps_for_phase(
        phase=phase,
        observation_count=observation_count,
        pending_candidate_count=pending_candidate_count,
        memory_entry_count=memory_entry_count,
        project_name=project_name,
    )
    current_step_id = _current_step_id(
        phase=phase,
        observation_count=observation_count,
        pending_candidate_count=pending_candidate_count,
        steps=steps,
    )
    return {
        "flow_id": GUIDED_FLOW_ID,
        "version": GUIDED_FLOW_VERSION,
        "title": "Daily memory loop",
        "authority": "guided_hint",
        "project_name": project_name,
        "active_project": active_project,
        "phase": phase,
        "current_step_id": current_step_id,
        "steps": steps,
        "why": _flow_why(phase=phase, current_step_id=current_step_id),
    }


def _flow_why(*, phase: str, current_step_id: str) -> str:
    if phase == "needs-project":
        return (
            "No active project is configured; set the active project before ingest or wake."
        )
    if phase == "needs-distill":
        return (
            "Captured sessions are waiting for distill before the next wake."
        )
    if phase == "awaiting-capture":
        return "No captured evidence exists yet; wake will sync the current workspace."
    if current_step_id == "review_pending":
        return (
            "Pending candidates remain; review only when correcting or rechecking, "
            "then continue with wake."
        )
    if current_step_id == "wake":
        return (
            "Project memory is ready; start sessions with wake, then search and drill down."
        )
    return "Follow the ordered steps for progressive disclosure; generated material is not truth."


def _current_step_id(
    *,
    phase: str,
    observation_count: int,
    pending_candidate_count: int,
    steps: list[dict[str, Any]],
) -> str:
    if phase == "needs-project":
        return "activate_project"
    if phase == "awaiting-capture":
        return "wake"
    if phase == "needs-distill":
        return "distill"
    if pending_candidate_count > 0 and any(
        step["step_id"] == "review_pending" for step in steps
    ):
        return "review_pending"
    for step in steps:
        if step.get("required"):
            return str(step["step_id"])
    return str(steps[0]["step_id"]) if steps else "wake"


def _steps_for_phase(
    *,
    phase: str,
    observation_count: int,
    pending_candidate_count: int,
    memory_entry_count: int,
    project_name: str | None,
) -> list[dict[str, Any]]:
    project_fragment = f'project_name="{project_name}"' if project_name else "project_name=<project>"
    steps: list[dict[str, Any]] = []

    if phase == "needs-project":
        steps.append(
            _step(
                step_id="resolve_project",
                order=1,
                title="Open the intended workspace",
                description=(
                    "Open the intended workspace so memory resolves to the correct project without a global project switch."
                ),
                entry="project_root",
                entry_kind="context",
                required=True,
                arguments={"project_root": "<workspace-root>"},
            )
        )
        steps.append(
            _step(
                step_id="distill",
                order=2,
                title="Distill session evidence",
                description="Sync recent transcript evidence and draft reviewable memory candidates.",
                entry="/hm:distill",
                entry_kind="slash",
                required=True,
            )
        )
        return steps

    if phase == "awaiting-capture":
        steps.append(
            _step(
                step_id="wake",
                order=1,
                title="Capture and wake the current workspace",
                description=(
                    "Sync available session evidence, then load any project memory."
                ),
                entry=f"wake({project_fragment})",
                entry_kind="mcp",
                required=True,
                arguments={"project_name": project_name} if project_name else {},
            )
        )
        return steps

    if phase == "needs-distill":
        steps.append(
            _step(
                step_id="distill",
                order=1,
                title="Distill session evidence",
                description=(
                    "Sync recent transcript evidence and distill observations into candidates."
                ),
                entry="/hm:distill",
                entry_kind="slash",
                required=True,
            )
        )
        steps.append(
            _step(
                step_id="wake",
                order=2,
                title="Wake for the next session",
                description="After distill, load profile, rules, handoffs, and task-aware retrieval.",
                entry=f"wake({project_fragment})",
                entry_kind="mcp",
                required=True,
                arguments={"project_name": project_name} if project_name else {},
            )
        )
        return steps

    order = 1
    if pending_candidate_count > 0:
        steps.append(
            _step(
                step_id="review_pending",
                order=order,
                title="Review pending candidates (when needed)",
                description=(
                    "Use review only for explicit recheck or correction; distill already "
                    "auto-handles low-risk items."
                ),
                entry="/hm:review",
                entry_kind="slash",
                required=False,
                badge=f"{pending_candidate_count} pending",
            )
        )
        order += 1

    steps.append(
        _step(
            step_id="wake",
            order=order,
            title="Wake at session start",
            description=(
                "Prefer wake over manually stitching get_confirmed_rules / get_task_handoffs."
            ),
            entry=f"wake({project_fragment})",
            entry_kind="mcp",
            required=True,
            arguments={"project_name": project_name} if project_name else {},
        )
    )
    order += 1

    steps.append(
        _step(
            step_id="search_task",
            order=order,
            title="Search before deep reads",
            description="Narrow context to the current subsystem or decision.",
            entry=f'search_memory({project_fragment}, query="<topic>")',
            entry_kind="mcp",
            required=False,
            arguments={"project_name": project_name, "query": "<topic>"} if project_name else {},
        )
    )
    order += 1

    steps.append(
        _step(
            step_id="drilldown_sources",
            order=order,
            title="Drill down to sources",
            description=(
                "Use drilldown_hints, get_observations, or temporal_query for proof; "
                "do not treat compact generated summaries as confirmed truth."
            ),
            entry="drilldown_hints",
            entry_kind="mcp",
            required=False,
        )
    )
    order += 1

    steps.append(
        _step(
            step_id="handoff",
            order=order,
            title="Hand off at session end",
            description="Record progress, blockers, and next steps for the next session.",
            entry=f"create_task_handoff({project_fragment})",
            entry_kind="mcp",
            required=False,
            arguments={"project_name": project_name} if project_name else {},
        )
    )
    return steps


def _step(
    *,
    step_id: str,
    order: int,
    title: str,
    description: str,
    entry: str,
    entry_kind: EntryKind,
    required: bool,
    arguments: dict[str, Any] | None = None,
    badge: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "step_id": step_id,
        "order": order,
        "title": title,
        "description": description,
        "entry": entry,
        "entry_kind": entry_kind,
        "required": required,
    }
    if arguments:
        payload["arguments"] = dict(arguments)
    if badge:
        payload["badge"] = badge
    return payload


def guided_flow_drilldown_hint(flow: dict[str, Any]) -> dict[str, Any]:
    """Single drilldown hint pointing at the current guided-flow step."""
    current = str(flow.get("current_step_id") or "")
    steps = flow.get("steps") or []
    current_step = next(
        (item for item in steps if isinstance(item, dict) and item.get("step_id") == current),
        None,
    )
    title = str(current_step.get("title") if current_step else current)
    entry = str(current_step.get("entry") if current_step else "get_project_status")
    return {
        "source_id": None,
        "source_kind": "guided_flow",
        "read_surface": "mcp.guided_flow",
        "tool": entry.split("(")[0].removeprefix("/hm:"),
        "arguments": dict((current_step or {}).get("arguments") or {}),
        "why": f"Official daily-memory step: {title} ({GUIDED_FLOW_ID} {GUIDED_FLOW_VERSION}).",
    }
