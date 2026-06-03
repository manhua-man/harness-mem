from __future__ import annotations

from pathlib import Path

from harness_mem.commands.wake import cmd_wake_up
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.core.schemas.project_profile import ProjectProfile
from tests.helpers import run


def test_confirmed_truth_written_via_store_surfaces_in_cmd_wake_output(
    tmp_path: Path,
    capsys,
    monkeypatch,
) -> None:
    project_name = "v2961-wake-renderer-truth"
    data_dir = tmp_path / "data"

    from harness_mem.commands import wake as wake_module

    monkeypatch.setattr(wake_module, "DEFAULT_DATA_DIR", data_dir)

    backend = LocalMemoryBackend(data_dir)
    run(backend.init())
    try:
        run(
            LocalProjectProfileStore(data_dir).save(
                ProjectProfile(project_name=project_name)
            )
        )
        run(
            backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name=project_name,
                    category="decision",
                    content="Wake renderer should surface confirmed truth written earlier.",
                    source="manual",
                    status="accepted",
                )
            )
        )

        assert run(cmd_wake_up(project_name, no_auto_ingest=True)) == 0
        out = capsys.readouterr().out
    finally:
        run(backend.close())

    assert "# Essential Truth  (L1 · confirmed current)" in out
    assert "Wake renderer should surface confirmed truth written earlier." in out
