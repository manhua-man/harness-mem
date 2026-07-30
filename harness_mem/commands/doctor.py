"""Doctor command implementation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from harness_mem import __version__
from harness_mem.commands.doctor_thresholds import (
    WAL_SIZE_THRESHOLD_BYTES,
)
from harness_mem.commands.dream import dream_status_snapshot
from harness_mem.commands.error_codes import doctor_error, format_error_summary
from harness_mem.commands.doctor_recovery import (
    build_doctor_recovery_plan,
    read_only_storage_v2_health,
)
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    WakeBucketQuotaError,
    claude_session_count,
    codex_scope_note,
    codex_session_count,
    cursor_session_count,
    get_active_project,
    grok_session_count,
    log_next_step_shown,
    print_recent_sessions,
    project_state,
    recent_claude_sessions,
    recent_cursor_sessions,
    recent_codex_sessions,
    recent_grok_sessions,
    resolve_project_name,
    find_project_root,
    suggested_next_step,
    wake_bucket_quotas,
    wake_budget,
)
from harness_mem.distribution import distribution_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.hook_runtime import collect_hook_runtime_report
from harness_mem.commands.doctor_classification import (  # noqa: F401
    UNUSED_RULE_DAYS,
    _confirmed_rule_quality_counts,
    _memory_quality_counts,
    detect_cwd_project_mismatch,
)
from harness_mem.commands.doctor_probes import (  # noqa: F401
    _check_vector_index_health,
    _check_verbatim_exact_index_health,
    _load_project_dream_config,
    candidate_health,
    legacy_accepted_status_report,
    local_health_summary,
    maintenance_hints,
    signal_freshness,
)
from harness_mem.commands.doctor_rendering import (  # noqa: F401
    _doctor_candidate_health_block,
    _doctor_distribution_block,
    _doctor_dream_status_block,
    _doctor_hook_path,
    _doctor_hook_runtime_block,
    _doctor_legacy_accepted_block,
    _doctor_maintenance_block,
    _doctor_one_line,
    _doctor_recovery_plan_block,
    _doctor_runtime_health_block,
    _doctor_signal_freshness_block,
    _doctor_storage_v2_block,
)

logger = logging.getLogger(__name__)


async def cmd_doctor(project_name: str | None = None) -> int:
    """Inspect local setup and print actionable next steps."""
    resolved_project = resolve_project_name(
        project_name, required=False, action_label="doctor"
    )
    initialized = DEFAULT_DATA_DIR.exists()
    active_project = get_active_project()

    print(f"harness-mem {__version__}")
    print(f"Data directory: {DEFAULT_DATA_DIR}")
    print(f"Initialized: {'yes' if initialized else 'no'}")
    print(f"Active project: {active_project or '(none)'}")

    if not initialized:
        issue = doctor_error("doctor_not_initialized")
        print(format_error_summary(issue))
        print(f"Fix: {issue.fix_command}")
        return 1

    # HM-501: surface obvious cwd / active-project mismatch before doing
    # anything project-scoped. Catches the common Cursor / Codex case
    # where an old active project was set weeks ago and now
    # writes memory into the wrong project from a different repo.
    profile_store_for_listing = LocalProjectProfileStore(DEFAULT_DATA_DIR)
    known_profiles = await profile_store_for_listing.list()
    known_project_names = [p.project_name for p in known_profiles]
    suspected_project = detect_cwd_project_mismatch(
        cwd=Path.cwd(),
        active_project=active_project,
        known_projects=known_project_names,
    )
    if suspected_project:
        # We hand-format here instead of calling format_error_summary so
        # the user sees both their cwd and the suspected project; the
        # generic summary is too lossy for this specific check.
        doctor_error("doctor_cwd_project_mismatch")  # validate code is registered
        print(
            f"\n⚠️  HM-501: cwd ({Path.cwd().name}) looks like a different known "
            f"project than the active one ({active_project})."
        )
        print(
            "Fix: reopen the intended workspace or pass its project root; "
            "project context is directory-first."
        )

    # v1.6.1: validate wake bucket quotas early so misconfiguration surfaces
    # before any project-specific work (HM-101 / HM-102).
    try:
        wake_bucket_quotas()
    except WakeBucketQuotaError as exc:
        if exc.code == "HM-101":
            issue = doctor_error("doctor_wake_bucket_quota_sum")
        else:
            issue = doctor_error("doctor_wake_bucket_quota_range")
        print(format_error_summary(issue))
        print(f"Detail: {exc}")
        print(f"Fix: {issue.fix_command}")
        return 1

    if resolved_project:
        project_root = find_project_root(resolved_project) or Path.cwd()
        claude_sessions = recent_claude_sessions(resolved_project, limit=3)
        cursor_sessions = recent_cursor_sessions(project_root, limit=3)
        codex_sessions = recent_codex_sessions(project_root, limit=3)
        grok_sessions = recent_grok_sessions(project_root, limit=3)
        print(f"Doctor project: {resolved_project}")
        print(f"Claude Code sessions: {claude_session_count(resolved_project)}")
        print(
            f"Cursor sessions (workspace-scoped): {cursor_session_count(project_root)}"
        )
        print(f"Codex sessions (workspace-scoped): {codex_session_count(project_root)}")
        print(f"Grok sessions (workspace-scoped): {grok_session_count(project_root)}")
        print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
        print_recent_sessions("Recent Cursor sessions:", cursor_sessions)
        print_recent_sessions("Recent Codex sessions:", codex_sessions)
        print_recent_sessions("Recent Grok sessions:", grok_sessions)
        if codex_sessions:
            print(f"Note: {codex_scope_note()}")

        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
        profile = await profile_store.get(resolved_project)
        print(f"Profile saved: {'yes' if profile else 'no'}")
        if profile and profile.stacks:
            print(f"Stacks detected: {', '.join(profile.stacks)}")

        backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        await backend.init()
        try:
            state = await project_state(resolved_project)
            print(f"Observations: {state['observations']}")
            print(f"Memory entries: {state['memory_entries']}")
            print(f"Task handoffs: {state['task_handoffs']}")
            print(f"Confirmed rules: {state['confirmed_rules']}")

            entries = await backend.structured_store.list_memory_entries(
                resolved_project, limit=5
            )
            all_entries = await backend.structured_store.list_memory_entries(
                resolved_project,
                limit=100000,
            )
            handoffs = await backend.structured_store.get_latest_handoffs(
                resolved_project, limit=3
            )
            rules = await backend.structured_store.list_confirmed_rules(
                resolved_project
            )
            stale_count, never_accessed_count = _memory_quality_counts(all_entries)
            if all_entries:
                print(
                    "Memory quality: "
                    f"{stale_count} stale, {never_accessed_count} never accessed"
                )

            stale_rule_count, never_surfaced_rule_count = (
                _confirmed_rule_quality_counts(rules)
            )
            if rules:
                print(
                    "Rule quality: "
                    f"{stale_rule_count} stale (>{UNUSED_RULE_DAYS}d), "
                    f"{never_surfaced_rule_count} never surfaced"
                )
                if stale_rule_count or never_surfaced_rule_count:
                    issue = doctor_error("doctor_unused_confirmed_rules")
                    print(format_error_summary(issue))
                    print(f"Fix: {issue.fix_command}")

            # Graph traversal status (info only — not a warning).
            # The graph table is rarely populated by heuristic distill;
            # loop_harness scenario 6 measured 0 facts from natural prose.
            # Showing the count without nagging keeps users informed
            # without implying action they probably can't take yet.
            relation_facts = await backend.structured_store.list_relation_facts(
                resolved_project, limit=1000
            )
            print(
                f"Relation graph: {len(relation_facts)} facts "
                f"(trace_relations returns empty when 0)"
            )

            # Vector-index and verbatim-exact-index health are no longer
            # emitted inline here. They
            # are rolled up into the unified Maintenance block below via
            # local health summary -> maintenance_hints. The check
            # functions themselves are unchanged; only the inline emission
            # moved. The same message + fix_command strings are preserved
            # verbatim by maintenance_hints so operator-visible text is
            # identical to the previous inline output.

            total_tokens, level = wake_budget(profile, entries, rules, handoffs)
            print(f"Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")
            if level in ("L3", "L4+"):
                issue = doctor_error("doctor_wake_budget_large")
                three_months_ago = (
                    datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
                ).strftime("%Y-%m-%d")
                purge_command = (
                    "harness-mem maintenance purge "
                    f"-p {resolved_project} --before {three_months_ago} --category all --dry-run"
                )
                print(format_error_summary(issue))
                print(f"Fix: {purge_command}")

            next_command, reason = suggested_next_step(
                project_name=resolved_project,
                observation_count=state["observations"],
                memory_entry_count=state["memory_entries"],
                claude_sessions=claude_sessions,
                cursor_sessions=cursor_sessions,
                grok_sessions=grok_sessions,
                codex_sessions=codex_sessions,
                project_root=project_root,
            )

            print()
            dream_config = _load_project_dream_config(resolved_project)
            dream_report = await dream_status_snapshot(
                backend,
                project_name=resolved_project,
                config=dream_config,
            )
            _doctor_dream_status_block(dream_report)
            # Compose local health in a single pass and render the user-facing
            # slices. Legacy job queues are internal dream runtime details and
            # are not part of doctor output.
            report = await local_health_summary(backend, resolved_project)
            _doctor_candidate_health_block(report["candidate_health"])
            _doctor_legacy_accepted_block(report.get("legacy_accepted", {}))
            _doctor_signal_freshness_block(report["signal_freshness"], resolved_project)
            _doctor_maintenance_block(report["maintenance_hints"])
            _doctor_runtime_health_block(report.get("runtime_health", {}))
            storage_report = read_only_storage_v2_health(
                backend.data_dir,
                project_name=resolved_project,
                wal_size_warning_bytes=WAL_SIZE_THRESHOLD_BYTES,
            )
            _doctor_storage_v2_block(storage_report)
            _doctor_recovery_plan_block(build_doctor_recovery_plan(storage_report))
            _doctor_distribution_block(
                distribution_report(
                    repo_root=Path(__file__).resolve().parents[2],
                    data_dir=backend.data_dir,
                )
            )
            _doctor_hook_runtime_block(collect_hook_runtime_report(project_root))
            print("📍 Phase: Ready")
            print(f"→ Next: {next_command}")
            print(f"   Why: {reason}")
            log_next_step_shown(resolved_project, "doctor", next_command)
        finally:
            await backend.close()
        return 0

    issue = doctor_error("doctor_no_active_project")
    print()
    print("📍 Phase: No Project Selected")
    print(format_error_summary(issue))
    print(f"Fix: {issue.fix_command}")
    log_next_step_shown(None, "doctor", issue.fix_command)
    return 0
