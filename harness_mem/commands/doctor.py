"""Doctor command implementation."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Sequence, cast

from harness_mem import __version__
from harness_mem.commands.doctor_thresholds import (
    DORMANT_SIGNAL_AGE,
    HIGH_RISK_CONFIDENCE_CUTOFFS,
    STALE_THRESHOLDS,
    WAL_SIZE_THRESHOLD_BYTES,
)
from harness_mem.commands.dream import dream_status_snapshot
from harness_mem.commands.error_codes import doctor_error, format_error_summary
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
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.distribution import distribution_report
from harness_mem.runtime_health import runtime_health_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.canonical_store import canonical_store_health
from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS
from harness_mem.hook_runtime import HookRuntimeReport, collect_hook_runtime_report
from harness_mem.version import runtime_version_payload

logger = logging.getLogger(__name__)

_LEGACY_SCAN_TABLES: tuple[tuple[str, str], ...] = (
    ("memory_entries", "list_memory_entries"),
    ("relation_facts", "list_relation_facts"),
    ("rule_candidates", "list_rule_candidates"),
)

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
        print(f"Cursor sessions (workspace-scoped): {cursor_session_count(project_root)}")
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

            # v1.6.2 vector-index health + v1.7.3 verbatim-exact-index
            # health are no longer emitted inline here. As of v2.4.2 they
            # are rolled up into the unified Maintenance block below via
            # local health summary -> maintenance_hints. The check
            # functions themselves are unchanged; only the inline emission
            # moved. The same message + fix_command strings are preserved
            # verbatim by maintenance_hints so operator-visible text is
            # identical to the pre-v2.4.2 output.

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
            await _doctor_weak_link_block(backend, resolved_project)
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
            _doctor_storage_v2_block(
                canonical_store_health(
                    backend.data_dir,
                    project_name=resolved_project,
                    wal_size_warning_bytes=WAL_SIZE_THRESHOLD_BYTES,
                )
            )
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

        model_id = get_embedding_model_id()
        expected_dim = get_model_loader(model_id).dimensions

        # Check if vec_embeddings table exists
        structured_store = cast(LocalStructuredStore, backend.structured_store)
        with structured_store.index.locked_connection() as conn:
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

        coverage = structured_store.index.vec0_coverage_report(model_id=model_id)
        if coverage.get("vec0_missing", 0) > 0:
            return {
                "has_issue": True,
                "message": (
                    "HM-204: vec0 index is behind vec_embeddings "
                    f"({coverage['vec0_missing']} missing); KNN will lazy-backfill "
                    "or fall back to batch cosine"
                ),
                "fix_command": (
                    f"harness-mem maintenance rebuild-vector-index --project {project_name}"
                ),
            }

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
    from harness_mem.signal_influence import pull_recent_signals

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


# ---- v2.4.2 candidate-health diagnostics -------------------------------

# The five pending-candidate tables covered by Candidate_Health (Req 1.1).
# Order is the stable payload contract — callers branch on values, not on
# key existence (Req 1.7), but we still keep insertion order deterministic
# so JSON consumers see a fixed shape.
_CANDIDATE_TABLE_KEYS: tuple[str, ...] = (
    "rule_candidates",
    "memory_entries",
    "relation_facts",
    "procedural_candidates",
    "supersede_candidates",
)

# Over-fetch limit for the two list methods that accept a ``limit`` kwarg
# (``list_memory_entries`` and ``list_relation_facts``). Doctor is a
# diagnostic — if a review queue ever exceeds this, "go drain the queue"
# is the real story, not "doctor under-counted by N rows".
_CANDIDATE_LIST_LIMIT = 100000


def _normalize_created_at(value: datetime) -> datetime:
    """Treat a naive ``created_at`` as UTC before any age comparison.

    Mirrors the ``reference_time.tzinfo is None`` guard in
    ``_memory_quality_counts`` so candidate rows persisted by older code
    paths (which may have stored naive timestamps) compare correctly
    against ``datetime.now(timezone.utc)``.
    """
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _candidate_table_summary(
    rows: Sequence[Any],
    table: str,
    now: datetime,
) -> dict[str, Any]:
    """Build the per-table aggregate dict for one candidate table.

    Stale = ``now - created_at`` exceeds ``STALE_THRESHOLDS[table]`` (Req 1.3,
    2.1). High_Risk_Stale = stale AND ``confidence`` below the per-type cutoff
    (Req 2.2); tables without a cutoff entry (supersede_candidates) report
    ``None`` for ``high_risk_stale_count`` to keep the shape stable.
    """
    stale_threshold = STALE_THRESHOLDS[table]
    confidence_cutoff = HIGH_RISK_CONFIDENCE_CUTOFFS.get(table)

    pending_count = len(rows)
    stale_count = 0
    high_risk_stale_count = 0 if confidence_cutoff is not None else None
    for row in rows:
        created_at = _normalize_created_at(row.created_at)
        is_stale = (now - created_at) > stale_threshold
        if is_stale:
            stale_count += 1
            if confidence_cutoff is not None and row.confidence < confidence_cutoff:
                # high_risk_stale_count is an int on every table with a cutoff.
                high_risk_stale_count = cast(int, high_risk_stale_count) + 1

    oldest_pending_id: str | None = None
    oldest_pending_created_at: str | None = None
    if rows:
        oldest = min(rows, key=lambda r: _normalize_created_at(r.created_at))
        oldest_pending_id = oldest.id
        oldest_pending_created_at = _normalize_created_at(oldest.created_at).isoformat()

    return {
        "pending_count": pending_count,
        "stale_count": stale_count,
        "high_risk_stale_count": high_risk_stale_count,
        "oldest_pending_id": oldest_pending_id,
        "oldest_pending_created_at": oldest_pending_created_at,
    }


async def candidate_health(structured_store: Any, project_name: str) -> dict[str, Any]:
    """Per-table pending-candidate aggregate (Req 1). Read-only.

    Returns a stable-shape dict keyed by the five covered candidate tables.
    Every table key is always present even when the table has zero pending
    rows (Req 1.7), so callers can branch on
    ``candidate_health[table]["pending_count"]`` without a key-existence
    check first.

    Read-only invariant (Req 1.5, 2.6): only ``list_*`` methods are called;
    no ``confirm_*`` / ``reject_*`` / ``update_*_status`` mutator is touched.

    Note on store-method signatures: ``list_memory_entries`` and
    ``list_relation_facts`` accept a ``limit`` kwarg and default ``status``
    to ``READABLE_TRUTH_FILTER`` — both are passed explicitly here. The rule /
    procedural / supersede list methods take no ``limit`` and default
    ``status`` to ``None``, so only ``status="pending"`` is passed to them.
    """
    now = datetime.now(timezone.utc)

    rule_rows = await structured_store.list_rule_candidates(
        project_name, status="pending"
    )
    memory_rows = await structured_store.list_memory_entries(
        project_name, status="pending", limit=_CANDIDATE_LIST_LIMIT
    )
    relation_rows = await structured_store.list_relation_facts(
        project_name, status="pending", limit=_CANDIDATE_LIST_LIMIT
    )
    procedural_rows = await structured_store.list_procedural_candidates(
        project_name, status="pending"
    )
    supersede_rows = await structured_store.list_supersede_candidates(
        project_name, status="pending"
    )

    rows_by_table: dict[str, Sequence[Any]] = {
        "rule_candidates": rule_rows,
        "memory_entries": memory_rows,
        "relation_facts": relation_rows,
        "procedural_candidates": procedural_rows,
        "supersede_candidates": supersede_rows,
    }

    return {
        table: _candidate_table_summary(rows_by_table[table], table, now)
        for table in _CANDIDATE_TABLE_KEYS
    }


# ---- v2.4.2 signal-freshness diagnostics -------------------------------

# The five retrieval-signal types Signal_Freshness tracks (Req 3.1). Order is
# the stable payload contract; ``all_silent`` is appended after these five.
_SIGNAL_FRESHNESS_TYPES: tuple[str, ...] = (
    "search_hit",
    "wake_surfaced",
    "supersede_completed",
    "skill_result_success",
    "skill_result_failure",
)


async def signal_freshness(structured_store: Any, project_name: str) -> dict[str, Any]:
    """Per-signal-type freshness report (Req 3). Read-only.

    For each tracked signal type, surface the most recent ``recorded_at``
    timestamp (ISO 8601), its age in seconds, and whether the type has gone
    dormant. A signal type is dormant when its freshest event is older than
    ``DORMANT_SIGNAL_AGE`` *or* when it has never been recorded at all — a
    never-seen loop is treated as dormant (Req 3.2).

    ``all_silent`` is ``True`` only when every tracked signal type has zero
    events, so brand-new projects can be rendered as one summary line rather
    than five "never" lines (Req 3.7).

    Read-only invariant (Req 3.6): only ``query_retrieval_signals`` is called;
    no signal row is mutated. The store returns rows ordered by
    ``recorded_at DESC`` with ``limit=1``, so the first row is the freshest
    event of that type.
    """
    now = datetime.now(timezone.utc)

    report: dict[str, Any] = {}
    silent_count = 0
    for signal_type in _SIGNAL_FRESHNESS_TYPES:
        rows = await structured_store.query_retrieval_signals(
            project_name, signal_type=signal_type, since=None, limit=1
        )
        if not rows:
            silent_count += 1
            report[signal_type] = {
                "latest_timestamp": None,
                "age_seconds": None,
                "is_dormant": True,
            }
            continue

        recorded_at = _normalize_created_at(rows[0].recorded_at)
        age = now - recorded_at
        report[signal_type] = {
            "latest_timestamp": recorded_at.isoformat(),
            "age_seconds": int(age.total_seconds()),
            "is_dormant": age > DORMANT_SIGNAL_AGE,
        }

    report["all_silent"] = silent_count == len(_SIGNAL_FRESHNESS_TYPES)
    return report


# ---- v2.4.2 maintenance-hint roll-up -----------------------------------

# The structured-index WAL file lives beside ``structured_index.sqlite`` in
# the backend data directory. SQLite always names the write-ahead log
# ``<db>-wal``, so this is the file whose on-disk size we inspect (Req 5.6).
_STRUCTURED_INDEX_WAL_NAME = "structured_index.sqlite-wal"

# Stable id for the WAL-size maintenance hint (Req 5.6). HM-401 is already
# taken by ``doctor_unused_confirmed_rules`` in error_codes.py, so the next
# free HM-4xx slot — HM-402 — is the new v2.4.2 WAL-checkpoint code. The
# fix command points at the WAL-checkpoint maintenance entry point.
_WAL_HINT_CODE = "HM-402"
_WAL_FIX_COMMAND = "harness-mem maintenance checkpoint-wal"

# Matches the leading ``HM-NNN`` token of a hint message (e.g. "HM-201").
_HM_CODE_PREFIX = re.compile(r"^HM-\d+$")


def _extract_hm_code(message: str, fallback: str) -> str:
    """Pull the ``HM-NNN`` code prefix out of a hint message.

    The existing v1.6.2 / v1.7.3 health checks embed a stable code at the
    front of their message (e.g. ``"HM-201: Vector index is empty"``). We
    split on the first colon and return the leading token when it matches
    the ``HM-<digits>`` shape; otherwise we fall back to the supplied
    category-derived id (some vector-index messages — model/dimension
    mismatch — have no code prefix).
    """
    head = message.split(":", 1)[0].strip()
    if _HM_CODE_PREFIX.match(head):
        return head
    return fallback


async def maintenance_hints(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    """Roll up vector-index, verbatim-exact-index, and WAL-size maintenance hints (Req 5).

    Read-only. Aggregates three existing/structural checks into one ordered
    hint list so operators see all rebuild/checkpoint pointers in a single
    place:

    1. v1.6.2 vector-index health via ``_check_vector_index_health`` (sync).
    2. v1.7.3 verbatim-exact-index health via
       ``_check_verbatim_exact_index_health`` (async).
    3. A SQLite WAL-size threshold check against the structured index's
       ``*-wal`` file.

    Each existing check's ``message`` and ``fix_command`` are preserved
    verbatim so the v2.4.2 roll-up never changes operator-visible text — it
    only re-groups it (Req 5.5). The ``code`` field is the stable ``HM-NNN``
    prefix extracted from the message where present, falling back to a
    category id otherwise. An empty ``hints`` list means nothing to report
    (Req 5.3). The roll-up emits hints only; it never executes a rebuild or
    checkpoint command (Req 5.4).
    """
    hints: list[dict[str, str]] = []

    # 1) Vector index (v1.6.2). Sync helper. Already returns has_issue=True
    #    with the "not built" / "empty" message for the missing-table and
    #    fresh-install cases, so surfacing it preserves Req 5.7 behavior.
    vector_health = _check_vector_index_health(backend, project_name)
    if vector_health["has_issue"]:
        hints.append(
            {
                "category": "vector_index",
                "code": _extract_hm_code(vector_health["message"], "vector_index"),
                "message": vector_health["message"],
                "fix_command": vector_health["fix_command"],
            }
        )

    # 2) Verbatim exact index (v1.7.3). Async helper.
    exact_health = await _check_verbatim_exact_index_health(backend, project_name)
    if exact_health["has_issue"]:
        hints.append(
            {
                "category": "verbatim_exact_index",
                "code": _extract_hm_code(exact_health["message"], "verbatim_exact_index"),
                "message": exact_health["message"],
                "fix_command": exact_health["fix_command"],
            }
        )

    # 3) SQLite WAL size. Missing WAL file → no hint (Req 5.7 — safe against
    #    missing files). Present and over threshold → checkpoint hint (Req 5.6).
    wal_path = backend.data_dir / _STRUCTURED_INDEX_WAL_NAME
    if wal_path.exists():
        wal_size = wal_path.stat().st_size
        if wal_size > WAL_SIZE_THRESHOLD_BYTES:
            size_mb = wal_size // (1024 * 1024)
            hints.append(
                {
                    "category": "sqlite_wal",
                    "code": _WAL_HINT_CODE,
                    "message": f"SQLite WAL file is large ({size_mb} MB)",
                    "fix_command": _WAL_FIX_COMMAND,
                }
            )

    return {"hints": hints}


# ---- v2.4.2 health-summary orchestrator --------------------------------


async def legacy_accepted_status_report(
    structured_store: Any,
    project_name: str,
) -> dict[str, Any]:
    """Count blobs still carrying literal pre-0.8.9 ``status=accepted``."""
    by_table: dict[str, int] = {}
    for table, list_method in _LEGACY_SCAN_TABLES:
        list_fn = getattr(structured_store, list_method)
        if table == "rule_candidates":
            rows = await list_fn(project_name, status=LEGACY_ACCEPTED_STATUS)
        else:
            rows = await list_fn(
                project_name,
                status=LEGACY_ACCEPTED_STATUS,
                limit=100_000,
            )
        if rows:
            by_table[table] = len(rows)
    total = sum(by_table.values())
    return {"total": total, "by_table": by_table}


async def local_health_summary(backend: LocalMemoryBackend, project_name: str) -> dict[str, Any]:
    """Compose local health surfaces. Read-only, never raises.

    Routes CLI ``cmd_doctor`` blocks through the same detection helpers. The
    public health payload intentionally avoids legacy queue terminology; dream
    runtime details are reported through the dream ledger.

    Graceful degradation: each helper call is wrapped in its own try/except.
    On failure the affected category becomes ``{"warnings": [str(exc)]}`` and
    the orchestrator carries on, so a single broken store never crashes the
    whole summary.
    """
    report: dict[str, Any] = {}

    # candidate_health ← per-table pending-candidate aggregate.
    try:
        report["candidate_health"] = await candidate_health(
            backend.structured_store, project_name
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_health_summary: candidate_health failed: %s", exc)
        report["candidate_health"] = {"warnings": [str(exc)]}

    try:
        report["legacy_accepted"] = await legacy_accepted_status_report(
            backend.structured_store, project_name
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_health_summary: legacy_accepted failed: %s", exc)
        report["legacy_accepted"] = {"warnings": [str(exc)]}

    # signal_freshness ← per-signal-type freshness report.
    try:
        report["signal_freshness"] = await signal_freshness(
            backend.structured_store, project_name
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_health_summary: signal_freshness failed: %s", exc)
        report["signal_freshness"] = {"warnings": [str(exc)]}

    # maintenance_hints ← vector / exact / WAL roll-up.
    try:
        report["maintenance_hints"] = await maintenance_hints(backend, project_name)
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_health_summary: maintenance_hints failed: %s", exc)
        report["maintenance_hints"] = {"warnings": [str(exc)]}

    try:
        data_dir = backend.data_dir
        profile = await LocalProjectProfileStore(data_dir).get(project_name)
        report["runtime_health"] = await runtime_health_report(
            backend,
            data_dir=data_dir,
            project_name=project_name,
            profile=profile,
            project_root=find_project_root(project_name),
            repo_root=Path(__file__).resolve().parents[2],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("local_health_summary: runtime_health failed: %s", exc)
        report["runtime_health"] = {"warnings": [str(exc)]}

    return report


# ---- v2.4.2 CLI print blocks -------------------------------------------

# Fix-command pointers for the candidate-health block. Stale and high-risk
# candidates both go through the review audit surface; session-distill no
# longer owns a separate KB verification surface.
_CANDIDATE_STALE_FIX = "/hm:review"
_CANDIDATE_HIGH_RISK_FIX = "/hm:review"


def _doctor_legacy_accepted_block(legacy_report: dict[str, Any]) -> None:
    """Report legacy ``status=accepted`` blobs (invisible to readable_truth)."""
    if "warnings" in legacy_report:
        for warning in legacy_report["warnings"]:
            print(f"⚠️  Legacy accepted scan unavailable: {warning}")
        return

    total = int(legacy_report.get("total", 0))
    by_table = legacy_report.get("by_table") or {}
    if total <= 0:
        print(
            f"Legacy status={LEGACY_ACCEPTED_STATUS}: 0 records "
            "(invisible to readable_truth; not auto-migrated)"
        )
        return

    parts = ", ".join(f"{table}={count}" for table, count in sorted(by_table.items()))
    print(
        f"⚠️  Legacy status={LEGACY_ACCEPTED_STATUS}: {total} record(s) ({parts}) "
        "— invisible to readable_truth; re-confirm or re-promote manually"
    )


def _doctor_candidate_health_block(candidate_report: dict[str, Any]) -> None:
    """Render the candidate-health slice of a local health payload.

    Silent absence (Req 2.5): a table only produces output when it has at
    least one stale pending candidate — no "0 stale" filler. High-risk-stale
    candidates (stale + low confidence) get a separate escalated bullet
    (Req 2.4). Degraded shape (``{"warnings": [...]}`` per Req 6.7) is
    rendered as warning lines instead of the normal aggregate.
    """
    if "warnings" in candidate_report:
        for warning in candidate_report["warnings"]:
            print(f"⚠️  Candidate health unavailable: {warning}")
        return

    printed_header = False
    for table in _CANDIDATE_TABLE_KEYS:
        summary = candidate_report.get(table)
        if not summary:
            continue
        stale_count = summary.get("stale_count", 0)
        if stale_count <= 0:
            continue
        if not printed_header:
            print("Candidate health:")
            printed_header = True
        print(
            f"⚠️  {table}: {stale_count} stale pending candidate(s). "
            f"Fix: {_CANDIDATE_STALE_FIX}"
        )
        high_risk = summary.get("high_risk_stale_count")
        if high_risk is not None and high_risk > 0:
            print(
                f"    ⚠️  {table}: {high_risk} high-risk stale (low confidence). "
                f"Fix: {_CANDIDATE_HIGH_RISK_FIX}"
            )


def _doctor_signal_freshness_block(
    signal_report: dict[str, Any], project_name: str
) -> None:
    """Render the signal-freshness slice of a local health payload.

    Info-level only (Req 3.4): dormancy may be intentional, so this block
    never escalates to a warning. When every signal type is silent
    (``all_silent``) it emits one summary line naming the project rather than
    five "never" lines (Req 3.7). Otherwise it emits one info line per
    Dormant_Signal_Type (Req 3.3); fresh types stay silent (Req 3.5).
    Degraded shape (Req 6.7) renders as warning lines.
    """
    if "warnings" in signal_report:
        for warning in signal_report["warnings"]:
            print(f"⚠️  Signal freshness unavailable: {warning}")
        return

    if signal_report.get("all_silent"):
        print(
            "Signal freshness: no retrieval signals recorded yet for project "
            f"{project_name}"
        )
        return

    printed_header = False
    for signal_type in _SIGNAL_FRESHNESS_TYPES:
        summary = signal_report.get(signal_type)
        if not summary or not summary.get("is_dormant"):
            continue
        if not printed_header:
            print("Signal freshness:")
            printed_header = True
        latest = summary.get("latest_timestamp")
        if latest is None:
            print(f"  {signal_type}: dormant (last event: never)")
        else:
            age_days = (summary.get("age_seconds") or 0) // 86400
            print(f"  {signal_type}: dormant (last event: {latest}, {age_days}d ago)")


def _doctor_maintenance_block(maintenance_report: dict[str, Any]) -> None:
    """Render the maintenance-hints slice of a local health payload.

    Silent absence (Req 5.3): nothing is printed when the hint list is empty.
    Each hint preserves the underlying v1.6.2 / v1.7.3 ``message`` and
    ``fix_command`` verbatim (Req 5.2 / 5.5) so operator-visible text is
    unchanged from the pre-v2.4.2 inline emissions — only the grouping moved
    under a single "Maintenance" heading. Degraded shape (Req 6.7) renders as
    warning lines.
    """
    if "warnings" in maintenance_report:
        for warning in maintenance_report["warnings"]:
            print(f"⚠️  Maintenance hints unavailable: {warning}")
        return

    hints = maintenance_report.get("hints", [])
    if not hints:
        return

    print("Maintenance:")
    for hint in hints:
        print(f"⚠️  {hint['message']}")
        print(f"Fix: {hint['fix_command']}")


def _doctor_runtime_health_block(runtime_report: dict[str, Any]) -> None:
    if not runtime_report:
        return
    if "warnings" in runtime_report:
        for warning in runtime_report["warnings"]:
            print(f"⚠️  Runtime health unavailable: {warning}")
        return
    print("Runtime health:")
    versions = runtime_version_payload()
    print(
        "  versions: "
        f"runtime={versions['runtime_version']} | wire={versions['wire_format_version']}"
    )
    jobs = runtime_report.get("job_health", {})
    dream = jobs.get("dream", {})
    print(
        "  dream maintenance: "
        f"last={dream.get('last_status') or 'none'}, "
        f"failures={dream.get('failure_count', 0)}, "
        f"retryable={dream.get('retryable_count', 0)}"
    )
    retrieval = runtime_report.get("retrieval_health", {})
    surfaces = retrieval.get("surfaces", [])
    if surfaces:
        high = sum(int(row.get("high_output_calls") or 0) for row in surfaces)
        print(f"  retrieval: {len(surfaces)} active surface(s), {high} high-cost call(s)")
    drift = runtime_report.get("version_drift", {})
    if drift.get("has_drift"):
        print(f"⚠️  version/install drift: {len(drift.get('issues', []))} issue(s)")
        for issue in drift.get("issues", [])[:3]:
            print(f"    {issue.get('surface')}: {issue.get('message')}")


def _doctor_storage_v2_block(storage_report: dict[str, Any]) -> None:
    if not storage_report:
        return
    if "warnings" in storage_report:
        for warning in storage_report["warnings"]:
            print(f"⚠️  Storage v2 health unavailable: {warning}")
        return
    status = storage_report.get("status") or "unknown"
    runtime_state = storage_report.get("runtime_state") or "canonical"
    print("Storage v2:")
    print(f"  runtime truth: {runtime_state}")
    print(
        "  canonical: "
        f"{status} | rows={storage_report.get('canonical_row_count', 0)} | "
        f"legacy={storage_report.get('legacy_json_file_count', 0)}"
    )
    print(
        "  checksum: "
        f"{'match' if storage_report.get('checksum_match') else 'not matched'} | "
        f"wal={storage_report.get('wal_size_bytes', 0)} bytes"
    )
    gate = storage_report.get("dual_write_gate") or {}
    if gate:
        print(
            "  dual-write: "
            f"{'enabled' if gate.get('enabled') else 'off'} ({gate.get('env')})"
        )
    if status != "healthy" and storage_report.get("fix_command"):
        print(f"⚠️  Storage v2: {status} ({runtime_state})")
        print(f"Fix: {storage_report['fix_command']}")
    recovery_hint = storage_report.get("recovery_hint")
    if isinstance(recovery_hint, str) and recovery_hint and runtime_state == "degraded_fallback":
        print(f"  recovery: {recovery_hint}")
    drift = storage_report.get("index_drift") or []
    if drift:
        print(f"⚠️  Storage v2 index drift: {len(drift)} missing index(es)")


def _doctor_distribution_block(distribution: dict[str, Any]) -> None:
    if not distribution:
        return
    if set(distribution.keys()) == {"warnings"}:
        for warning in distribution["warnings"]:
            print(f"⚠️  Distribution report unavailable: {warning}")
        return
    rust = distribution.get("rust_core") or {}
    fallback = distribution.get("fallback") or {}
    wheel = distribution.get("wheel_matrix") or {}
    index = distribution.get("index_fabric") or {}
    policy = distribution.get("rust_policy", rust.get("policy", "prefer"))
    print("Distribution:")
    print(
        "  rust core: "
        f"{rust.get('mode', 'unknown')} | native={str(rust.get('available')).lower()} | "
        f"policy={policy}"
    )
    print(
        "  platform: "
        f"{wheel.get('current_target', 'unknown')} | fallback={fallback.get('mode')}"
    )
    print(
        "  index fabric: "
        f"{index.get('freshness', 'unknown')} | sidecars={index.get('sidecar_count', 0)}"
    )
    for warning in distribution.get("warnings") or []:
        if policy == "required" and not rust.get("available"):
            print(f"❌  {warning}")
        else:
            print(f"⚠️  {warning}")


def _doctor_hook_runtime_block(report: HookRuntimeReport) -> None:
    """Render project-scoped hook runtime diagnostics."""

    installed = [hook for hook in report.hooks if hook.exists]
    missing = len(report.hooks) - len(installed)
    probe = report.runner_probe
    legacy = [hook for hook in installed if hook.legacy_python]
    unbound = [hook for hook in installed if not hook.runner_bound and not hook.legacy_python]
    if not probe.ok:
        state = "unavailable"
    elif not installed:
        state = "not installed"
    elif legacy or unbound:
        state = "repair needed"
    else:
        state = "ready"

    print(f"Hook runtime: {state}")
    if probe.ok:
        print(f"  runner: {probe.path} ({probe.version or 'unknown version'})")
    else:
        print("  runner: unavailable")
        if probe.error:
            print(f"    error: {_doctor_one_line(probe.error)}")
        print("    fix: reinstall harness-mem, then reinstall the project Hook suite.")

    if not installed:
        print(f"  hook files: none installed ({missing} known artifact(s) missing)")
    else:
        print(f"  hook files: {len(installed)} installed / {missing} missing")
        for hook in installed:
            if hook.legacy_python:
                binding = "legacy python"
            elif hook.runner_bound:
                binding = "runner bound"
            else:
                binding = "runner not found"
            if hook.project_root_match:
                root_match = "project-root match"
            else:
                root_match = "project-root not found"
            scope = "global" if hook.scope == "global" else "project"
            print(
                f"    {hook.client} {hook.label}: {binding}, {root_match} "
                f"[{scope}] ({_doctor_hook_path(report.project_root, hook.path)})"
            )

    if legacy or unbound:
        print("  fix: reinstall the Hook suite to bind the verified runner.")


def _doctor_hook_path(project_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return path.expanduser().resolve().as_posix()
    except OSError:
        return str(path)


def _doctor_one_line(text: str) -> str:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _load_project_dream_config(project_name: str) -> MergedConfig | None:
    root = find_project_root(project_name)
    if root is None:
        return None
    try:
        return load_merged_config(str(root))
    except ConfigError:
        return None


def _doctor_dream_status_block(dream_report: dict[str, Any]) -> None:
    """Render read-only v3.1 dream status without creating a review queue."""
    state = "enabled" if dream_report.get("enabled") else "off"
    print("Dream auto maintenance:")
    print(f"  enabled: {state}")
    if dream_report.get("last_run_id"):
        print(
            "  last run: "
            f"{dream_report.get('last_status')} "
            f"(processed {dream_report.get('last_processed', 0)}, "
            f"failed {dream_report.get('last_failed', 0)})"
        )
    else:
        print("  last run: none")
    if dream_report.get("enabled"):
        print(
            "  auto gate: "
            f"{'eligible' if dream_report.get('scheduler_eligible') else 'not eligible'} "
            f"({dream_report.get('scheduler_reason')})"
        )
        next_at = dream_report.get("next_eligible_at")
        if next_at:
            print(f"  next eligible: {next_at}")
