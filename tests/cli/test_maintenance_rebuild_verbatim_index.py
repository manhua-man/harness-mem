"""Tests for maintenance rebuild-verbatim-index command (v1.7.3)."""

from __future__ import annotations

from harness_mem.commands.maintenance import cmd_rebuild_verbatim_index
from harness_mem.core.schemas import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


def test_rebuild_verbatim_index_restores_exact_search_postings(data_dir, capsys):
    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            backend.verbatim_store.save(
                Observation(
                    id="obs-maint-raw",
                    session_id="maint-raw-session",
                    client="codex",
                    raw_content="Maintenance exact search sentinel ERROR-7301.",
                    content_type="transcript",
                    metadata={"project_name": "demo"},
                )
            )
        )
        backend.verbatim_store._index.delete_observation_trigrams("obs-maint-raw")
    finally:
        run(backend.close())

    assert run(cmd_rebuild_verbatim_index("demo")) == 0
    output = capsys.readouterr().out
    assert "Rebuilding verbatim exact index: demo" in output
    assert "Done: 1 observations" in output

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        matches = run(
            backend.verbatim_store.regex_search_observations(
                r"ERROR-7301",
                project_name="demo",
            )
        )
        assert [match.observation.id for match in matches] == ["obs-maint-raw"]
    finally:
        run(backend.close())
