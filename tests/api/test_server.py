from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from harness_mem.api.server import create_app, set_backend_override
from harness_mem.core.schemas import ConfirmedRule, MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import fake_embed_texts, run, seed_search_backend

pytestmark = pytest.mark.api


@pytest.fixture
def seeded_backend(backend: LocalMemoryBackend):
    run(seed_search_backend(backend))
    return backend


@pytest.fixture
def client(seeded_backend: LocalMemoryBackend):
    app = create_app()
    set_backend_override(seeded_backend)
    with TestClient(app) as test_client:
        yield test_client
    set_backend_override(None)


def test_health(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_search(client: TestClient):
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


def test_search_requires_project_name_for_project_scope(client: TestClient):
    resp = client.get("/search", params={
        "query": "SQLite FTS5",
        "scope": "project",
    })
    assert resp.status_code == 400
    assert resp.json()["detail"] == "project_name required when scope=project"


def test_search_with_type_filter(client: TestClient):
    resp = client.get("/search", params={
        "query": "SQLite",
        "project_name": "test-project",
        "type": "architecture",
    })
    assert resp.status_code == 200
    data = resp.json()
    for entry in data["memory_entries"]:
        assert entry["category"] == "architecture"


def test_search_scope_all_includes_project_context(
    client: TestClient,
    seeded_backend: LocalMemoryBackend,
):
    run(
        LocalProjectProfileStore(seeded_backend.data_dir).save(
            ProjectProfile(
                project_name="test-project",
                stacks=["python", "sqlite"],
            )
        )
    )

    resp = client.get("/search", params={
        "query": "SQLite",
        "scope": "all",
        "mode": "fts",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["memory_entries"][0]["project_name"] == "test-project"
    assert data["memory_entries"][0]["tech_stack"] == ["python", "sqlite"]
    assert data["observations"][0]["project_name"] == "test-project"
    assert data["observations"][0]["tech_stack"] == ["python", "sqlite"]


def test_search_reports_effective_mode(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(HybridSearchLayer, "_embed_texts", fake_embed_texts)

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


def test_search_include_history_returns_historical_entries(
    client: TestClient,
    seeded_backend: LocalMemoryBackend,
):
    run(
        seeded_backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name="test-project",
                category="decision",
                content="Historical API temporal sentinel used Vue.",
                source="manual",
                valid_to=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    default_resp = client.get("/search", params={
        "query": "API temporal sentinel",
        "project_name": "test-project",
        "scope": "project",
        "mode": "fts",
    })
    assert default_resp.status_code == 200
    assert default_resp.json()["memory_entry_count"] == 0

    history_resp = client.get("/search", params={
        "query": "API temporal sentinel",
        "project_name": "test-project",
        "scope": "project",
        "mode": "fts",
        "include_history": True,
    })
    assert history_resp.status_code == 200
    data = history_resp.json()
    assert data["include_history"] is True
    assert data["memory_entry_count"] == 1
    assert data["memory_entries"][0]["is_historical"] is True


def test_timeline(client: TestClient):
    resp = client.get("/timeline", params={
        "project_name": "test-project",
        "limit": 50,
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1


def test_observations(client: TestClient):
    resp = client.get("/observations", params={
        "project_name": "test-project",
        "session_id": "test-session-001",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] >= 1


def test_context(client: TestClient):
    resp = client.get("/context/test-session-001", params={
        "project_name": "test-project",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "test-session-001"
    assert "memories" in data
    assert "rules" in data
    assert "recent_sessions" in data


def test_context_missing_project_name(client: TestClient):
    resp = client.get("/context/test-session-001")
    assert resp.status_code == 400


def test_rules(client: TestClient):
    resp = client.get("/rules", params={"project_name": "test-project"})
    assert resp.status_code == 200
    data = resp.json()
    assert "rules" in data
    assert "count" in data


def test_rules_include_history(
    client: TestClient,
    seeded_backend: LocalMemoryBackend,
):
    run(
        seeded_backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                project_name="test-project",
                pattern="Historical API rule used the old route.",
                trigger="When checking API temporal history",
                source_candidate_id="candidate-old",
                valid_to=datetime.now(timezone.utc) - timedelta(days=1),
            )
        )
    )

    default_resp = client.get("/rules", params={"project_name": "test-project"})
    assert default_resp.status_code == 200
    assert all(
        rule["pattern"] != "Historical API rule used the old route."
        for rule in default_resp.json()["rules"]
    )

    history_resp = client.get("/rules", params={
        "project_name": "test-project",
        "include_history": True,
    })
    assert history_resp.status_code == 200
    old_rule = next(
        rule
        for rule in history_resp.json()["rules"]
        if rule["pattern"] == "Historical API rule used the old route."
    )
    assert old_rule["is_historical"] is True


def test_rules_candidates_list(client: TestClient):
    resp = client.get("/rules/candidates", params={"project_name": "test-project"})
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data


def test_rules_candidates_create(client: TestClient):
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


def test_rule_confirm(client: TestClient):
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Always validate JWT before API calls",
        "trigger": "Before any authenticated API call",
    })
    candidate_id = create_resp.json()["candidate_id"]

    resp = client.post(f"/rules/{candidate_id}/confirm")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "confirmed_rule_id" in data


def test_rule_reject(client: TestClient):
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Pattern to reject",
        "trigger": "Trigger to reject",
    })
    candidate_id = create_resp.json()["candidate_id"]

    resp = client.post(f"/rules/{candidate_id}/reject", json={"reason": "Test rejection"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True


def test_rule_feedback(client: TestClient):
    create_resp = client.post("/rules/candidates", json={
        "project_name": "test-project",
        "session_id": "test-session-001",
        "pattern": "Pattern for feedback test",
        "trigger": "Trigger for feedback test",
    })
    candidate_id = create_resp.json()["candidate_id"]
    confirm_resp = client.post(f"/rules/{candidate_id}/confirm")
    confirmed_id = confirm_resp.json()["confirmed_rule_id"]

    resp = client.post(f"/rules/{confirmed_id}/feedback", json={"signal": "positive"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["signal"] == "positive"


def test_rule_feedback_invalid_signal(client: TestClient):
    resp = client.post("/rules/some-id/feedback", json={"signal": "invalid"})
    assert resp.status_code == 400


def test_wakeup_context(client: TestClient):
    resp = client.get("/wakeup/new-session-999", params={
        "project_name": "test-project",
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["session_id"] == "new-session-999"
    assert "recent_memories" in data
    assert "active_rules" in data
    assert "recommendations" in data


def test_wakeup_missing_project_name(client: TestClient):
    resp = client.get("/wakeup/new-session-999")
    assert resp.status_code == 400


def test_confirm_nonexistent_rule(client: TestClient):
    resp = client.post("/rules/nonexistent-id/confirm")
    assert resp.status_code == 404


def test_reject_nonexistent_rule(client: TestClient):
    resp = client.post("/rules/nonexistent-id/reject")
    assert resp.status_code == 404
