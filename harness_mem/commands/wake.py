"""Wake command implementation."""

from __future__ import annotations

import asyncio
import json
import os
import time
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
    get_config,
    log_command_invoked,
    log_next_step_shown,
    project_ingest_lock_path,
    project_ingest_scan_stamp_path,
    resolve_project_name,
)
from harness_mem.commands.ingest import _select_claude_candidate_sessions
from harness_mem.commands.wake_render import (
    LAYER_HEADERS,
    SURFACED_LAYERS,
    render_wake_plan,
    select_rendered_entries,
)
from harness_mem.context_assembly import assemble_context_plan
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.context_assembly_plan import ContextAssemblyPlan, PlanEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.skill import Skill
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore

AUTO_SYNC_TIMEOUT_SECONDS = 0.3
DEFAULT_AUTO_INGEST_MIN_INTERVAL_SECONDS = 300
DEFAULT_AUTO_INGEST_MIN_NEW_SESSIONS = 1
DEFAULT_AUTO_INGEST_SCAN_THROTTLE_SECONDS = 60
DEFAULT_AUTO_INGEST_LOCK_TTL_SECONDS = 3600
DEFAULT_SKILL_HINT_LIMIT = 3


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
    config = get_config()
    min_interval_seconds = _wake_int_setting(
        config,
        "auto_ingest_min_interval_seconds",
        DEFAULT_AUTO_INGEST_MIN_INTERVAL_SECONDS,
    )
    min_new_sessions = _wake_int_setting(
        config,
        "auto_ingest_min_new_sessions",
        DEFAULT_AUTO_INGEST_MIN_NEW_SESSIONS,
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

    adapter = AdapterRegistry.build("claude-code", backend)
    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    profile = await profile_store.get(project_name)
    all_sessions = adapter.list_sessions(project_name, min_size_kb=0)

    candidate_sessions = _select_claude_candidate_sessions(
        all_sessions,
        limit=len(all_sessions),
        full_rescan=False,
        last_session_id=(prior_last_session_id or (profile.last_ingest_session_id if profile else None)),
        last_ingest_at=profile.last_ingest_at if profile else None,
    )

    if len(candidate_sessions) < min_new_sessions:
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
    newest_seen_session_id = prior_last_session_id or (profile.last_ingest_session_id if profile else None)
    cursor_time_to_write = prior_cursor_time

    try:
        for session in candidate_sessions:
            if await _session_exists_for_project(backend, session["session_id"], project_name):
                continue
            try:
                obs = adapter.session_to_observation(session["path"], session["session_id"], project_name)
                await backend.verbatim_store.save(obs)
                ingested += 1
            except Exception:
                continue

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

    if ingested > 0:
        print(f"🔄 Auto-synced: {ingested} new sessions ingested ({_elapsed_ms(start_time)}ms)")
    else:
        print(f"🔄 Auto-sync: up to date ({_elapsed_ms(start_time)}ms)")


async def _session_exists_for_project(
    backend: LocalMemoryBackend,
    session_id: str,
    project_name: str,
) -> bool:
    # Cap is a defensive ceiling, not a paging limit: we short-circuit on the
    # first matching observation, so realistic transcripts (≤ a few thousand
    # entries per session) finish well before reaching it. The previous 20
    # would silently miss long sessions and re-ingest duplicates.
    observations = await backend.verbatim_store.list(session_id=session_id, limit=10_000)
    return any(
        observation.metadata.get("project_name") == project_name
        for observation in observations
    )


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
) -> None:
    """Apply wake's existing per-record side effects over the rendered entries.

    Walks the surfaced layers (L0/L1/L2) in render order, selecting the same
    entries the wake output shows (truth-filtered + budget-capped via
    ``select_rendered_entries``), and for each surfaced confirmed-rule /
    accepted-memory-entry record applies the existing ``wake_surfaced`` signal
    plus its usage-counter touch (``touch_confirmed_rule`` /
    ``touch_memory_entry``) **once per distinct source record id** across the
    whole render — an accepted entry can appear in both L1 and L2 (Req 7.1).
    Handoffs and the profile carry no side effect, and no other
    ``RetrievalSignal`` is emitted (Req 7.4).
    """
    seen_ids: set[str] = set()
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
            await record_retrieval_signal(
                backend,
                project_name=plan.project_name,
                signal_type="wake_surfaced",
                target_kind=target_kind,
                target_id=record_id,
                context={"source": "wake"},
            )


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


def _serialize_plan_entry(entry: PlanEntry) -> dict[str, Any]:
    return {
        "summary": entry.summary,
        "source_ids": list(entry.source_ids),
        "truth_status": entry.truth_status,
        "why_included": entry.why_included,
    }


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
            _serialize_plan_entry(entry) for entry in select_rendered_entries(layer)
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


async def build_wake_injection(
    backend: LocalMemoryBackend,
    project_name: str,
    *,
    apply_surface_side_effects: bool = True,
) -> str:
    """Return the session-start wake text for host injection.

    This is the hook-facing form of wake: it reuses the same L0/L1/L2 context
    plan renderer as `/hm:wake` and MCP `wake`, but leaves out CLI-only budget
    advice and never runs maintenance, distill, review, or dream.
    """
    plan = await assemble_context_plan(backend, project_name=project_name)
    if apply_surface_side_effects:
        await _apply_surface_side_effects(backend, plan)
    return render_wake_plan(plan)


async def cmd_wake_up(
    project_name: str | None,
    no_auto_ingest: bool = False,
    *,
    no_bucket_quota: bool = False,
    include_skill_hints: bool | None = None,
    skill_hint_limit: int | None = None,
) -> int:
    """Generate wake-up context for a project.

    v2.5.1: the rendered output reflects the v2.5.0 ``ContextAssemblyPlan``.
    ``cmd_wake_up`` assembles a plan for the resolved project, renders the
    cold-start surfaced layers (L0/L1/L2) through the pure
    :func:`render_wake_plan`, applies wake's existing side effects
    (``wake_surfaced`` signals + usage-counter touches) in a separate
    de-duplicated pass, and prints the Disclosure_Level token-budget summary.

    ``no_bucket_quota`` is retained for CLI / back-compat; the v1.6.1
    bucket-quota ``Memory Entries`` block is superseded by the plan-backed
    L1/L2 rendering, so the flag no longer affects the rendered output.
    """
    project_name = resolve_project_name(project_name, action_label="wake-up")
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

        # Req 1, 8 — pure render -> stdout; the MCP redirect_stdout capture
        # stays complete because rendering emits only via print().
        print(render_wake_plan(plan))
        if skill_hints_enabled:
            skill_hints = await _select_wake_skill_hints(
                backend,
                project_name,
                limit=effective_skill_hint_limit,
            )
            print(_render_skill_hint_block(skill_hints))

        # Req 7 — wake's existing per-record signals/touches, de-duplicated.
        await _apply_surface_side_effects(backend, plan)

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
