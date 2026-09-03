"""Read-only Doctor probes and health aggregation."""

from __future__ import annotations

import logging
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence, cast

from harness_mem.commands.doctor_thresholds import (
    DORMANT_SIGNAL_AGE,
    WAL_SIZE_THRESHOLD_BYTES,
)
from harness_mem.commands.support import (
    find_project_root,
)
from harness_mem.config.errors import ConfigError
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.runtime_health import runtime_health_report
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS
from harness_mem.commands.doctor_classification import (
    _candidate_table_summary,
    _extract_hm_code,
    _normalize_created_at,
)

logger = logging.getLogger(__name__)

_LEGACY_SCAN_TABLES: tuple[tuple[str, str], ...] = (
    ("memory_entries", "list_memory_entries"),
    ("relation_facts", "list_relation_facts"),
    ("rule_candidates", "list_rule_candidates"),
)
_CANDIDATE_TABLE_KEYS: tuple[str, ...] = (
    "rule_candidates",
    "memory_entries",
    "relation_facts",
    "procedural_candidates",
    "supersede_candidates",
)
_CANDIDATE_LIST_LIMIT = 100000
_SIGNAL_FRESHNESS_TYPES: tuple[str, ...] = (
    "search_hit",
    "wake_surfaced",
    "supersede_completed",
    "skill_result_success",
    "skill_result_failure",
)
_STRUCTURED_INDEX_WAL_NAME = "structured_index.sqlite-wal"
_WAL_HINT_CODE = "HM-402"
_WAL_FIX_COMMAND = "harness-mem maintenance checkpoint-wal"
_VECTOR_REBUILD_COMMAND = (
    "harness-mem maintenance rebuild-vector-index --project <PROJECT_NAME>"
)
_VERBATIM_REBUILD_COMMAND = (
    "harness-mem maintenance rebuild-verbatim-index --project <PROJECT_NAME>"
)


def _check_vector_index_health(backend: LocalMemoryBackend, project_name: str) -> dict:
    """Check vec_embeddings table health (v1.6.2).

    Returns dict with keys: has_issue, message, fix_command
    """
    try:
        from harness_mem.commands.support import get_embedding_model_id
        from harness_mem.embedding import get_model_loader

        model_id = get_embedding_model_id()
        expected_dim = get_model_loader(model_id).dimensions

        structured_store = cast(LocalStructuredStore, backend.structured_store)
        verbatim_store = cast(LocalVerbatimStore, backend.verbatim_store)
        indexes = (structured_store.index, verbatim_store.index)
        table_count = 0
        vector_count = 0
        matching_count = 0
        stored_models: set[str] = set()
        vec0_missing = 0
        manifest_reports: list[dict] = []

        for index in indexes:
            with index.locked_connection() as conn:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name='vec_embeddings'"
                )
                if cursor.fetchone() is None:
                    continue
                table_count += 1
                vector_count += int(
                    conn.execute("SELECT COUNT(*) FROM vec_embeddings").fetchone()[0]
                )
                matching_count += int(
                    conn.execute(
                        "SELECT COUNT(*) FROM vec_embeddings WHERE model_id = ?",
                        (model_id,),
                    ).fetchone()[0]
                )
                stored_models.update(
                    str(row[0])
                    for row in conn.execute(
                        "SELECT DISTINCT model_id FROM vec_embeddings"
                    ).fetchall()
                )
                cursor = conn.execute(
                    "SELECT entry_id, length(embedding) FROM vec_embeddings "
                    "WHERE model_id = ? LIMIT 100",
                    (model_id,),
                )
                for entry_id, byte_length in cursor.fetchall():
                    stored_dim = int(byte_length) // 4
                    if stored_dim != expected_dim:
                        return {
                            "has_issue": True,
                            "message": (
                                "Vector index dimension mismatch "
                                f"(entry={entry_id}, stored={stored_dim}, "
                                f"current={expected_dim})"
                            ),
                            "fix_command": _VECTOR_REBUILD_COMMAND,
                        }
            coverage = index.vec0_coverage_report(model_id=model_id)
            vec0_missing += int(coverage.get("vec0_missing", 0))
            active_manifest = index.get_active_index_generation("vec0")
            indexed_count = int(coverage.get("vec0_indexed", 0))
            if indexed_count > 0 and active_manifest is None:
                return {
                    "has_issue": True,
                    "message": "HM-205: derived vec0 generation manifest is missing",
                    "fix_command": _VECTOR_REBUILD_COMMAND,
                    "verification_status": "missing",
                }
            if active_manifest is not None and indexed_count > 0:
                physical = index.vec0_content_identity(model_id=model_id)
                source = index.embedding_source_identity(model_id=model_id)
                manifest_report = index.validate_index_generation(
                    "vec0",
                    row_count=int(physical["row_count"]),
                    id_hash=str(physical["id_hash"]),
                    source_generation=f"embeddings-content:{source['content_hash']}",
                    model_id=model_id,
                    dimensions=expected_dim,
                )
                metadata = active_manifest.get("metadata") or {}
                if metadata.get("content_hash") != physical["content_hash"]:
                    manifest_report["has_issue"] = True
                    manifest_report["reason"] = "manifest_mismatch"
                    manifest_report.setdefault("mismatches", []).append("content_hash")
                if physical["content_hash"] != source["content_hash"]:
                    manifest_report["has_issue"] = True
                    manifest_report["reason"] = "manifest_mismatch"
                    manifest_report.setdefault("mismatches", []).append(
                        "source_content"
                    )
                physical_matches_source = all(
                    physical[key] == source[key]
                    for key in ("row_count", "id_hash", "content_hash")
                )
                if manifest_report.get("has_issue") and physical_matches_source:
                    manifest_report["has_issue"] = False
                    manifest_report["assessment"] = "healthy_incremental"
                    manifest_report["reason"] = "verified_incremental_growth"
                manifest_reports.append(manifest_report)
                if manifest_report.get("has_issue"):
                    return {
                        "has_issue": True,
                        "message": (
                            "HM-205: derived vec0 generation manifest mismatch "
                            f"({', '.join(manifest_report.get('mismatches', []))})"
                        ),
                        "fix_command": _VECTOR_REBUILD_COMMAND,
                        "manifest": manifest_report,
                    }

        if table_count == 0:
            return {
                "has_issue": True,
                "message": "HM-201: Vector index not built",
                "fix_command": _VECTOR_REBUILD_COMMAND,
            }

        if vector_count == 0:
            return {
                "has_issue": True,
                "message": "HM-201: Vector index is empty",
                "fix_command": _VECTOR_REBUILD_COMMAND,
            }

        if matching_count == 0:
            stored_model_id = ", ".join(sorted(stored_models)) or "unknown"
            return {
                "has_issue": True,
                "message": f"Vector index uses different model ({stored_model_id}), current config is {model_id}",
                "fix_command": _VECTOR_REBUILD_COMMAND,
            }

        if vec0_missing > 0:
            return {
                "has_issue": True,
                "message": (
                    "HM-204: vec0 index is behind vec_embeddings "
                    f"({vec0_missing} missing); KNN will lazy-backfill "
                    "or fall back to batch cosine"
                ),
                "fix_command": _VECTOR_REBUILD_COMMAND,
            }

        return {
            "has_issue": False,
            "message": "",
            "fix_command": "",
            "manifest_reports": manifest_reports,
        }

    except (sqlite3.Error, ValueError) as exc:
        # A read-only probe that cannot verify the index is not proof of
        # health. Fail closed while keeping remediation non-destructive.
        return {
            "has_issue": True,
            "message": f"HM-206: vector index health could not be verified ({exc})",
            "fix_command": _VECTOR_REBUILD_COMMAND,
            "verification_status": "unknown",
        }


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
                "fix_command": _VERBATIM_REBUILD_COMMAND,
            }
        generation = verbatim_store.exact_index_generation_report()
        if generation["has_issue"]:
            assessment = str(generation.get("assessment") or "unknown")
            return {
                "has_issue": True,
                "message": (
                    "HM-302: Verbatim exact index generation does not match "
                    f"canonical evidence ({assessment}: {generation['reason']})"
                ),
                "fix_command": _VERBATIM_REBUILD_COMMAND,
                "generation_report": generation,
                "assessment": assessment,
            }
        return {"has_issue": False, "message": "", "fix_command": ""}
    except Exception as exc:
        return {
            "has_issue": True,
            "message": f"HM-303: Verbatim exact index health could not be verified ({exc})",
            "fix_command": _VERBATIM_REBUILD_COMMAND,
            "verification_status": "unknown",
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


# ---- maintenance-hint roll-up ------------------------------------------

# The structured-index WAL file lives beside ``structured_index.sqlite`` in
# the backend data directory. SQLite always names the write-ahead log
# ``<db>-wal``, so this is the file whose on-disk size we inspect (Req 5.6).
_STRUCTURED_INDEX_WAL_NAME = "structured_index.sqlite-wal"

# Stable id for the WAL-size maintenance hint (Req 5.6). HM-401 is already
# taken by ``doctor_unused_confirmed_rules`` in error_codes.py, so the next
# free HM-4xx slot — HM-402 — is the WAL-checkpoint code. The
# fix command points at the WAL-checkpoint maintenance entry point.
_WAL_HINT_CODE = "HM-402"
_WAL_FIX_COMMAND = "harness-mem maintenance checkpoint-wal"

# Matches the leading ``HM-NNN`` token of a hint message (e.g. "HM-201").
_HM_CODE_PREFIX = re.compile(r"^HM-\d+$")


async def maintenance_hints(
    backend: LocalMemoryBackend, project_name: str
) -> dict[str, Any]:
    """Roll up vector-index, verbatim-exact-index, and WAL-size maintenance hints (Req 5).

    Read-only. Aggregates three existing/structural checks into one ordered
    hint list so operators see all rebuild/checkpoint pointers in a single
    place:

    1. Vector-index health via ``_check_vector_index_health`` (sync).
    2. Verbatim-exact-index health via
       ``_check_verbatim_exact_index_health`` (async).
    3. A SQLite WAL-size threshold check against the structured index's
       ``*-wal`` file.

    Each existing check's ``message`` and ``fix_command`` are preserved
    verbatim so the roll-up never changes operator-visible text — it
    only re-groups it (Req 5.5). The ``code`` field is the stable ``HM-NNN``
    prefix extracted from the message where present, falling back to a
    category id otherwise. An empty ``hints`` list means nothing to report
    (Req 5.3). The roll-up emits hints only; it never executes a rebuild or
    checkpoint command (Req 5.4).
    """
    hints: list[dict[str, str]] = []

    # 1) Vector index. Sync helper. Already returns has_issue=True
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

    # 2) Verbatim exact index. Async helper.
    exact_health = await _check_verbatim_exact_index_health(backend, project_name)
    if exact_health["has_issue"]:
        hints.append(
            {
                "category": "verbatim_exact_index",
                "code": _extract_hm_code(
                    exact_health["message"], "verbatim_exact_index"
                ),
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


# ---- health-summary orchestrator ---------------------------------------


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


async def local_health_summary(
    backend: LocalMemoryBackend, project_name: str
) -> dict[str, Any]:
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


# ---- CLI print blocks --------------------------------------------------

# Fix-command pointers for the candidate-health block. Stale and high-risk
# candidates both go through the review audit surface; hm-distill no
# longer owns a separate KB verification surface.
_CANDIDATE_STALE_FIX = "Use hm to review or correct this memory"
_CANDIDATE_HIGH_RISK_FIX = "Use hm to review or correct this memory"


def _load_project_dream_config(project_name: str) -> MergedConfig | None:
    root = find_project_root(project_name)
    if root is None:
        return None
    try:
        return load_merged_config(str(root))
    except ConfigError:
        return None
