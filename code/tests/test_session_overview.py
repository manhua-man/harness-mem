from __future__ import annotations

import json

import pytest

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.commands import session_inventory
from harness_mem.commands.session_overview import build_session_overview
from harness_mem.config.merge import MergedConfig


@pytest.fixture
def overview_fixture(tmp_path, monkeypatch):
    root = tmp_path / "project"
    root.mkdir()
    projects = tmp_path / "cursor"
    for name, text in (("a", "greeting " * 50 + "TAIL_THEME"), ("b", "hello")):
        path = projects / "bucket" / "agent-transcripts" / name / f"{name}.jsonl"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"role": "user", "cwd": str(root), "message": {"content": text}}), encoding="utf-8")
    monkeypatch.setattr(session_inventory, "load_merged_config", lambda *_: MergedConfig())
    monkeypatch.setattr(session_inventory, "build_inspection_adapter", lambda _: CursorAdapter(None, projects_dir=projects))
    data = tmp_path / "data"
    inventory = session_inventory.collect_session_inventory(data, project_root=root, project_name="project", clients=["cursor"])
    pages = [session_inventory.read_session_page(data, project_root=root, project_name="project", session=row) for row in inventory.rows]
    coverage = [{"reference_id": page["session"]["reference_id"], "content_sha256": page["content_sha256"], "offset": 0, "end": page["end"]} for page in pages]
    return data, root, inventory.rows, pages, coverage


def test_overview_requires_complete_coverage_and_allows_multiple_themes(overview_fixture):
    data, root, rows, pages, coverage = overview_fixture
    tail = pages[0]["content"].index("TAIL_THEME")
    topic = {"name": "tail", "evidence": [{"reference_id": rows[0]["reference_id"], "start": tail, "end": tail + 10}]}
    result = build_session_overview(data, project_root=root, project_name="project", sessions=rows, coverage=coverage, topics=[topic, {**topic, "name": "another perspective"}])
    assert result["status"] == "complete"
    assert result["session_count"] == 2
    assert result["topic_memberships"] == 2
    assert result["unclassified"] == [rows[1]["reference_id"]]
    assert not data.exists()
    repeated = build_session_overview(data, project_root=root, project_name="project", sessions=rows, coverage=coverage, topics=[topic, {**topic, "name": "another perspective"}])
    assert result == repeated


def test_only_first_page_is_partial_not_full_analysis(overview_fixture):
    data, root, rows, _pages, coverage = overview_fixture
    coverage[0]["end"] = 10
    result = build_session_overview(data, project_root=root, project_name="project", sessions=rows, coverage=coverage, topics=[])
    assert result["status"] == "partial"
    assert result["not_fully_read"] == [rows[0]["reference_id"]]


def test_tail_theme_cannot_be_claimed_from_unread_range(overview_fixture):
    data, root, rows, pages, coverage = overview_fixture
    tail = pages[0]["content"].index("TAIL_THEME")
    coverage[0]["end"] = 10
    with pytest.raises(ValueError, match="outside inspected"):
        build_session_overview(data, project_root=root, project_name="project", sessions=rows, coverage=coverage,
                               topics=[{"name": "tail", "evidence": [{"reference_id": rows[0]["reference_id"], "start": tail, "end": tail + 10}]}])


def test_changed_digest_or_foreign_reference_rejected(overview_fixture):
    data, root, rows, _pages, coverage = overview_fixture
    coverage[0]["content_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="selected revision"):
        build_session_overview(data, project_root=root, project_name="project", sessions=rows, coverage=coverage, topics=[])
