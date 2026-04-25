"""REST API smoke tests — verify all HTTP endpoints respond correctly."""

from __future__ import annotations
import asyncio
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from harness_mem.api.server import create_app, set_backend_override  # noqa: E402
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.core.schemas import Observation, MemoryEntry  # noqa: E402
from harness_mem.search.hybrid_search import HybridSearchLayer  # noqa: E402


def run(coro):
    return asyncio.run(coro)


@pytest.fixture
def backend(tmp_path: Path):
    data_dir = tmp_path / "data"
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        yield backend
    finally:
        run(backend.close())


@pytest.fixture
def seeded_backend(backend: LocalMemoryBackend):
    run(_seed_data(backend))
    return backend


@pytest.fixture
def client(seeded_backend: LocalMemoryBackend):
    app = create_app()
    set_backend_override(seeded_backend)
    with TestClient(app) as test_client:
        yield test_client
    set_backend_override(None)


async def _seed_data(backend: LocalMemoryBackend):
    obs = Observation(
        session_id="test-session-001",
        client="claude-code",
        raw_content="We decided to use SQLite FTS5 for full-text search in this project.",
        content_type="transcript",
        metadata={"project_name": "test-project"},
        tags=["session", "claude-code"],
    )
    await backend.verbatim_store.save(obs)

    entry = MemoryEntry(
        project_name="test-project",
        category="architecture",
        content="SQLite FTS5 is used for full-text search indexing",
        confidence=0.9,
        source="manual",
        tags=["architecture", "search"],
    )
    await backend.structured_store.save_memory_entry(entry)


def test_health(client):
    """GET /health — should return server status."""
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data
    print("  [PASS] /health")


def test_search(client):
    """GET /search — should return memory entries and observations."""
    resp = client.get("/search", params={
        "query": "SQLite FTS5",
        "project_name": "test-project",
        "scope": "project",
        "limit": 20,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["memory_entry_count"] >= 1
    assert data["observation_count"] >= 1
    print(f"  [PASS] /search — {data['memory_entry_count']} entries, {data['observation_count']} obs")


def test_search_requires_project_name_for_project_scope(client):
    resp = client.get("/search", params={
        "query": "SQLite FTS5",
        "scope": "project",
    })
    assert resp.status_code == 400
    assert resp.json()["detail"] == "project_name required when scope=project"


def test_search_with_type_filter(client):
    """GET /search with type filter should filter memory entries."""
    resp = client.get("/search", params={
        "query": "SQLite",
        "project_name": "test-project",
        "type": "architecture",
    })
    assert resp.status_code == 200
    data = resp.json()
    for entry in data["memory_entries"]:
        assert entry["category"] == "architecture"
    print("  [PASS] /search with type filter")


def _fake_embed_texts(self, texts: list[str]) -> list[list[float]]:
    return [[1.0, float(len(text))] for text in texts]


def test_search_reports_effective_mode(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", _fake_embed_texts)

    resp = client.get("/search", params={
        "query": "SQLite FTS5",
        "project_name": "test-project",
        "scope": "project",
        "mode": "hybrid",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["requested_mode"] == "hybrid"
    assert data["effective_mode"] == "hybrid"
    assert data["memory_entries"][0]["search_mode"] == "hybrid"


def test_timeline(client):
    """GET /timeline — should return observations for project."""
    resp = client.get("/timeline", params={
        "project_name": "test-project",
        "limit": 50,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    print(f"  [PASS] /timeline — {data['count']} observations")


def test_observations(client):
    """GET /observations — should return observations for session."""
    resp = client.get("/observations", params={
        "project_name": "test-project",
        "session_id": "test-session-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1
    print(f"  [PASS] /observations — {data['count']} observations")


def test_context(client):
    """GET /context/{session_id} — should return session context."""
    resp = client.get("/context/test-session-001", params={
        "project_name": "test-project",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "test-session-001"
    assert "memories" in data
    assert "rules" in data
    assert "recent_sessions" in data
    print(f"  [PASS] /context — {len(data['memories'])} memories, {len(data['rules'])} rules")


def test_context_missing_project_name(client):
    """GET /context/{session_id} without project_name should fail."""
    resp = client.get("/context/test-session-001")
    assert resp.status_code == 400
    print("  [PASS] /context without project_name returns 400")


def test_rules(client):
    """GET /rules — should return confirmed rules for project."""
    resp = client.get("/rules", params={"project_name": "test-project"})
    assert resp.status_code == 200
    data = resp.json()
    assert "rules" in data
    assert "count" in data
    print(f"  [PASS] /rules — {data['count']} rules")


def test_rules_candidates_list(client):
    """GET /rules/candidates — should list rule candidates."""
    resp = client.get("/rules/candidates", params={"project_name": "test-project"})
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data
    print(f"  [PASS] /rules/candidates — {data['count']} candidates")


def test_rules_candidates_create(client):
    """POST /rules/candidates — should create a rule candidate."""
    resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Use SQLite FTS5 for full-text search",
        "trigger": "When setting up search indexing",
        "examples": ["Example: FTS5 query with bm25 ranking"],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "candidate_id" in data
    print(f"  [PASS] /rules/candidates — created {data['candidate_id']}")


def test_rule_confirm(client):
    """POST /rules/{id}/confirm — should confirm a rule candidate."""
    # First create a candidate
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Always validate JWT before API calls",
        "trigger": "Before any authenticated API call",
    })
    candidate_id = create_resp.json()["candidate_id"]

    # Confirm it
    resp = client.post(f"/rules/{candidate_id}/confirm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "confirmed_rule_id" in data
    print(f"  [PASS] /rules/{{id}}/confirm — confirmed {data['confirmed_rule_id']}")


def test_rule_reject(client):
    """POST /rules/{id}/reject — should reject a rule candidate."""
    # First create a candidate
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Pattern to reject",
        "trigger": "Trigger to reject",
    })
    candidate_id = create_resp.json()["candidate_id"]

    # Reject it
    resp = client.post(f"/rules/{candidate_id}/reject", json={"reason": "Test rejection"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    print("  [PASS] /rules/{id}/reject")


def test_rule_feedback(client):
    """POST /rules/{id}/feedback — should accept feedback signals."""
    # First create and confirm a rule
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Pattern for feedback test",
        "trigger": "Trigger for feedback test",
    })
    candidate_id = create_resp.json()["candidate_id"]
    confirm_resp = client.post(f"/rules/{candidate_id}/confirm")
    confirmed_id = confirm_resp.json()["confirmed_rule_id"]

    # Submit positive feedback
    resp = client.post(f"/rules/{confirmed_id}/feedback", json={"signal": "positive"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["signal"] == "positive"
    print("  [PASS] /rules/{id}/feedback — positive feedback accepted")


def test_rule_feedback_invalid_signal(client):
    """POST /rules/{id}/feedback with invalid signal should fail."""
    resp = client.post("/rules/some-id/feedback", json={"signal": "invalid"})
    assert resp.status_code == 400
    print("  [PASS] /rules/{id}/feedback rejects invalid signal")


def test_wakeup_context(client):
    """GET /wakeup/{session_id} — should return wakeup context."""
    resp = client.get("/wakeup/new-session-999", params={
        "project_name": "test-project",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "new-session-999"
    assert "recent_memories" in data
    assert "active_rules" in data
    assert "recommendations" in data
    print(f"  [PASS] /wakeup — {len(data['active_rules'])} active rules")


def test_wakeup_missing_project_name(client):
    """GET /wakeup/{session_id} without project_name should fail."""
    resp = client.get("/wakeup/new-session-999")
    assert resp.status_code == 400
    print("  [PASS] /wakeup without project_name returns 400")


def test_confirm_nonexistent_rule(client):
    """POST /rules/{id}/confirm for nonexistent rule should return 404."""
    resp = client.post("/rules/nonexistent-id/confirm")
    assert resp.status_code == 404
    print("  [PASS] /rules/{id}/confirm returns 404 for nonexistent rule")


def test_reject_nonexistent_rule(client):
    """POST /rules/{id}/reject for nonexistent rule should return 404."""
    resp = client.post("/rules/nonexistent-id/reject")
    assert resp.status_code == 404
    print("  [PASS] /rules/{id}/reject returns 404 for nonexistent rule")
