from __future__ import annotations

from pathlib import Path

from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from tests.helpers import run


def test_search_matches_ascii_terms_inside_cjk_text(data_dir: Path):
    store = LocalVerbatimStore(data_dir)
    try:
        observation = Observation(
            session_id="sess-unity",
            client="claude-code",
            raw_content="检查ConfigCreator编译失败原因，修复后创建ScriptableObject配置。",
            content_type="transcript",
            metadata={"project_name": "unity-project"},
            tags=["session"],
        )
        run(store.save(observation))

        scriptable_results = run(
            store.search(
                "ScriptableObject",
                project_name="unity-project",
                mode="fts",
            )
        )
        config_results = run(
            store.search(
                "ConfigCreator",
                project_name="unity-project",
                mode="fts",
            )
        )

        assert [result.id for result in scriptable_results] == [observation.id]
        assert [result.id for result in config_results] == [observation.id]
        assert scriptable_results[0].raw_content == observation.raw_content
    finally:
        store.close()
