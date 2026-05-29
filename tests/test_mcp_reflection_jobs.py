"""MCP visibility tests for reflection jobs (Req 7).

Exercises the read-only ``list_reflection_jobs`` and
``get_reflection_job`` MCP tools end-to-end against a real backend +
``ReflectionJobStore``. We seed jobs directly through the store and
then call the tools as a JSON-RPC client would, asserting on the
caller-facing response shape.

The autouse ``data_dir`` fixture in ``tests/conftest.py`` keeps
incidental writes scoped to ``tmp_path`` so we never touch
``~/.harness-mem/`` (per project rules: data path isolation).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from harness_mem.core.schemas import ReflectionJob
from harness_mem.mcp.server import handle_request, set_backend_override
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.reflection_job_store import ReflectionJobStore


pytestmark = pytest.mark.mcp


# ---- fixtures ------------------------------------------------------------


@pytest.fixture
def mcp_backend(backend: LocalMemoryBackend):
    """Wire the conftest backend into the MCP server singleton."""
    set_backend_override(backend)
    try:
        yield backend
    finally:
        set_backend_override(None)


@pytest.fixture
def store(mcp_backend: LocalMemoryBackend) -> ReflectionJobStore:
    """Convenience handle to the same ReflectionJobStore the MCP tools see."""
    return mcp_backend.reflection_job_store


# ---- helpers -------------------------------------------------------------


def _call_tool(name: str, arguments: dict) -> dict:
    """JSON-RPC ``tools/call`` round-trip returning the parsed result."""
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


def _make_job(
    *,
    project_name: str = "demo",
    status: str = "pending",
    kind: str = "reflection",
    phase: str = "ingest",
    source: str = "agent",
    created_at: datetime | None = None,
) -> ReflectionJob:
    """Build a ReflectionJob with the optional kwargs callers care about."""
    kwargs: dict = {
        "project_name": project_name,
        "project_root": "/tmp/" + project_name,
        "status": status,
        "kind": kind,
        "phase": phase,
        "source": source,
    }
    if created_at is not None:
        kwargs["created_at"] = created_at
        kwargs["updated_at"] = created_at
    return ReflectionJob(**kwargs)


def _snapshot_reflection_jobs(backend: LocalMemoryBackend) -> list[dict]:
    """Return all reflection_jobs rows as plain dicts for read-only checks.

    We read the whole row (not just ``data``) so any drift in the index
    columns surfaces too.
    """
    index = backend.structured_store._index  # type: ignore[attr-defined]
    conn = index._conn_write()
    with index._lock:
        rows = conn.execute(
            "SELECT id, project_name, status, kind, phase, source, "
            "data, created_at, updated_at, lease_owner, lease_until, "
            "attempt_count "
            "FROM reflection_jobs ORDER BY id"
        ).fetchall()
    return [dict(row) for row in rows]


# ---- list: empty / order / filters --------------------------------------


def test_list_empty_returns_empty_list(mcp_backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 7.3 (empty filter result is success+empty)."""
    data = _call_tool("list_reflection_jobs", {})
    assert data == {"success": True, "jobs": []}


def test_list_returns_jobs_ordered_by_created_at_desc(
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 7.1 (ORDER BY created_at DESC)."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    older = _make_job(project_name="ord", created_at=base)
    middle = _make_job(project_name="ord", created_at=base + timedelta(hours=1))
    newer = _make_job(project_name="ord", created_at=base + timedelta(hours=2))
    # Save in non-monotonic order so ORDER BY (not insertion order) wins.
    store.save(middle)
    store.save(older)
    store.save(newer)

    data = _call_tool("list_reflection_jobs", {"project_name": "ord"})

    assert data["success"] is True
    job_ids = [job["id"] for job in data["jobs"]]
    assert job_ids == [newer.id, middle.id, older.id]


def test_list_filters_by_project_name(store: ReflectionJobStore) -> None:
    """Validates: Requirements 7.1 (project_name filter)."""
    a = _make_job(project_name="alpha")
    b = _make_job(project_name="beta")
    store.save(a)
    store.save(b)

    data = _call_tool("list_reflection_jobs", {"project_name": "alpha"})

    assert data["success"] is True
    assert {job["id"] for job in data["jobs"]} == {a.id}


def test_list_filters_by_status(store: ReflectionJobStore) -> None:
    """Validates: Requirements 7.1 (status filter)."""
    pending = _make_job(status="pending")
    processing = _make_job(status="processing")
    store.save(pending)
    store.save(processing)

    data = _call_tool("list_reflection_jobs", {"status": "processing"})

    assert data["success"] is True
    assert {job["id"] for job in data["jobs"]} == {processing.id}


# ---- list: invalid inputs -----------------------------------------------


def test_list_invalid_status_returns_error(mcp_backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 7.5 (invalid status surfaces valid set)."""
    data = _call_tool("list_reflection_jobs", {"status": "bogus"})

    assert data["success"] is False
    # Error message must list the valid values so the caller can recover.
    for valid in (
        "pending",
        "processing",
        "completed",
        "failed",
        "retryable",
        "needs_distill",
    ):
        assert valid in data["error"]


def test_list_invalid_kind_returns_error(mcp_backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 7.5 (invalid kind surfaces valid set)."""
    data = _call_tool("list_reflection_jobs", {"kind": "bogus"})

    assert data["success"] is False
    assert "reflection" in data["error"]


# ---- list: limit clamping -----------------------------------------------


def test_list_limit_clamped_to_max_200(store: ReflectionJobStore) -> None:
    """Validates: Requirements 7.1 (server clamps limit to max 200)."""
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    # 250 jobs all in the same project so the filter doesn't constrain
    # the count below 200.
    for i in range(250):
        store.save(
            _make_job(
                project_name="clamp",
                created_at=base + timedelta(seconds=i),
            )
        )

    data = _call_tool(
        "list_reflection_jobs",
        {"project_name": "clamp", "limit": 500},
    )

    assert data["success"] is True
    assert len(data["jobs"]) == 200


# ---- get: hit / miss ----------------------------------------------------


def test_get_returns_job(store: ReflectionJobStore) -> None:
    """Validates: Requirements 7.2 (get returns full to_dict payload)."""
    job = _make_job(project_name="get-hit", status="needs_distill")
    store.save(job)

    data = _call_tool("get_reflection_job", {"job_id": job.id})

    assert data["success"] is True
    payload = data["job"]
    # Spot-check the payload mirrors ReflectionJob.to_dict() — every
    # persisted field round-trips through the JSON layer.
    assert payload["id"] == job.id
    assert payload["project_name"] == "get-hit"
    assert payload["status"] == "needs_distill"
    assert payload["kind"] == "reflection"
    assert payload["source"] == "agent"
    # Datetimes are ISO strings on the wire.
    assert isinstance(payload["created_at"], str)
    assert isinstance(payload["updated_at"], str)


def test_get_unknown_id_returns_error(mcp_backend: LocalMemoryBackend) -> None:
    """Validates: Requirements 7.4 (missing id → success=False / not found)."""
    data = _call_tool(
        "get_reflection_job",
        {"job_id": "nope-not-a-real-id"},
    )

    assert data["success"] is False
    assert "not found" in data["error"].lower()


# ---- read-only invariant ------------------------------------------------


def test_list_and_get_are_read_only(
    mcp_backend: LocalMemoryBackend,
    store: ReflectionJobStore,
) -> None:
    """Validates: Requirements 7.6 (no mutation through visibility tools)."""
    # Seed a small fixture so there's something to read.
    base = datetime(2025, 1, 1, tzinfo=timezone.utc)
    seeded = [
        _make_job(
            project_name="ro",
            status="pending",
            created_at=base,
        ),
        _make_job(
            project_name="ro",
            status="processing",
            created_at=base + timedelta(seconds=1),
        ),
    ]
    for job in seeded:
        store.save(job)

    # Snapshot before any read-only call.
    before = _snapshot_reflection_jobs(mcp_backend)

    # Hammer both tools; neither should mutate the rows.
    list_resp = _call_tool("list_reflection_jobs", {"project_name": "ro"})
    assert list_resp["success"] is True
    get_resp = _call_tool("get_reflection_job", {"job_id": seeded[0].id})
    assert get_resp["success"] is True

    after = _snapshot_reflection_jobs(mcp_backend)

    assert before == after, (
        "list_reflection_jobs / get_reflection_job mutated the table"
    )
