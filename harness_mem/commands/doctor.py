"""Doctor command implementation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence, cast

from harness_mem import __version__
from harness_mem.commands.error_codes import doctor_error, format_error_summary
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    WakeBucketQuotaError,
    claude_session_count,
    codex_scope_note,
    codex_session_count,
    get_active_project,
    log_next_step_shown,
    print_recent_sessions,
    project_state,
    recent_claude_sessions,
    recent_codex_sessions,
    resolve_project_name,
    suggested_next_step,
    wake_bucket_quotas,
    wake_budget,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore

STALE_MEMORY_DAYS = 90


async def cmd_doctor(project_name: str | None = None) -> int:
    """Inspect local setup and print actionable next steps."""
    resolved_project = resolve_project_name(project_name, required=False, action_label="doctor")
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
        print(f'Fix: call MCP set_active_project(project_name="{suspected_project}")')

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
        claude_sessions = recent_claude_sessions(resolved_project, limit=3)
        codex_sessions = recent_codex_sessions(limit=3)
        print(f"Doctor project: {resolved_project}")
        print(f"Claude Code sessions: {claude_session_count(resolved_project)}")
        print(f"Codex sessions (global): {codex_session_count()}")
        print_recent_sessions("Recent Claude Code sessions:", claude_sessions)
        print_recent_sessions("Recent Codex sessions (global):", codex_sessions)
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

            entries = await backend.structured_store.list_memory_entries(resolved_project, limit=5)
            all_entries = await backend.structured_store.list_memory_entries(
                resolved_project,
                limit=100000,
            )
            handoffs = await backend.structured_store.get_latest_handoffs(resolved_project, limit=3)
            rules = await backend.structured_store.list_confirmed_rules(resolved_project)
            stale_count, never_accessed_count = _memory_quality_counts(all_entries)
            if all_entries:
                print(
                    "Memory quality: "
                    f"{stale_count} stale, {never_accessed_count} never accessed"
                )

            stale_rule_count, never_surfaced_rule_count = _confirmed_rule_quality_counts(rules)
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

            # v1.7.2 graph traversal status (info only — not a warning).
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

            # v1.6.2: Check vector index health
            vector_health = _check_vector_index_health(backend, resolved_project)
            if vector_health["has_issue"]:
                print(f"\n⚠️  {vector_health['message']}")
                print(f"Fix: {vector_health['fix_command']}")
            exact_health = await _check_verbatim_exact_index_health(backend, resolved_project)
            if exact_health["has_issue"]:
                print(f"\n⚠️  {exact_health['message']}")
                print(f"Fix: {exact_health['fix_command']}")

            total_tokens, level = wake_budget(profile, entries, rules, handoffs)
            print(f"Estimated wake-up: ≈ {total_tokens:,} tokens [{level}]")
            if level in ("L3", "L4+"):
                issue = doctor_error("doctor_wake_budget_large")
                three_months_ago = (
                    datetime.now(timezone.utc).replace(day=1) - timedelta(days=90)
                ).strftime("%Y-%m-%d")
                purge_command = (
                    f"harness-mem purge -p {resolved_project} --before {three_months_ago} "
                    "--category all --dry-run"
                )
                print(format_error_summary(issue))
                print(f"Fix: {purge_command}")

            next_command, reason = suggested_next_step(
                project_name=resolved_project,
                observation_count=state["observations"],
                memory_entry_count=state["memory_entries"],
                claude_sessions=claude_sessions,
                codex_sessions=codex_sessions,
            )

            print()
            await _doctor_weak_link_block(backend, resolved_project)
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


def _memory_quality_counts(entries: Sequence[object]) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_MEMORY_DAYS)
    stale_count = 0
    never_accessed_count = 0
    for entry in entries:
        usage_count = getattr(entry, "usage_count", 0)
        last_accessed_at = getattr(entry, "last_accessed_at", None)
        if usage_count == 0:
            never_accessed_count += 1
        reference_time = last_accessed_at or getattr(entry, "created_at", None)
        if reference_time is None:
            continue
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if reference_time < stale_cutoff:
            stale_count += 1
    return stale_count, never_accessed_count


UNUSED_RULE_DAYS = 90


def _confirmed_rule_quality_counts(rules: Sequence[object]) -> tuple[int, int]:
    """Mirror of ``_memory_quality_counts`` for ConfirmedRule.

    Returns ``(stale_count, never_surfaced_count)``:

    - ``never_surfaced_count``: rules with ``usage_count == 0``. These rules
      were confirmed but wake-up has never actually emitted them — the
      strongest signal that the rule is dead weight.
    - ``stale_count``: rules whose last surface (or, if never surfaced, the
      confirmation timestamp) is older than ``UNUSED_RULE_DAYS``. Captures
      "this rule was useful once but the project has moved on".
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=UNUSED_RULE_DAYS)
    stale_count = 0
    never_surfaced_count = 0
    for rule in rules:
        usage_count = getattr(rule, "usage_count", 0)
        if usage_count == 0:
            never_surfaced_count += 1
        reference_time = getattr(rule, "last_surfaced_at", None) or getattr(
            rule, "confirmed_at", None
        )
        if reference_time is None:
            continue
        if reference_time.tzinfo is None:
            reference_time = reference_time.replace(tzinfo=timezone.utc)
        if reference_time < cutoff:
            stale_count += 1
    return stale_count, never_surfaced_count


def _check_vector_index_health(backend: LocalMemoryBackend, project_name: str) -> dict:
    """Check vec_embeddings table health (v1.6.2).

    Returns dict with keys: has_issue, message, fix_command
    """
    try:
        from harness_mem.commands.support import get_embedding_model_id
        from harness_mem.embedding import get_model_loader

        # Check if vec_embeddings table exists
        structured_store = cast(LocalStructuredStore, backend.structured_store)
        conn = structured_store._index._conn_write()
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='vec_embeddings'"
        )
        table_exists = cursor.fetchone() is not None

        if not table_exists:
            return {
                "has_issue": True,
                "message": "HM-201: Vector index not built",
                "fix_command": f"harness-mem maintenance rebuild-vector-index --project {project_name}"
            }

        # Check if there are any vectors
        cursor = conn.execute("SELECT COUNT(*) FROM vec_embeddings")
        vector_count = cursor.fetchone()[0]

        if vector_count == 0:
            return {
                "has_issue": True,
                "message": "HM-201: Vector index is empty",
                "fix_command": f"harness-mem maintenance rebuild-vector-index --project {project_name}"
            }

        # Check model_id mismatch
        model_id = get_embedding_model_id()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM vec_embeddings WHERE model_id = ?",
            (model_id,)
        )
        matching_count = cursor.fetchone()[0]

        if matching_count == 0:
            cursor = conn.execute("SELECT DISTINCT model_id FROM vec_embeddings LIMIT 1")
            stored_model = cursor.fetchone()
            stored_model_id = stored_model[0] if stored_model else "unknown"
            return {
                "has_issue": True,
                "message": f"Vector index uses different model ({stored_model_id}), current config is {model_id}",
                "fix_command": f"harness-mem maintenance rebuild-vector-index --project {project_name}"
            }

        expected_dim = get_model_loader(model_id).dimensions
        cursor = conn.execute(
            "SELECT entry_id, length(embedding) FROM vec_embeddings WHERE model_id = ? LIMIT 100",
            (model_id,),
        )
        for entry_id, byte_length in cursor.fetchall():
            stored_dim = int(byte_length) // 4
            if stored_dim != expected_dim:
                return {
                    "has_issue": True,
                    "message": (
                        "Vector index dimension mismatch "
                        f"(entry={entry_id}, stored={stored_dim}, current={expected_dim})"
                    ),
                    "fix_command": f"harness-mem maintenance rebuild-vector-index --project {project_name}",
                }

        # All checks passed
        return {"has_issue": False, "message": "", "fix_command": ""}

    except (sqlite3.Error, ValueError):
        # If check fails, assume no issue (table might not exist yet)
        return {"has_issue": False, "message": "", "fix_command": ""}


async def _check_verbatim_exact_index_health(
    backend: LocalMemoryBackend,
    project_name: str,
) -> dict:
    """Check v1.7.3 observation trigram exact-search index health."""
    try:
        verbatim_store = cast(LocalVerbatimStore, backend.verbatim_store)
        observations = [
            observation
            for observation in await verbatim_store.list(limit=100000)
            if observation.metadata.get("project_name") == project_name
        ]
        if not observations:
            return {"has_issue": False, "message": "", "fix_command": ""}
        stats = verbatim_store.exact_index_stats()
        if stats["indexed_observation_count"] == 0:
            return {
                "has_issue": True,
                "message": "HM-301: Verbatim exact index is empty",
                "fix_command": f"harness-mem maintenance rebuild-verbatim-index --project {project_name}",
            }
        return {"has_issue": False, "message": "", "fix_command": ""}
    except Exception:
        return {"has_issue": False, "message": "", "fix_command": ""}


def detect_cwd_project_mismatch(
    *,
    cwd: Path,
    active_project: str | None,
    known_projects: Sequence[str],
) -> str | None:
    """Return a known-project name when cwd unambiguously points elsewhere.

    Conservative on purpose:

    - If there is no active project, no candidate, or only one known project,
      return None (nothing to disambiguate).
    - The cwd's basename must exactly match a known project name *and* differ
      from the active project. Soft matches ("ink" matching "inkpad") are
      intentionally not enough; users hit those constantly when navigating
      monorepos and we'd cry wolf.
    - Returns the suspected project name so the caller can format its own
      message and Fix: command.

    The function is pure (no I/O) so it's trivial to unit-test from a
    loop-harness scenario.
    """
    if not active_project or not known_projects:
        return None
    candidate = cwd.name
    if not candidate:
        return None
    if candidate == active_project:
        return None
    if candidate in known_projects:
        return candidate
    return None


async def _doctor_weak_link_block(
    backend: LocalMemoryBackend,
    project_name: str | None,
) -> None:
    """Print the v2.3.1 weak-link signal influence block.

    Three shapes:

    - Project-less doctor (no active project): one line noting the
      block is skipped — the flag lives on the profile, so without
      one there's nothing to report.
    - ``weak_link_signals=False``: one disabled line with the opt-in
      hint so users see the switch without having to read the
      project profile.
    - ``weak_link_signals=True``: header + 3 stat lines:
        rules pushed to 'Stable / quiet' group:    X / Y
        search results boosted (last 7 days):      N distinct targets
        experimental skills:                       — (deferred to v2.3.2)

    The "stable" stat reuses :func:`pull_recent_signals` against
    confirmed rules over the last 30 days (mirrors the wake re-grouping
    window in 4.2). The "boosted" stat counts distinct memory_entry
    targets with at least 2 ``search_hit`` signals in the last 7 days
    (mirrors 4.3's repeat-boost trigger). When the flag is off we skip
    those queries entirely so doctor stays fast on big projects.
    """
    if project_name is None:
        print("Weak-link signal influence: skipped (no active project)")
        return

    profile_store = LocalProjectProfileStore(backend.data_dir)
    profile = await profile_store.get(project_name)
    if profile is None or not profile.weak_link_signals:
        print(
            "Weak-link signal influence: disabled "
            "(set weak_link_signals=true in project profile)"
        )
        return

    # Lazy import: signal_influence pulls in the v2.3.1 weak-link helper
    # that we only need when the flag is on. Keeping it lazy means doctor
    # on the v2.2-default-off path doesn't pay any import cost.
    from harness_mem.commands.signal_influence import pull_recent_signals

    now = datetime.now(timezone.utc)

    # 1) rules pushed to 'Stable / quiet' group (no surface signals in
    #    the last 30 days).
    rules = await backend.structured_store.list_confirmed_rules(project_name)
    if rules:
        rule_summaries = await pull_recent_signals(
            backend,
            project_name=project_name,
            target_ids=[r.id for r in rules],
            since=now - timedelta(days=30),
        )
        stable_count = sum(
            1
            for r in rules
            if (s := rule_summaries.get(r.id)) is None
            or s.wake_surfaced_count + s.search_hit_count == 0
        )
    else:
        stable_count = 0

    # 2) boosted search targets (last 7 days, memory_entry targets with
    #    >= 2 search_hit signals — mirrors 4.3's REPEAT_BOOST trigger).
    seven_days_ago = now - timedelta(days=7)
    search_signals = await backend.structured_store.query_retrieval_signals(
        project_name,
        signal_type="search_hit",
        since=seven_days_ago,
        limit=10000,
    )
    target_counts: dict[str, int] = {}
    for sig in search_signals:
        if sig.target_kind == "memory_entry":
            target_counts[sig.target_id] = target_counts.get(sig.target_id, 0) + 1
    boosted_count = sum(1 for c in target_counts.values() if c >= 2)

    # 3) experimental skills line — deferred to v2.3.2 per design.md.
    print("Weak-link signal influence (v2.3.1):")
    print(
        f"  rules pushed to 'Stable / quiet' group:    "
        f"{stable_count} / {len(rules)}"
    )
    print(
        f"  search results boosted (last 7 days):      "
        f"{boosted_count} distinct targets"
    )
    print("  experimental skills:                       — (deferred to v2.3.2)")
