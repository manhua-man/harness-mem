import pytest
from datetime import datetime, timezone
from uuid import uuid4

from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore, _normalize_observation_search_text

@pytest.fixture
def store(tmp_path):
    store = LocalVerbatimStore(tmp_path)
    yield store
    store.close()

def test_normalize_observation_search_text():
    # Test CJK/ASCII boundary addition
    text = "创建ScriptableObject配置"
    normalized = _normalize_observation_search_text(text)
    # Should add spaces: "创建 ScriptableObject 配置"
    assert "创建 ScriptableObject 配置" in normalized
    
    text = "use code_fixer 处理 bug"
    normalized = _normalize_observation_search_text(text)
    assert "use code_fixer 处理 bug" in normalized # Mixed middle
    
    text = "你好world"
    assert "你好 world" == _normalize_observation_search_text(text)
    
    text = "world你好"
    assert "world 你好" == _normalize_observation_search_text(text)

@pytest.mark.anyio
async def test_verbatim_store_soft_delete_lifecycle(store):
    obs_id = str(uuid4())
    obs = Observation(
        id=obs_id,
        session_id="session-1",
        client="test",
        raw_content="Content to be compacted",
        content_type="transcript",
        timestamp=datetime.now(timezone.utc),
        metadata={"project_name": "p1"}
    )
    
    await store.save(obs)
    
    # 1. Normal state
    results = await store.list(session_id="session-1")
    assert len(results) == 1
    
    # 2. Soft delete
    success = await store.soft_delete(obs_id)
    assert success is True
    
    # 3. Should not appear in list
    results = await store.list(session_id="session-1")
    assert len(results) == 0
    
    # 4. Should not appear in timeline
    results = await store.timeline(project_name="p1")
    assert len(results) == 0
    
    # 5. Should not appear in search
    results = await store.search("Content")
    assert len(results) == 0
    
    # 6. Still exists through the runtime truth blob path.
    blob_path = store._blob_path(obs_id)
    assert blob_path.exists()
    
    # 7. Get by ID still works but status is compacted
    retrieved = await store.get(obs_id)
    assert retrieved.compacted is True

@pytest.mark.anyio
async def test_verbatim_store_search_metadata_and_score(store):
    # Ingest two observations for different projects
    for i, project in enumerate(["project-a", "project-b"]):
        obs = Observation(
            id=f"obs-{i}",
            session_id=f"sid-{i}",
            client="test",
            raw_content=f"Common keyword in {project}",
            content_type="transcript",
            timestamp=datetime.now(timezone.utc),
            metadata={"project_name": project}
        )
        await store.save(obs)
    
    # Search with project filter
    results = await store.search("Common", project_name="project-a")
    assert len(results) == 1
    assert results[0].metadata["project_name"] == "project-a"
    
    # Verify score presence
    assert "_fts_score" in results[0].model_extra or "_score" in results[0].model_extra
    
@pytest.mark.anyio
async def test_verbatim_store_delete_physical(store):
    obs_id = str(uuid4())
    obs = Observation(
        id=obs_id,
        session_id="sid",
        client="test",
        raw_content="Delete me",
        content_type="transcript",
        timestamp=datetime.now(timezone.utc)
    )
    await store.save(obs)
    
    blob_path = store._blob_path(obs_id)
    assert blob_path.exists()

    await store.delete(obs_id)

    assert not blob_path.exists()
    assert len(await store.list()) == 0
