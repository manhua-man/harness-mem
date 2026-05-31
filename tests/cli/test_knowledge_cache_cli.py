from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness_mem import cli
from harness_mem.commands import maintenance as maintenance_module
from harness_mem.commands.doctor import cmd_doctor
from harness_mem.commands.maintenance import (
    cmd_cleanup_generated_cache,
    cmd_prepare_knowledge_cache,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.knowledge_cache import ensure_knowledge_cache_layout, knowledge_cache_paths
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


def test_doctor_reports_knowledge_cache_boundary_visibility(
    backend,
    data_dir: Path,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    project_root = tmp_path / "demo"
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "architecture.md").write_text("doc", encoding="utf-8")
    run(
        LocalProjectProfileStore(data_dir).save(
            ProjectProfile(
                project_name="demo",
                curated_doc_paths=["docs/architecture.md"],
            )
        )
    )
    cli.cmd_use("demo")

    previous_find_project_root = maintenance_module.find_project_root
    maintenance_module.find_project_root = lambda _project: project_root
    try:
        assert run(cmd_prepare_knowledge_cache("demo")) == 0
        capsys.readouterr()
        assert run(cmd_doctor("demo")) == 0
    finally:
        maintenance_module.find_project_root = previous_find_project_root

    output = capsys.readouterr().out
    assert "Knowledge cache:" in output
    assert "boundary:" in output
    assert "sources: 2 tracked (1 curated docs)" in output
    assert "sync map:" in output


def test_cleanup_generated_cache_preview_and_apply(
    data_dir: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    cli.cmd_use("demo")
    paths = knowledge_cache_paths(data_dir, "demo")
    ensure_knowledge_cache_layout(paths)
    claims_dir = paths.generated_root / "claims"
    claims_dir.mkdir(parents=True, exist_ok=True)
    tracked = claims_dir / "tracked.json"
    orphan = claims_dir / "orphan.json"
    tracked.write_text("{}", encoding="utf-8")
    orphan.write_text("{}", encoding="utf-8")
    paths.generated_index_path.write_text(
        json.dumps({"tracked_outputs": ["claims/tracked.json"]}, indent=2),
        encoding="utf-8",
    )

    assert run(cmd_cleanup_generated_cache("demo", apply=False)) == 0
    preview_output = capsys.readouterr().out
    assert "Would remove 1 orphaned generated output(s)" in preview_output
    assert orphan.exists()

    assert run(cmd_cleanup_generated_cache("demo", apply=True)) == 0
    apply_output = capsys.readouterr().out
    assert "Removed 1 orphaned generated output(s)" in apply_output
    assert not orphan.exists()
    assert tracked.exists()


def test_cli_help_lists_new_knowledge_cache_maintenance_actions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        ["harness-mem", "maintenance", "--help"],
    )
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "prepare-knowledge-cache" in output
    assert "cleanup-generated-cache" in output
