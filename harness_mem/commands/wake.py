"""Wake command implementation."""

from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from harness_mem.adapters import AdapterRegistry
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.signal_influence import pull_recent_signals
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    chars_to_tokens,
    disclosure_level,
    ensure_project_profile,
    get_config,
    current_agent_client,
    log_command_invoked,
    log_next_step_shown,
    project_ingest_lock_path,
    project_ingest_scan_stamp_path,
    resolve_project_name,
)
from harness_mem.commands.wake_render import (
    LAYER_HEADERS,
    SURFACED_LAYERS,
    select_rendered_entries,
)
from harness_mem.context_assembly import assemble_context_plan
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.context_assembly_plan import ContextAssemblyPlan, PlanEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.skill import Skill
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.recent_context import build_recent_context, render_recent_context
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

AUTO_SYNC_TIMEOUT_SECONDS = 0.3
DEFAULT_AUTO_INGEST_MIN_INTERVAL_SECONDS = 300
DEFAULT_AUTO_INGEST_SCAN_THROTTLE_SECONDS = 60
DEFAULT_AUTO_INGEST_LOCK_TTL_SECONDS = 3600
DEFAULT_SKILL_HINT_LIMIT = 3


@dataclass(frozen=True)
class AutoSyncRuntimePlan:
    runtime_client: str
    sync_client: str | None
    skip_reason: str | None


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


def _format_usage_badge(
    usage_count: int | None,
    last_surfaced_at: datetime | None,
    *,
    now: datetime | None = None,
) -> str:
    """Render the per-rule "this is how often it shows up" suffix.

    Wakes don't tell users whether a confirmed rule is dead weight or
    genuinely useful. This helper turns ``usage_count`` /
    ``last_surfaced_at`` into a compact suffix so the user can see, at
    a glance, which rules are working ("used 8×, last 2d ago") and
    which are silent ("never surfaced before").

    The values rendered here are the **pre-touch** snapshot — the
    counter still reflects history *before* this wake, so users see
    the cumulative work the rule has done up to (but not including)
    the current call. The next wake will show the incremented count.

    Pure function. ``now`` is injectable for deterministic tests.
    """
    count = int(usage_count or 0)
    if count <= 0 or last_surfaced_at is None:
        return "  _(never surfaced before)_"

    reference = now or datetime.now(timezone.utc)
    surfaced = last_surfaced_at
    if surfaced.tzinfo is None:
        surfaced = surfaced.replace(tzinfo=timezone.utc)
    delta = reference - surfaced
    minutes = int(delta.total_seconds() // 60)
    if minutes < 1:
        ago = "just now"
    elif minutes < 60:
        ago = f"{minutes}m ago"
    elif minutes < 60 * 24:
        ago = f"{minutes // 60}h ago"
    elif minutes < 60 * 24 * 30:
        ago = f"{minutes // (60 * 24)}d ago"
    else:
        ago = f"{minutes // (60 * 24 * 30)}mo ago"
    return f"  _(used {count}×, last {ago})_"


def _print_auto_sync_skipped(reason: str, start_time: float) -> None:
    print(f"🔄 Auto-sync skipped: {reason} ({_elapsed_ms(start_time)}ms)")


def _render_rule(rule: ConfirmedRule) -> None:
    """Print one confirmed rule to stdout in v2.2 wake format.

    Extracted from the inline body of ``cmd_wake_up`` so the v2.2 path
    and the v2.3.1 weak-link grouping path share identical formatting.
    The touch / signal calls live in the caller — they're per-render
    side effects, not part of the format.
    """
    trigger_limit = 60
    pattern_limit = 100
    is_trigger_trunc = len(rule.trigger) > trigger_limit
    is_pattern_trunc = len(rule.pattern) > pattern_limit

    t_preview = rule.trigger[:trigger_limit] + "..." if is_trigger_trunc else rule.trigger
    p_preview = rule.pattern[:pattern_limit] + "..." if is_pattern_trunc else rule.pattern

    trunc_marker = " [...truncated]" if (is_trigger_trunc or is_pattern_trunc) else ""
    usage_badge = _format_usage_badge(rule.usage_count, rule.last_surfaced_at)
    print(f"- **{t_preview}**: {p_preview}{trunc_marker}{usage_badge}")
    if rule.provenance:
        provenance = rule.provenance
        source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
        print(f"  📍 {source}")


async def _split_rules_for_weak_link(
    backend: LocalMemoryBackend,
    rules: list[ConfirmedRule],
    project_name: str,
    *,
    total_budget: int,
) -> tuple[list[ConfirmedRule], list[ConfirmedRule]]:
    """Split rules into ``(recent_active, stable_quiet)`` for v2.3.1 wake.

    A rule is "recent active" iff it had at least one ``wake_surfaced``
    or ``search_hit`` signal in the last 30 days. Within each group the
    input order is preserved (caller passes rules sorted by
    ``confirmed_at DESC``). Total output is capped at ``total_budget``;
    recent fills first, stable fills the remainder.

    Gated upstream by ``ProjectProfile.weak_link_signals`` — this helper
    is only called when the flag is on, so it unconditionally hits
    ``pull_recent_signals``.
    """
    if not rules:
        return [], []

    now = datetime.now(timezone.utc)
    summaries = await pull_recent_signals(
        backend,
        project_name=project_name,
        target_ids=[rule.id for rule in rules],
        since=now - timedelta(days=30),
    )

    recent: list[ConfirmedRule] = []
    stable: list[ConfirmedRule] = []
    for rule in rules:
        summary = summaries.get(rule.id)
        is_recent = summary is not None and (
            summary.wake_surfaced_count + summary.search_hit_count > 0
        )
        if is_recent:
            recent.append(rule)
        else:
            stable.append(rule)

    recent_capped = recent[:total_budget]
    remaining = total_budget - len(recent_capped)
    stable_capped = stable[:remaining] if remaining > 0 else []
    return recent_capped, stable_capped


def _wake_int_setting(config: dict, key: str, default: int) -> int:
    value = config.get("wake", {}).get(key, default)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _wake_bool_setting(config: dict, key: str, default: bool) -> bool:
    value = config.get("wake", {}).get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on"}:
            return True
        if lowered in {"0", "false", "no", "off"}:
            return False
    return bool(value)


async def _select_wake_skill_hints(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    limit: int,
) -> list[Skill]:
    if limit <= 0:
        return []
    skills = await backend.structured_store.list_skills(project_name)
    return skills[:limit]


def _render_skill_hint_line(skill: Skill) -> str:
    reason = skill.activation_condition.strip()
    if len(reason) > 100:
        reason = reason[:97].rstrip() + "..."
    return f"- skill {skill.id}: {skill.name} | when: {reason}"


def _render_skill_hint_block(skills: list[Skill]) -> str:
    lines = ["# Skill Hints  (opt-in compact)"]
    if skills:
        lines.extend(_render_skill_hint_line(skill) for skill in skills)
    else:
        lines.append("_(none)_")
    hint_tokens = chars_to_tokens(len("\n".join(lines)))
    lines.append(f"_Approx skill-hint tokens: ≈ {hint_tokens:,} [separate budget]_")
    return "\n".join(lines)


def _read_lock_record(lock_path: Path) -> dict:
    if not lock_path.exists():
        return {}
    try:
        data = json.loads(lock_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        # Corrupt or empty lock file — treat as no prior state. Caller will
        # overwrite on successful acquire. Don't try to salvage partial data.
        return {}
    except OSError:
        return {}


def _record_updated_at(record: dict) -> datetime | None:
    value = record.get("updated_at")
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _write_lock_record(
    lock_path: Path,
    *,
    pid: int,
    state: str,
    last_session_id: str | None,
    cursor_time: datetime | None,
) -> None:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text(
        json.dumps(
            {
                "pid": pid,
                "state": state,
                "last_session_id": last_session_id,
                "cursor_time": cursor_time.isoformat() if cursor_time else None,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    if cursor_time is not None:
        ts = cursor_time.timestamp()
        os.utime(lock_path, (ts, ts))


def _file_mtime(path: Path) -> datetime | None:
    if not path.exists():
        return None
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _scan_stamp_is_fresh(
    scan_stamp_path: Path,
    cursor_time: datetime | None,
    throttle_seconds: int,
) -> bool:
    if throttle_seconds <= 0 or not scan_stamp_path.exists():
        return False
    stamp_time = _file_mtime(scan_stamp_path)
    if stamp_time is None:
        return False
    if cursor_time is not None and stamp_time <= cursor_time:
        return False
    age = (datetime.now(timezone.utc) - stamp_time).total_seconds()
    return age < throttle_seconds


def _mark_scan_stamp(scan_stamp_path: Path) -> None:
    scan_stamp_path.parent.mkdir(parents=True, exist_ok=True)
    scan_stamp_path.write_text(str(os.getpid()), encoding="utf-8")


def _clear_scan_stamp(scan_stamp_path: Path) -> None:
    if scan_stamp_path.exists():
        scan_stamp_path.unlink()


def _acquire_ingest_lock(
    lock_path: Path,
    *,
    last_session_id: str | None,
    prior_cursor_time: datetime | None,
    lock_ttl_seconds: int,
) -> tuple[bool, str | None]:
    existing = _read_lock_record(lock_path)
    existing_pid = int(existing.get("pid", 0) or 0)
    existing_state = str(existing.get("state", "idle") or "idle")
    existing_updated_at = _record_updated_at(existing)
    if (
        existing_state == "running"
        and existing_pid not in (0, os.getpid())
        and _is_pid_running(existing_pid)
        and (
            existing_updated_at is None
            or (datetime.now(timezone.utc) - existing_updated_at).total_seconds() < lock_ttl_seconds
        )
    ):
        return False, f"lock held by pid {existing_pid}"

    _write_lock_record(
        lock_path,
        pid=os.getpid(),
        state="running",
        last_session_id=last_session_id,
        cursor_time=prior_cursor_time,
    )
    return True, None


def _auto_sync_runtime_plan() -> AutoSyncRuntimePlan:
    runtime_client = current_agent_client()
    if runtime_client in {
        "claude-code", "cursor", "codex", "grok", "hermes", "opencode", "antigravity"
    }:
        return AutoSyncRuntimePlan(
            runtime_client=runtime_client,
            sync_client=runtime_client,
            skip_reason=None,
        )
    if runtime_client == "codex-archive":
        return AutoSyncRuntimePlan(
            runtime_client=runtime_client,
            sync_client=None,
            skip_reason=(
                "host codex currently syncs through archived rollouts; "
                "wake auto-sync stays off for archive imports; use codex-archive ingest explicitly"
            ),
        )
    return AutoSyncRuntimePlan(
        runtime_client=runtime_client,
        sync_client=None,
        skip_reason=(
            f"host {runtime_client} has no native project-scoped ingest yet"
        ),
    )


async def _auto_sync_sessions(backend: LocalMemoryBackend, project_name: str) -> None:
    """Perform a light, timed ingestion of new sessions."""
    start_time = time.perf_counter()
    try:
        # P95 budget 300ms
        await asyncio.wait_for(
            _perform_sync(backend, project_name, start_time),
            timeout=AUTO_SYNC_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        print("🔄 Auto-sync: timeout (>300ms), skipping")
    except Exception as exc:
        # Non-blocking: never let auto-sync errors break wake-up. But surface
        # a one-line hint so a user with chronic ingest failures isn't blind,
        # and persist details to events.log for postmortem.
        print("🔄 Auto-sync: error (skipped, see events.log)")
        try:
            await get_event_logger(DEFAULT_DATA_DIR).log(
                EventType.COMMAND_INVOKED,
                project_name=project_name,
                command="wake-up.auto-sync",
                extra={"error": str(exc), "error_kind": type(exc).__name__},
            )
        except Exception:
            # Logging itself must never break wake-up.
            pass


async def _perform_sync(backend: LocalMemoryBackend, project_name: str, start_time: float) -> None:
    plan = _auto_sync_runtime_plan()
    if plan.sync_client is None:
        _print_auto_sync_skipped(plan.skip_reason or "unsupported host", start_time)
        return

    config = get_config()
    min_interval_seconds = _wake_int_setting(
        config,
        "auto_ingest_min_interval_seconds",
        DEFAULT_AUTO_INGEST_MIN_INTERVAL_SECONDS,
    )
    scan_throttle_seconds = _wake_int_setting(
        config,
        "auto_ingest_scan_throttle_seconds",
        DEFAULT_AUTO_INGEST_SCAN_THROTTLE_SECONDS,
    )
    lock_ttl_seconds = _wake_int_setting(
        config,
        "auto_ingest_lock_ttl_seconds",
        DEFAULT_AUTO_INGEST_LOCK_TTL_SECONDS,
    )

    lock_path = project_ingest_lock_path(project_name)
    scan_stamp_path = project_ingest_scan_stamp_path(project_name)
    prior_lock_record = _read_lock_record(lock_path)
    prior_cursor_time = _file_mtime(lock_path)
    prior_last_session_id = prior_lock_record.get("last_session_id")

    if prior_cursor_time is not None:
        age = (datetime.now(timezone.utc) - prior_cursor_time).total_seconds()
        if age < min_interval_seconds:
            _print_auto_sync_skipped("time gate", start_time)
            return

    if _scan_stamp_is_fresh(scan_stamp_path, prior_cursor_time, scan_throttle_seconds):
        _print_auto_sync_skipped("scan throttle", start_time)
        return

    adapter_kwargs: dict[str, object] = {}
    if plan.sync_client in {
        "cursor", "codex", "grok", "hermes", "opencode", "antigravity"
    }:
        adapter_kwargs["project_root"] = Path.cwd()
    if plan.sync_client in {"codex", "hermes"}:
        adapter_kwargs["scope"] = "project"
    adapter = AdapterRegistry.build(plan.sync_client, backend, **adapter_kwargs)
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    profile = await profile_store.get(project_name)
    all_sessions = adapter.list_sessions(project_name, min_size_kb=0)

    if not all_sessions:
        _mark_scan_stamp(scan_stamp_path)
        print(f"🔄 Auto-sync: up to date ({_elapsed_ms(start_time)}ms)")
        return

    lock_acquired, lock_reason = _acquire_ingest_lock(
        lock_path,
        last_session_id=prior_last_session_id or (profile.last_ingest_session_id if profile else None),
        prior_cursor_time=prior_cursor_time,
        lock_ttl_seconds=lock_ttl_seconds,
    )
    if not lock_acquired:
        _print_auto_sync_skipped(lock_reason or "lock held", start_time)
        return

    ingested = 0
    updated = 0
    newest_seen_session_id = prior_last_session_id or (profile.last_ingest_session_id if profile else None)
    cursor_time_to_write = prior_cursor_time

    try:
        result = await adapter.ingest(
            project_name=project_name,
            limit=5,
            min_size_kb=0,
        )
        ingested = int(result.get("ingested", 0) or 0)
        updated = int(result.get("updated", 0) or 0)

        if all_sessions:
            newest_seen_session_id = all_sessions[0]["session_id"]
        cursor_time_to_write = datetime.now(timezone.utc)

        if profile is None:
            profile = ProjectProfile(project_name=project_name)
        profile.last_ingest_session_id = newest_seen_session_id
        profile.last_ingest_at = cursor_time_to_write
        await profile_store.save(profile)
        _clear_scan_stamp(scan_stamp_path)
    finally:
        _write_lock_record(
            lock_path,
            pid=os.getpid(),
            state="idle",
            last_session_id=newest_seen_session_id,
            cursor_time=cursor_time_to_write,
        )

    if ingested > 0 or updated > 0:
        print(
            f"🔄 Auto-synced: {ingested} new, {updated} updated "
            f"({_elapsed_ms(start_time)}ms)"
        )
    else:
        print(f"🔄 Auto-sync: up to date ({_elapsed_ms(start_time)}ms)")


# Map each plan ``why_included`` (set by the v2.5.0 assembler) to the
# ``wake_surfaced`` signal ``target_kind`` for the records that carry wake's
# existing side effects. ``active:recent_handoff`` (task handoffs) and
# ``identity:active_project`` (the project profile) are intentionally absent —
# they carry no signal/touch, matching current wake behavior.
_SIGNAL_TARGET_BY_WHY: dict[str, str] = {
    "essential:confirmed_rule": "rule",
    "essential:high_confidence_truth": "memory_entry",
    "active:recently_surfaced": "memory_entry",
}


async def _apply_surface_side_effects(
    backend: LocalMemoryBackend,
    plan: ContextAssemblyPlan,
    *,
    retrieval_id: str | None = None,
) -> dict[str, Any]:
    """Apply wake's existing per-record side effects over the rendered entries.

    Walks the surfaced layers (L0/L1/L2) in render order, selecting the same
    entries the wake output shows (truth-filtered + budget-capped via
    ``select_rendered_entries``), and for each surfaced confirmed-rule /
    readable-truth memory-entry record applies the existing ``wake_surfaced`` signal
    plus its usage-counter touch (``touch_confirmed_rule`` /
    ``touch_memory_entry``) **once per distinct source record id** across the
    whole render — a readable-truth entry can appear in both L1 and L2 (Req 7.1).
    Handoffs and the profile carry no side effect, and no other
    ``RetrievalSignal`` is emitted (Req 7.4).
    """
    seen_ids: set[str] = set()
    recorded_ids: set[str] = set()
    attempted = 0
    recorded = 0
    for layer_id in SURFACED_LAYERS:
        layer = plan.layer(layer_id)
        for entry in select_rendered_entries(layer):
            target_kind = _SIGNAL_TARGET_BY_WHY.get(entry.why_included)
            if target_kind is None:
                continue
            record_id = next((sid for sid in entry.source_ids if sid), "")
            if not record_id or record_id in seen_ids:
                continue
            seen_ids.add(record_id)
            if target_kind == "rule":
                await backend.structured_store.touch_confirmed_rule(record_id)
            else:
                await backend.structured_store.touch_memory_entry(record_id)
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
    failed = attempted - recorded
    return {
        "contract_version": "retrieval-signal-receipt-v1",
        "retrieval_id": retrieval_id,
        "surface": "wake",
        "attempted": attempted,
        "recorded": recorded,
        "failed": failed,
        "state": "degraded" if failed else "ok",
        "source_ids": sorted(recorded_ids),
        "content_recorded": False,
    }


def _disclosure_level_for_plan(plan: ContextAssemblyPlan) -> tuple[int, str]:
    """Compute the Disclosure_Level token-budget summary for a plan (Req 1.6).

    Pure: estimates tokens from the surfaced (L0/L1/L2) rendered entry
    summaries via the existing ``chars_to_tokens`` helper and maps that to the
    existing ``{L0, L1, L2, L3, L4+}`` label set via ``disclosure_level``. This
    is the v2.5.1 plan-backed analogue of the old ``wake_budget`` summary; the
    label set is a separate concept from a plan Layer (glossary) and is not
    governed by per-layer Budget caps.
    """
    total_chars = sum(
        len(entry.summary)
        for layer_id in SURFACED_LAYERS
        for entry in select_rendered_entries(plan.layer(layer_id))
    )
    total_tokens = chars_to_tokens(total_chars)
    return total_tokens, disclosure_level(total_tokens)


def _serialize_plan_entry(entry: PlanEntry, *, project_name: str) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "summary": entry.summary,
        "source_ids": list(entry.source_ids),
        "truth_status": entry.truth_status,
        "why_included": entry.why_included,
    }
    action_hint = _wake_action_hint(entry, project_name=project_name)
    if action_hint is not None:
        payload["action_hint"] = action_hint
    return payload


def _wake_action_hint(entry: PlanEntry, *, project_name: str) -> dict[str, Any] | None:
    source_id = next((value for value in entry.source_ids if value), "")
    if not source_id:
        return None
    if entry.why_included == "identity:active_project":
        return {
            "source_id": source_id,
            "source_kind": "project_profile",
            "tool": "get_project_profile",
            "arguments": {"project_name": project_name},
            "why_it_matters": "Confirms the project identity and stack before loading deeper memory.",
            "action": "Use this profile to keep wake/search scoped to the active project.",
        }
    if entry.why_included == "essential:confirmed_rule":
        return {
            "source_id": source_id,
            "source_kind": "confirmed_rule",
            "tool": "get_confirmed_rules",
            "arguments": {"project_name": project_name},
            "why_it_matters": "Confirmed rules are current operating constraints for this project.",
            "action": "Apply the rule before changing related behavior.",
        }
    if entry.why_included == "essential:high_confidence_truth":
        return {
            "source_id": source_id,
            "source_kind": "memory_entry",
            "tool": "search_memory",
            "arguments": {"project_name": project_name, "query": entry.summary},
            "why_it_matters": "High-confidence current truth should shape task decisions.",
            "action": "Use this decision as current context, then drill down if it conflicts with the task.",
        }
    if entry.why_included == "active:recent_handoff":
        return {
            "source_id": source_id,
            "source_kind": "task_handoff",
            "tool": "get_task_handoffs",
            "arguments": {"project_name": project_name},
            "why_it_matters": "Recent handoffs carry active task state and next steps.",
            "action": "Resume from this handoff before starting unrelated work.",
        }
    if entry.why_included == "active:recently_surfaced":
        return {
            "source_id": source_id,
            "source_kind": "memory_entry",
            "tool": "search_memory",
            "arguments": {"project_name": project_name, "query": entry.summary},
            "why_it_matters": "Recently surfaced memory is likely tied to ongoing work.",
            "action": "Re-check this context if the current task touches the same subsystem.",
        }
    return None


def _dedupe_wake_action_hints(hints: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for hint in hints:
        key = (str(hint.get("source_id") or ""), str(hint.get("tool") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(hint))
    return deduped


async def build_wake_snapshot(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    include_skill_hints: bool = False,
    skill_hint_limit: int = DEFAULT_SKILL_HINT_LIMIT,
) -> dict[str, Any]:
    """Return structured wake data that does not depend on long text rendering.

    MCP clients and router layers may truncate a large ``output`` string. This
    helper mirrors the plan-backed wake state into compact structured fields so
    callers can still read L0/L1/L2 content even when UI layers abbreviate the
    rendered text block.
    """
    plan = await assemble_context_plan(backend, project_name=project_name)
    total_tokens, level = _disclosure_level_for_plan(plan)

    entries_by_layer: dict[str, list[dict[str, Any]]] = {}
    sections: list[dict[str, Any]] = []
    for layer_id in SURFACED_LAYERS:
        layer = plan.layer(layer_id)
        serialized_entries = [
            _serialize_plan_entry(entry, project_name=project_name)
            for entry in select_rendered_entries(layer)
        ]
        entries_by_layer[layer_id] = serialized_entries
        sections.append(
            {
                "layer": layer_id,
                "title": LAYER_HEADERS[layer_id],
                "entries": serialized_entries,
                "truncation": layer.truncation.to_dict(),
            }
        )

    payload: dict[str, Any] = {
        "wake_sections": sections,
        "project_profile_entries": entries_by_layer["L0"],
        "essential_truth": entries_by_layer["L1"],
        "active_task": entries_by_layer["L2"],
        "action_hints": _dedupe_wake_action_hints(
            [
                entry["action_hint"]
                for entries in entries_by_layer.values()
                for entry in entries
                if isinstance(entry.get("action_hint"), dict)
            ]
        ),
        "disclosure": {
            "approx_tokens": total_tokens,
            "level": level,
        },
    }
    if include_skill_hints:
        skills = await _select_wake_skill_hints(
            backend,
            project_name,
            limit=max(0, skill_hint_limit),
        )
        payload["skill_hints"] = [
            {
                "id": skill.id,
                "name": skill.name,
                "activation_condition": skill.activation_condition,
            }
            for skill in skills
        ]
    return payload


def _build_distill_maintenance_offer(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    record_offer: bool,
) -> dict[str, Any]:
    """Build one truthful, machine-readable Agent-active wake offer."""

    from harness_mem.commands.distill_lifecycle import (
        build_distill_maintenance_offer,
        pending_distill_jobs,
        distill_drainer_metrics,
    )

    distill_config = MergedConfig()
    sources = backend.transcript_store.list_sources(
        project_name=project_name,
        limit=1,
    )
    if sources:
        root = Path(sources[0].project_root)
        if root.is_absolute() and root.is_dir():
            distill_config = load_merged_config(root)
    max_jobs = (
        distill_config.distill_auto_max_jobs_per_wake
        if distill_config.distill_auto_enabled
        else 0
    )
    jobs = pending_distill_jobs(
        backend,
        project_name=project_name,
        recent_first=distill_config.distill_auto_recent_first,
        target_backlog=distill_config.distill_auto_target_backlog,
        max_jobs=max_jobs,
        daily_job_budget=distill_config.distill_auto_daily_job_budget,
        record_offer=record_offer and distill_config.distill_auto_enabled,
    )
    drainer_metrics = distill_drainer_metrics(
        backend,
        project_name=project_name,
        daily_job_budget=distill_config.distill_auto_daily_job_budget,
    )
    offer = build_distill_maintenance_offer(
        jobs,
        max_jobs=max_jobs,
        target_backlog=distill_config.distill_auto_target_backlog,
        budget_tokens=distill_config.cost_budget_distill_tokens,
        metrics=drainer_metrics,
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
    """Return the session-start wake text for host injection.

    The hook-facing form uses the compact recent-context renderer. The existing
    ContextAssemblyPlan still supplies stable truth, active handoffs, and wake
    side effects, but empty L0/L1/L2 sections are no longer the primary view.
    """
    plan = await assemble_context_plan(backend, project_name=project_name)
    if apply_surface_side_effects:
        await _apply_surface_side_effects(backend, plan)
    recent_context = await build_recent_context(backend, project_name)
    rendered = render_recent_context(recent_context, plan, compact=True)
    maintenance = _build_distill_maintenance_offer(
        backend,
        project_name,
        record_offer=apply_surface_side_effects,
    )
    instruction = str(maintenance.get("instruction") or "")
    return f"{rendered}\n\n{instruction}" if instruction else rendered


async def cmd_wake_up(
    project_name: str | None,
    no_auto_ingest: bool = False,
    *,
    no_bucket_quota: bool = False,
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
    maintenance_capture: dict[str, Any] | None = None,
    retrieval_id: str | None = None,
    retrieval_capture: dict[str, Any] | None = None,
) -> int:
    """Generate wake-up context for a project.

    Human-facing output leads with a recent transcript index and appends
    stable truth plus active handoffs from ContextAssemblyPlan. Existing wake
    side effects, structured snapshots, and disclosure accounting stay intact.

    ``no_bucket_quota`` is retained for CLI / back-compat; the v1.6.1
    bucket-quota ``Memory Entries`` block is superseded by the plan-backed
    L1/L2 rendering, so the flag no longer affects the rendered output.
    """
    project_name = resolve_project_name(
        project_name,
        project_root=Path.cwd(),
        action_label="wake-up",
    )
    if not project_name:
        return 1

    # Configuration check
    config = get_config()
    should_auto_ingest = not no_auto_ingest and config.get("wake", {}).get("auto_ingest", True)
    skill_hints_enabled = (
        _wake_bool_setting(config, "include_skill_hints", False)
        if include_skill_hints is None
        else bool(include_skill_hints)
    )
    effective_skill_hint_limit = (
        _wake_int_setting(config, "skill_hint_limit", DEFAULT_SKILL_HINT_LIMIT)
        if skill_hint_limit is None
        else max(0, int(skill_hint_limit))
    )

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    await ensure_project_profile(project_name, Path.cwd())

    if should_auto_ingest:
        await _auto_sync_sessions(backend, project_name)

    try:
        # Req 1.7 — if no plan can be produced, stop before emitting any
        # plan-backed section and return a non-zero code naming the failure.
        try:
            plan = await assemble_context_plan(backend, project_name=project_name)
        except Exception as exc:
            print(f"Error: could not assemble context plan for '{project_name}': {exc}")
            return 1

        recent_context = await build_recent_context(backend, project_name)
        print(render_recent_context(recent_context, plan, compact=False))
        maintenance = _build_distill_maintenance_offer(
            backend,
            project_name,
            record_offer=True,
        )
        if maintenance_capture is not None:
            maintenance_capture.update(maintenance)
        maintenance_instruction = str(maintenance.get("instruction") or "")
        if maintenance_instruction:
            print(maintenance_instruction)
        if skill_hints_enabled:
            skill_hints = await _select_wake_skill_hints(
                backend,
                project_name,
                limit=effective_skill_hint_limit,
            )
            print(_render_skill_hint_block(skill_hints))

        # Req 7 — wake's existing per-record signals/touches, de-duplicated.
        retrieval_receipt = await _apply_surface_side_effects(
            backend,
            plan,
            retrieval_id=retrieval_id,
        )
        if retrieval_capture is not None:
            retrieval_capture.update(retrieval_receipt)

        # Req 1.6 — preserve the Disclosure_Level token-budget summary line.
        total_tokens, level = _disclosure_level_for_plan(plan)
        print(f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]")
        if level in ("L3", "L4+"):
            three_months_ago = (
                datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
            ).strftime("%Y-%m-%d")
            purge_command = (
                "harness-mem maintenance purge "
                f"-p {project_name} --before {three_months_ago} --category all --dry-run"
            )
            print(f"⚠️  Memory budget at {level}")
            print(f"💡 Run: {purge_command}")
            print("   to preview what can be archived.")
            log_next_step_shown(project_name, "wake-up", purge_command)

        surfaced_entries = sum(
            len(select_rendered_entries(plan.layer(layer_id)))
            for layer_id in SURFACED_LAYERS
        )
        log_command_invoked(
            "wake-up",
            project_name=project_name,
            extra={
                "disclosure_level": level,
                "surfaced_entries": surfaced_entries,
            },
        )
    finally:
        await backend.close()
    return 0
