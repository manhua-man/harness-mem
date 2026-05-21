from __future__ import annotations

from pathlib import Path
import re

import pytest

from harness_mem.core.schemas import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run

pytestmark = pytest.mark.storage


def test_regex_search_observations_hits_and_misses(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-hit",
                    session_id="sess-hit",
                    client="codex",
                    raw_content="The failure code was ERROR-1842 in auth flow.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-miss",
                    session_id="sess-miss",
                    client="codex",
                    raw_content="The failure code was WARN-1842 in billing.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                )
            )
        )

        matches = run(
            backend.verbatim_store.regex_search_observations(
                r"ERROR-\d+",
                project_name="demo",
                limit=10,
            )
        )
        assert [match.observation.id for match in matches] == ["obs-hit"]
        assert "ERROR-1842" in matches[0].snippet
        assert matches[0].candidate_count >= 1

        no_matches = run(
            backend.verbatim_store.regex_search_observations(
                r"NOTFOUND-\d+",
                project_name="demo",
                limit=10,
            )
        )
        assert no_matches == []
    finally:
        run(backend.close())


def test_regex_search_observations_respects_project_and_cjk_ascii(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-demo",
                    session_id="sess-demo",
                    client="codex",
                    raw_content="修复ScriptableObject配置后，错误码为HM-301。",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                )
            )
        )
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-other",
                    session_id="sess-other",
                    client="codex",
                    raw_content="修复ScriptableObject配置后，错误码为HM-301。",
                    content_type="transcript",
                    metadata={"project_name": "other"},
                )
            )
        )

        matches = run(
            backend.verbatim_store.regex_search_observations(
                r"ScriptableObject.*HM-301",
                project_name="demo",
                limit=10,
            )
        )
        assert [match.observation.id for match in matches] == ["obs-demo"]
    finally:
        run(backend.close())


def test_regex_search_observations_invalid_regex_raises(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        with pytest.raises(re.error):
            run(backend.verbatim_store.regex_search_observations(r"ERROR-["))
    finally:
        run(backend.close())


def test_rebuild_exact_index_restores_deleted_postings(data_dir: Path):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-rebuild",
                    session_id="sess-rebuild",
                    client="codex",
                    raw_content="Rebuild sentinel ERROR-301.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                )
            )
        )
        backend.verbatim_store._index.delete_observation_trigrams("obs-rebuild")
        assert run(
            backend.verbatim_store.regex_search_observations(
                r"ERROR-301",
                project_name="demo",
            )
        ) == []

        indexed, postings = run(backend.verbatim_store.rebuild_exact_index("demo"))
        assert indexed == 1
        assert postings > 0
        matches = run(
            backend.verbatim_store.regex_search_observations(
                r"ERROR-301",
                project_name="demo",
            )
        )
        assert [match.observation.id for match in matches] == ["obs-rebuild"]
    finally:
        run(backend.close())
