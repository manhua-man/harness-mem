"""Tests for the v2.4.2 ``health_summary`` orchestrator, CLI blocks, and MCP tool (Req 6).

``health_summary(backend, project_name)`` composes the five detection
surfaces — v2.4.0 ``queue_health`` plus the four v2.4.2 helpers
(``candidate_health``, ``signal_freshness``, ``chronic_failures``,
``maintenance_hints``) — into one read-only payload with a fixed top-level
key order. Both the CLI ``cmd_doctor`` blocks and the MCP ``health_summary``
tool consume that payload, so the two surfaces never disagree (Req 6.6).

Coverage:

- Property 3 (shape stability): top-level keys are exactly the five
  documented keys, in order, across empty / mixed / populated states.
- Property 4 (graceful degradation): when a composed helper raises, the
  orchestrator still returns and the failed category becomes
  ``{"warnings": [...]}`` while the others stay normal (Req 6.7).
- MCP round-trip via ``handle_request`` with ``set_backend_override``.
- Zero-state symmetry across all five categories.
- CLI block-helper rendering (Task 6.13) — see the module-level note on the
  approach taken.

The autouse ``data_dir`` fixture in :mod:`tests.conftest` keeps writes scoped
to ``tmp_path``. Async functions are driven via :func:`tests.helpers.run`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.commands import doctor
from harness_mem.commands.doctor import (
    _doctor_candidate_health_block,
    _doctor_chronic_failures_block,
    _doctor_maintenance_block,
    _doctor_queue_health_block,
    _doctor_signal_freshness_block,
    cmd_doctor,
    health_summary,
)
from harness_mem.commands.doctor_thresholds import (
    HIGH_RISK_CONFIDENCE_CUTOFFS,
    STALE_THRESHOLDS,
)
from harness_mem.commands.support import set_active_project
from harness_mem.core.schemas import MemoryEntry, ReflectionJob, RuleCandidate
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

PROJECT = "demo"

# The exact top-level key order health_summary must always produce (Req 6.5).
_EXPECTED_KEYS = [
    "reflection_queue",
    "candidate_health",
    "signal_freshness",
    "chronic_failures",
    "maintenance_hints",
]


# ---- seed helpers --------------------------------------------------------


def _seed_stale_high_risk_rule(backend: LocalMemoryBackend) -> RuleCandidate:
    """A pending rule candidate that is both stale and high-risk-stale.

    ``created_at`` is older than the per-type stale threshold and confidence
    sits below the per-type high-risk cutoff, so candidate_health classifies
    it as stale AND high-risk-stale.
    """
    created_at = (
        datetime.now(timezone.utc) - STALE_THRESHOLDS["rule_candidates"] - timedelta(days=1)
    )
    candidate = RuleCandidate(
        project_name=PROJECT,
        session_id="sess-1",
        pattern="always run ruff",
        trigger="before commit",
        confidence=HIGH_RISK_CONFIDENCE_CUTOFFS["rule_candidates"] - 0.1,
        status="pending",
        created_at=created_at,
    )
    run(backend.structured_store.save_rule_candidate(candidate))
    return candidate


def _seed_fresh_memory(backend: LocalMemoryBackend) -> MemoryEntry:
    entry = MemoryEntry(
        project_name=PROJECT,
        category="architecture",
        content="uses sqlite fts5",
        source="manual",
        status="pending",
        created_at=datetime.now(timezone.utc) - timedelta(hours=1),
    )
    run(backend.structured_store.save_memory_entry(entry))
    return entry


def _seed_dormant_signal(backend: LocalMemoryBackend) -> RetrievalSignal:
    """A search_hit signal old enough to be dormant (> 30 days)."""
    signal = RetrievalSignal(
        project_name=PROJECT,
        signal_type="search_hit",
        target_kind="memory_entry",
        target_id="target-1",
        recorded_at=datetime.now(timezone.utc) - timedelta(days=31),
    )
    run(backend.structured_store.save_retrieval_signal(signal))
    return signal


def _seed_chronic_cluster(
    backend: LocalMemoryBackend, *, error: str = "ingest: boom", count: int = 4
) -> list[ReflectionJob]:
    """Seed ``count`` failed reflection jobs sharing one error string.

    Freshly-saved jobs carry ``updated_at = now``, comfortably inside the
    7-day chronic lookback window, so 4 of them breach the chronic threshold
    (count > 3).
    """
    jobs: list[ReflectionJob] = []
    for _ in range(count):
        job = ReflectionJob(
            project_name=PROJECT,
            project_root="/tmp/" + PROJECT,
            status="failed",
            phase="ingest",
            source="agent",
            error=error,
        )
        backend.reflection_job_store.save(job)
        jobs.append(job)
    return jobs


# =============================================================================
# Property 3: shape stability
# =============================================================================


def _populate_mixed(backend: LocalMemoryBackend) -> None:
    _seed_fresh_memory(backend)
    _seed_dormant_signal(backend)


def _populate_full(backend: LocalMemoryBackend) -> None:
    _seed_stale_high_risk_rule(backend)
    _seed_fresh_memory(backend)
    _seed_dormant_signal(backend)
    _seed_chronic_cluster(backend)


@pytest.mark.parametrize(
    "populate",
    [
        pytest.param(lambda b: None, id="empty"),
        pytest.param(_populate_mixed, id="mixed"),
        pytest.param(_populate_full, id="populated"),
    ],
)
def test_health_summary_top_level_keys_are_exact_and_ordered(
    backend: LocalMemoryBackend, populate
) -> None:
    """Validates: Requirements 6.5 — keys are exactly the five, in order.

    Property 3 (shape stability): no state mutation changes the key set or
    its order.
    """
    populate(backend)

    report = run(health_summary(backend, PROJECT))

    assert list(report.keys()) == _EXPECTED_KEYS


# =============================================================================
# Property 4: graceful degradation under store failure
# =============================================================================


def test_graceful_degradation_when_candidate_health_raises(
    backend: LocalMemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 6.7 — a failing candidate_health degrades to warnings."""

    async def _boom(structured_store, project_name):  # noqa: ANN001
        raise RuntimeError("candidate store unavailable")

    monkeypatch.setattr(doctor, "candidate_health", _boom)

    report = run(health_summary(backend, PROJECT))

    # Key set + order unchanged even under failure (Req 6.5 + 6.7).
    assert list(report.keys()) == _EXPECTED_KEYS
    # The failed category carries warnings...
    assert report["candidate_health"] == {"warnings": ["candidate store unavailable"]}
    # ...and the others render normally (no warnings key).
    assert "warnings" not in report["reflection_queue"]
    assert "warnings" not in report["signal_freshness"]
    assert "warnings" not in report["chronic_failures"]
    assert "warnings" not in report["maintenance_hints"]
    # Spot-check a normal category still has its real shape.
    assert "all_silent" in report["signal_freshness"]


def test_graceful_degradation_when_chronic_failures_raises(
    backend: LocalMemoryBackend, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validates: Requirements 6.7 — a failing chronic_failures degrades to warnings."""

    async def _boom(job_store, project_name):  # noqa: ANN001
        raise RuntimeError("job store unavailable")

    monkeypatch.setattr(doctor, "chronic_failures", _boom)

    report = run(health_summary(backend, PROJECT))

    assert list(report.keys()) == _EXPECTED_KEYS
    assert report["chronic_failures"] == {"warnings": ["job store unavailable"]}
    assert "warnings" not in report["candidate_health"]
    assert "warnings" not in report["reflection_queue"]
    # Unaffected categories keep their real shapes.
    assert "status_counts" in report["reflection_queue"]


# =============================================================================
# Zero-state symmetry across all five categories
# =============================================================================


def test_zero_state_symmetry_across_categories(backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 6.4 — empty project yields zero/silent everywhere.

    The one deliberate exception is maintenance_hints: a fresh backend has an
    empty vec_embeddings table, so the v1.6.2 check emits an HM-201
    vector-index hint (documented in Task 5's test surface). We assert that
    fresh-backend hint is present rather than asserting an empty hint list.
    """
    report = run(health_summary(backend, PROJECT))

    # reflection_queue: every status count is zero.
    assert all(v == 0 for v in report["reflection_queue"]["status_counts"].values())

    # candidate_health: every covered table has zero pending rows.
    for table_summary in report["candidate_health"].values():
        assert table_summary["pending_count"] == 0

    # signal_freshness: brand-new project is all_silent.
    assert report["signal_freshness"]["all_silent"] is True

    # chronic_failures: nothing recurring.
    assert report["chronic_failures"]["is_chronic"] is False

    # maintenance_hints: fresh backend surfaces the empty vector index (HM-201).
    hints = report["maintenance_hints"]["hints"]
    assert any(h["category"] == "vector_index" and h["code"] == "HM-201" for h in hints)


# =============================================================================
# MCP round-trip
# =============================================================================


@pytest.fixture
def mcp_backend(backend: LocalMemoryBackend):
    """Wire the conftest backend into the MCP server singleton."""
    set_backend_override(backend)
    try:
        yield backend
    finally:
        set_backend_override(None)


def _call_tool(name: str, arguments: dict) -> dict:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }
    response = handle_request(request)
    assert response is not None
    assert "error" not in response, f"RPC error: {response.get('error')}"
    text = response["result"]["content"][0]["text"]
    return json.loads(text)


def test_mcp_health_summary_round_trip(mcp_backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 6.1, 6.2, 6.5 — MCP tool returns the full payload."""
    _populate_full(mcp_backend)

    data = _call_tool("health_summary", {"project_name": PROJECT})

    assert data["success"] is True
    assert data["project_name"] == PROJECT
    # All five category keys present in the response envelope.
    for key in _EXPECTED_KEYS:
        assert key in data, key
    # The chronic cluster we seeded surfaces through the MCP payload.
    assert data["chronic_failures"]["is_chronic"] is True


def test_mcp_health_summary_requires_project_when_no_active(
    mcp_backend: LocalMemoryBackend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Validates: Requirements 6.2 — no project + no active project → error envelope."""
    # Ensure no active project resolves.
    monkeypatch.setattr(
        "harness_mem.mcp.server.get_active_project", lambda: None
    )

    data = _call_tool("health_summary", {})

    assert data["success"] is False
    assert "project_name is required" in data["error"]


# =============================================================================
# CLI block-helper rendering (Task 6.13)
# =============================================================================
#
# Approach taken: a full ``cmd_doctor`` integration test (drives the real
# command end-to-end against a seeded project) PLUS focused block-helper
# render tests (hand-built payload slices) for precise line assertions. The
# integration test proves the wiring; the helper tests pin the exact rendered
# text without the noise of the rest of doctor's output.


def test_cmd_doctor_renders_v242_blocks_and_keeps_queue_block(
    backend: LocalMemoryBackend,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 2.3, 2.4, 3.3, 4.4, 8.x — full cmd_doctor integration.

    Seeds one stale+high-risk candidate, one dormant signal, and one chronic
    failure cluster, then runs ``cmd_doctor`` and asserts all three new blocks
    render their expected lines and the v2.4.0 queue-health block still
    renders unchanged.
    """
    _seed_stale_high_risk_rule(backend)
    _seed_dormant_signal(backend)
    _seed_chronic_cluster(backend)
    # cmd_doctor opens its own backend on the shared data dir, so close ours
    # first to avoid two live SQLite handles racing on the same file.
    run(backend.close())

    set_active_project(PROJECT)
    _ = capsys.readouterr()  # clear any prior output

    exit_code = run(cmd_doctor(PROJECT))
    out = capsys.readouterr().out

    assert exit_code == 0

    # v2.4.0 queue-health block still renders (regression guard).
    assert "Reflection job queue:" in out
    assert "status counts:" in out

    # Candidate-health block: stale + escalated high-risk line.
    assert "Candidate health:" in out
    assert "rule_candidates" in out
    assert "stale pending candidate" in out
    assert "/hm:review-kb" in out
    assert "high-risk stale" in out
    assert "/hm:verify-entry" in out

    # Signal-freshness block: dormant search_hit line (info-level).
    assert "Signal freshness:" in out
    assert "search_hit" in out
    assert "dormant" in out

    # Chronic-failures block.
    assert "Chronic reflection failures" in out
    assert "ingest" in out


def test_candidate_health_block_silent_when_no_stale(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 2.5 — no stale candidates → no output."""
    payload = {
        "rule_candidates": {
            "pending_count": 3,
            "stale_count": 0,
            "high_risk_stale_count": 0,
            "oldest_pending_id": "x",
            "oldest_pending_created_at": "2025-01-01T00:00:00+00:00",
        },
    }
    _doctor_candidate_health_block(payload)
    out = capsys.readouterr().out
    assert out == ""


def test_candidate_health_block_renders_stale_and_high_risk(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 2.3, 2.4 — stale line + escalated high-risk bullet."""
    payload = {
        "memory_entries": {
            "pending_count": 5,
            "stale_count": 3,
            "high_risk_stale_count": 2,
            "oldest_pending_id": "x",
            "oldest_pending_created_at": "2025-01-01T00:00:00+00:00",
        },
    }
    _doctor_candidate_health_block(payload)
    out = capsys.readouterr().out
    assert "memory_entries: 3 stale" in out
    assert "/hm:review-kb" in out
    assert "2 high-risk stale" in out
    assert "/hm:verify-entry" in out


def test_signal_freshness_block_all_silent_summary(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 3.7 — all-silent → one project-named summary line."""
    payload = {"all_silent": True}
    _doctor_signal_freshness_block(payload, PROJECT)
    out = capsys.readouterr().out
    assert "no retrieval signals recorded yet for project demo" in out


def test_signal_freshness_block_only_dormant_types(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 3.5 — fresh types silent, dormant types emitted."""
    payload = {
        "search_hit": {
            "latest_timestamp": "2025-01-01T00:00:00+00:00",
            "age_seconds": 40 * 86400,
            "is_dormant": True,
        },
        "wake_surfaced": {
            "latest_timestamp": "2025-06-01T00:00:00+00:00",
            "age_seconds": 3600,
            "is_dormant": False,
        },
        "supersede_completed": {
            "latest_timestamp": None,
            "age_seconds": None,
            "is_dormant": True,
        },
        "skill_result_success": {
            "latest_timestamp": None,
            "age_seconds": None,
            "is_dormant": True,
        },
        "skill_result_failure": {
            "latest_timestamp": None,
            "age_seconds": None,
            "is_dormant": True,
        },
        "all_silent": False,
    }
    _doctor_signal_freshness_block(payload, PROJECT)
    out = capsys.readouterr().out
    assert "search_hit" in out
    assert "40d ago" in out
    assert "never" in out  # never-seen dormant types
    # Fresh wake_surfaced must NOT appear.
    assert "wake_surfaced" not in out


def test_chronic_failures_block_silent_when_not_chronic(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 4.5 — is_chronic False → no output."""
    payload = {"lookback_days": 7, "threshold": 3, "subcategories": [], "is_chronic": False}
    _doctor_chronic_failures_block(payload)
    out = capsys.readouterr().out
    assert out == ""


def test_chronic_failures_block_renders_subcategories(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 4.4 — header + sub-category counts + offenders."""
    payload = {
        "lookback_days": 7,
        "threshold": 3,
        "subcategories": [
            {
                "label": "ingest",
                "count": 4,
                "top_offenders": [
                    {"job_id": "job-1", "updated_at": "2025-06-01T00:00:00+00:00", "error": "ingest: boom"},
                ],
            }
        ],
        "is_chronic": True,
    }
    _doctor_chronic_failures_block(payload)
    out = capsys.readouterr().out
    assert "Chronic reflection failures (last 7d):" in out
    assert "ingest: × 4" in out
    assert "job-1" in out


def test_maintenance_block_silent_when_no_hints(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 5.3 — empty hint list → no output."""
    _doctor_maintenance_block({"hints": []})
    out = capsys.readouterr().out
    assert out == ""


def test_maintenance_block_renders_hints_verbatim(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 5.2, 5.5 — message + fix_command preserved verbatim."""
    payload = {
        "hints": [
            {
                "category": "vector_index",
                "code": "HM-201",
                "message": "HM-201: Vector index is empty",
                "fix_command": "harness-mem maintenance rebuild-vector-index --project demo",
            }
        ]
    }
    _doctor_maintenance_block(payload)
    out = capsys.readouterr().out
    assert "Maintenance:" in out
    assert "HM-201: Vector index is empty" in out
    assert "Fix: harness-mem maintenance rebuild-vector-index --project demo" in out


def test_blocks_render_degraded_warnings_shape(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 6.7 — each block renders the {warnings: [...]} slice."""
    _doctor_candidate_health_block({"warnings": ["candidate store down"]})
    _doctor_signal_freshness_block({"warnings": ["signal store down"]}, PROJECT)
    _doctor_chronic_failures_block({"warnings": ["job store down"]})
    _doctor_maintenance_block({"warnings": ["index probe down"]})
    out = capsys.readouterr().out
    assert "candidate store down" in out
    assert "signal store down" in out
    assert "job store down" in out
    assert "index probe down" in out


def test_queue_health_block_renders_unchanged(
    backend: LocalMemoryBackend,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Validates: Requirements 8.x — the v2.4.0 queue-health block is untouched.

    Regression guard alongside the v2.4.2 blocks: the frozen v2.4.0 surface
    still renders its header and zero-state lines.
    """
    run(_doctor_queue_health_block(backend.reflection_job_store))
    out = capsys.readouterr().out
    assert "Reflection job queue:" in out
    assert "status counts: pending=0" in out
    assert "oldest waiting age: — (no pending or retryable jobs)" in out


# =============================================================================
# Property 1: read-only invariant across the full health_summary surface
# =============================================================================
#
# health_summary composes five helpers that, between them, read every
# persistence surface the v2.4.2 diagnostics touch:
#
#   - reflection_jobs           (queue_health + chronic_failures)
#   - the five candidate tables (candidate_health)
#   - retrieval_signals         (signal_freshness)
#   - vec_embeddings + the WAL  (maintenance_hints)
#
# Candidates and signals are persisted as JSON blobs under
# ``data_dir/structured/``; reflection jobs live in the ``reflection_jobs``
# SQLite table. We snapshot BOTH surfaces (every JSON blob's bytes + every
# reflection_jobs row) before and after a health_summary call and assert
# byte-equality, so any stray mutator anywhere in the composition would trip
# the assertion (Property 1, Req 1.5/2.6/3.6/4.6/5.4/6.3).


def _snapshot_structured_blobs(backend: LocalMemoryBackend) -> dict[str, str]:
    """Map of every JSON blob path -> content under the structured data dir.

    Covers the five candidate tables and ``retrieval_signals`` (all of which
    persist as ``structured/<table>/<id>.json``).
    """
    snapshot: dict[str, str] = {}
    structured_dir = backend.data_dir / "structured"
    for path in sorted(structured_dir.rglob("*.json")):
        if path.is_file():
            snapshot[str(path.relative_to(structured_dir))] = path.read_text()
    return snapshot


def _snapshot_reflection_jobs(backend: LocalMemoryBackend) -> list[tuple]:
    """Stable snapshot of the reflection_jobs table for read-only assertions."""
    index = backend.structured_store._index  # type: ignore[attr-defined]
    conn = index._conn_write()
    rows = conn.execute(
        "SELECT id, project_name, status, kind, phase, source, "
        "idempotency_key, data, created_at, updated_at, "
        "lease_owner, lease_until, attempt_count "
        "FROM reflection_jobs ORDER BY id"
    ).fetchall()
    return [tuple(row) for row in rows]


def _seed_extra_signals(backend: LocalMemoryBackend) -> None:
    """A fresh + a dormant signal of distinct types, so the snapshot is non-trivial."""
    fresh = RetrievalSignal(
        project_name=PROJECT,
        signal_type="wake_surfaced",
        target_kind="memory_entry",
        target_id="target-fresh",
        recorded_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    dormant = RetrievalSignal(
        project_name=PROJECT,
        signal_type="supersede_completed",
        target_kind="memory_entry",
        target_id="target-dormant",
        recorded_at=datetime.now(timezone.utc) - timedelta(days=45),
    )
    run(backend.structured_store.save_retrieval_signal(fresh))
    run(backend.structured_store.save_retrieval_signal(dormant))


def test_health_summary_is_read_only_across_all_tables(
    backend: LocalMemoryBackend,
) -> None:
    """Validates: Requirements 1.5, 2.6, 3.6, 4.6, 5.4, 6.3 — Property 1.

    Seed a populated project (a stale+high-risk rule candidate, a fresh memory
    candidate, several retrieval signals spanning fresh/dormant, and a chronic
    failed-job cluster), snapshot every candidate/signal JSON blob and every
    reflection_jobs row, run ``health_summary`` once, snapshot again, and assert
    both snapshots are byte-identical. A non-trivial seed ensures the snapshot
    has real content for a mutator to disturb.
    """
    # Populate every surface health_summary reads.
    _seed_stale_high_risk_rule(backend)
    _seed_fresh_memory(backend)
    _seed_dormant_signal(backend)
    _seed_extra_signals(backend)
    _seed_chronic_cluster(backend)

    blobs_before = _snapshot_structured_blobs(backend)
    jobs_before = _snapshot_reflection_jobs(backend)
    # Sanity: the seed is non-trivial, so we're actually guarding something.
    assert blobs_before, "expected seeded candidate/signal blobs"
    assert jobs_before, "expected seeded reflection jobs"

    report = run(health_summary(backend, PROJECT))

    blobs_after = _snapshot_structured_blobs(backend)
    jobs_after = _snapshot_reflection_jobs(backend)

    assert blobs_before == blobs_after
    assert jobs_before == jobs_after
    # And the call we exercised actually produced the full payload (not a
    # degraded shape), so the read-only assertion covers the real code path.
    assert list(report.keys()) == _EXPECTED_KEYS
    assert report["chronic_failures"]["is_chronic"] is True
