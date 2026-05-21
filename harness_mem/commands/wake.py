"""Wake command implementation."""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem.adapters import AdapterRegistry
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    WakeBucketQuotaError,
    get_config,
    log_command_invoked,
    log_next_step_shown,
    project_ingest_lock_path,
    project_ingest_scan_stamp_path,
    profile_text,
    resolve_project_name,
    wake_budget,
    wake_bucket_enabled,
    wake_bucket_quotas,
)
from harness_mem.commands.ingest import _select_claude_candidate_sessions
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.event_log import EventType, get_event_logger
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.wake_selection import (
    BUCKET_ORDER,
    select_wake_memory_entries,
    select_wake_memory_entries_with_buckets,
)

AUTO_SYNC_TIMEOUT_SECONDS = 0.3
DEFAULT_AUTO_INGEST_MIN_INTERVAL_SECONDS = 300
DEFAULT_AUTO_INGEST_MIN_NEW_SESSIONS = 1
DEFAULT_AUTO_INGEST_SCAN_THROTTLE_SECONDS = 60
DEFAULT_AUTO_INGEST_LOCK_TTL_SECONDS = 3600


def _elapsed_ms(start_time: float) -> int:
    return int((time.perf_counter() - start_time) * 1000)


def _print_auto_sync_skipped(reason: str, start_time: float) -> None:
    print(f"🔄 Auto-sync skipped: {reason} ({_elapsed_ms(start_time)}ms)")


def _wake_int_setting(config: dict, key: str, default: int) -> int:
    value = config.get("wake", {}).get(key, default)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


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


async def cmd_wake_up(
    project_name: str | None,
    no_auto_ingest: bool = False,
    *,
    no_bucket_quota: bool = False,
) -> int:
    """Generate wake-up context for a project.

    v1.6.1: ``no_bucket_quota`` (CLI ``--no-bucket-quota``) overrides config
    ``[wake] bucket_quota_enabled`` and forces the v1.6.0 single-pool behavior.
    """
    project_name = resolve_project_name(project_name, action_label="wake-up")
    if not project_name:
        return 1

    # Configuration check
    config = get_config()
    should_auto_ingest = not no_auto_ingest and config.get("wake", {}).get("auto_ingest", True)
    bucket_quota_active = (not no_bucket_quota) and wake_bucket_enabled(config)
    quotas: dict[str, float] | None = None
    if bucket_quota_active:
        try:
            quotas = wake_bucket_quotas(config)
        except WakeBucketQuotaError as exc:
            print(f"Error ({exc.code}): {exc}")
            print(
                "Fix: edit ~/.harness-mem/config.toml [wake] bucket_quota_* "
                "(default: 0.5 / 0.5 / 0.0). "
                "Or run with --no-bucket-quota to fall back to v1.6.0 behavior."
            )
            return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    
    if should_auto_ingest:
        await _auto_sync_sessions(backend, project_name)

    profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    try:
        profile = await profile_store.get(project_name)
        if profile:
            profile_chars = len(profile.project_name or "") + len(profile_text(profile))
            print(f"# Project Profile  (source: profile, ~{profile_chars} chars)")
            if profile.description:
                print(f"Description: {profile.description}")
            if profile.stacks:
                print(f"Stacks: {', '.join(profile.stacks)}")
            if profile.key_files:
                print("Key files:")
                for key_file in profile.key_files[:5]:
                    print(f"  - {key_file}")
            if profile.conventions:
                print("Conventions:")
                for convention in profile.conventions[:5]:
                    print(f"  - {convention}")
            if not any([profile.description, profile.stacks, profile.key_files, profile.conventions]):
                print("(empty profile)")
            print()
        else:
            print("# Project Profile  (source: profile, empty)")
            print()

        handoffs = await backend.structured_store.get_latest_handoffs(project_name, limit=3)
        if handoffs:
            handoff_chars = sum(
                len(handoff.summary or "") + len(str(handoff.next_steps)) + len(str(handoff.blockers))
                for handoff in handoffs
            )
            print(f"# Recent Tasks  (source: task_handoffs, {len(handoffs)} items, ~{handoff_chars} chars)")
            for handoff in handoffs:
                print(f"## [{handoff.status}] {handoff.summary}")
                if handoff.next_steps:
                    print(f"  Next: {handoff.next_steps[0]}")
                if handoff.blockers:
                    print(f"  Blockers: {', '.join(handoff.blockers)}")
                if handoff.provenance:
                    provenance = handoff.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()
        else:
            print("# Recent Tasks  (source: task_handoffs, empty)")
            print()

        rules = await backend.structured_store.list_confirmed_rules(project_name)
        if rules:
            rules_chars = sum(len(rule.trigger or "") + len(rule.pattern or "") for rule in rules)
            print(f"# Confirmed Rules  (source: confirmed_rules, {len(rules)} rules, ~{rules_chars} chars)")
            for rule in rules[:5]:
                trigger_limit = 60
                pattern_limit = 100
                is_trigger_trunc = len(rule.trigger) > trigger_limit
                is_pattern_trunc = len(rule.pattern) > pattern_limit
                
                t_preview = rule.trigger[:trigger_limit] + "..." if is_trigger_trunc else rule.trigger
                p_preview = rule.pattern[:pattern_limit] + "..." if is_pattern_trunc else rule.pattern
                
                trunc_marker = " [...truncated]" if (is_trigger_trunc or is_pattern_trunc) else ""
                print(f"- **{t_preview}**: {p_preview}{trunc_marker}")
                if rule.provenance:
                    provenance = rule.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()
        else:
            print("# Confirmed Rules  (source: confirmed_rules, empty)")
            print()

        relation_candidates = await backend.structured_store.list_relation_facts(project_name, limit=20)
        relation_facts = [
            fact for fact in relation_candidates
            if fact.confidence >= 0.7
        ][:5]
        if relation_facts:
            relation_chars = sum(
                len(fact.source_entity)
                + len(fact.relation_type)
                + len(fact.target_entity)
                + len(fact.evidence)
                for fact in relation_facts
            )
            print(
                f"# Relation Facts  (source: relation_facts, "
                f"{len(relation_facts)} facts, ~{relation_chars} chars)"
            )
            for fact in relation_facts:
                evidence_limit = 100
                is_trunc = len(fact.evidence) > evidence_limit
                evidence_preview = fact.evidence[:evidence_limit] + "..." if is_trunc else fact.evidence
                trunc_marker = " [...truncated]" if is_trunc else ""
                print(f"- {fact.source_entity} --{fact.relation_type}-> {fact.target_entity}: {evidence_preview}{trunc_marker}")
                if fact.provenance:
                    provenance = fact.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
            print()

        entry_candidates = await backend.structured_store.list_memory_entries(project_name, limit=50)
        if bucket_quota_active and quotas is not None:
            entries, bucket_stats = select_wake_memory_entries_with_buckets(
                entry_candidates, limit=5, quotas=quotas, enabled=True
            )
        else:
            entries = select_wake_memory_entries(entry_candidates, limit=5)
            bucket_stats = {}
        if entries:
            entry_chars = sum(len(entry.content or "") for entry in entries)
            print(f"# Memory Entries  (source: structured_memory, {len(entries)} entries, ~{entry_chars} chars)")
            if bucket_quota_active and quotas is not None and bucket_stats:
                quota_line = "  ".join(
                    f"{bucket}={quotas[bucket]:.2f}" for bucket in BUCKET_ORDER
                )
                fill_line = "  ".join(
                    f"{bucket}={bucket_stats[bucket].used}/{bucket_stats[bucket].quota_count}"
                    for bucket in BUCKET_ORDER
                )
                print(f"#  bucket quotas: {quota_line}")
                print(f"#  bucket fill:   {fill_line}")
            for entry in entries:
                content_limit = 100
                is_trunc = len(entry.content) > content_limit
                content_preview = entry.content[:content_limit] + "..." if is_trunc else entry.content
                trunc_marker = " [...truncated]" if is_trunc else ""
                memory_type = getattr(entry, "memory_type", "semantic")
                print(f"- [{entry.category}/{memory_type}] {content_preview}{trunc_marker}")
                if entry.provenance:
                    provenance = entry.provenance
                    source = provenance.get("session_id", provenance.get("agent_type", "unknown"))
                    print(f"  📍 {source}")
                await backend.structured_store.touch_memory_entry(entry.id)
            if bucket_quota_active and quotas is not None and bucket_stats:
                for bucket in BUCKET_ORDER:
                    stats = bucket_stats[bucket]
                    if stats.truncated:
                        print(
                            f"[truncated within bucket: {bucket} "
                            f"{stats.used}/{stats.candidates}]"
                        )
            print()
        else:
            print("# Memory Entries  (source: structured_memory, empty)")
            print()

        total_tokens, level = wake_budget(profile, entries, rules, handoffs, relation_facts)
        print(f"Approx wake-up tokens: ≈ {total_tokens:,} [{level}]")
        if level in ("L3", "L4+"):
            three_months_ago = (
                datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
            ).strftime("%Y-%m-%d")
            purge_command = (
                f"harness-mem purge -p {project_name} --before {three_months_ago} --category all --dry-run"
            )
            print(f"⚠️  Memory budget at {level}")
            print(f"💡 Run: {purge_command}")
            print("   to preview what can be archived.")
            log_next_step_shown(project_name, "wake-up", purge_command)

        log_command_invoked(
            "wake-up",
            project_name=project_name,
            extra={
                "disclosure_level": level,
                "memory_entries": len(entries),
                "relation_facts": len(relation_facts),
                "rules": len(rules),
            },
        )
    finally:
        await backend.close()
    return 0
