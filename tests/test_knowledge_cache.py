from __future__ import annotations

import json
from pathlib import Path

from harness_mem import cli
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.knowledge_cache import (
    GENERATED_INDEX_FILENAME,
    build_knowledge_sources,
    cleanup_generated_outputs,
    ensure_knowledge_cache_layout,
    knowledge_cache_health,
    knowledge_cache_paths,
    rebuild_wiki_bridge,
    write_knowledge_cache_boundary,
)
from harness_mem.read_api import search_memory
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from tests.helpers import run


PROJECT = "demo"


def test_prepare_knowledge_cache_writes_manual_generated_split_and_sync_map(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "architecture.md").write_text("# architecture", encoding="utf-8")

    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name=PROJECT,
                category="decision",
                content="Use SQLite FTS5 for local retrieval.",
                source="manual",
            )
        )
    )
    run(
        LocalProjectProfileStore(data_dir).save(
            ProjectProfile(
                project_name=PROJECT,
                curated_doc_paths=["docs/architecture.md"],
            )
        )
    )

    from harness_mem.commands.maintenance import cmd_prepare_knowledge_cache
    from harness_mem.commands import maintenance as maintenance_module

    cli.cmd_use(PROJECT)
    previous_find_project_root = maintenance_module.find_project_root
    maintenance_module.find_project_root = lambda _project: project_root
    try:
        assert run(cmd_prepare_knowledge_cache(PROJECT)) == 0
    finally:
        maintenance_module.find_project_root = previous_find_project_root

    paths = knowledge_cache_paths(data_dir, PROJECT)
    assert paths.manual_root.exists()
    assert paths.generated_root.exists()
    sync_map = json.loads(paths.sync_map_path.read_text(encoding="utf-8"))
    assert sync_map["project_name"] == PROJECT
    assert {item["source_kind"] for item in sync_map["sources"]} == {
        "accepted_memory",
        "curated_doc",
    }
    manifest = json.loads(paths.source_manifest_path.read_text(encoding="utf-8"))
    assert len(manifest["sources"]) == 2
    assert all(item["source_hash"] for item in manifest["sources"])


def test_knowledge_cache_health_flags_stale_sources_and_orphaned_generated_outputs(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    curated_doc = docs_dir / "reference.md"
    curated_doc.write_text("v1", encoding="utf-8")
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/reference.md"],
    )

    paths = knowledge_cache_paths(data_dir, PROJECT)
    ensure_knowledge_cache_layout(paths)
    sources = run(
        build_knowledge_sources(
            backend,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )
    write_knowledge_cache_boundary(paths, project_name=PROJECT, sources=sources)
    curated_doc.write_text("v2", encoding="utf-8")

    orphan = paths.generated_root / "claims" / "orphan.json"
    orphan.parent.mkdir(parents=True, exist_ok=True)
    orphan.write_text("{}", encoding="utf-8")
    report = run(
        knowledge_cache_health(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )

    assert report["prepared"] is True
    assert report["stale_source_count"] == 1
    assert report["orphaned_output_count"] == 1
    assert report["orphaned_outputs"][0].endswith("orphan.json")


def test_cleanup_generated_outputs_removes_orphans_only_when_apply(data_dir: Path) -> None:
    paths = knowledge_cache_paths(data_dir, PROJECT)
    ensure_knowledge_cache_layout(paths)

    tracked_dir = paths.generated_root / "claims"
    tracked_dir.mkdir(parents=True, exist_ok=True)
    tracked = tracked_dir / "tracked.json"
    orphan = tracked_dir / "orphan.json"
    tracked.write_text("{}", encoding="utf-8")
    orphan.write_text("{}", encoding="utf-8")
    paths.generated_index_path.write_text(
        json.dumps({"tracked_outputs": ["claims/tracked.json"]}, indent=2),
        encoding="utf-8",
    )

    preview = cleanup_generated_outputs(data_dir, project_name=PROJECT, apply=False)
    assert preview["orphaned_count"] == 1
    assert orphan.exists()
    assert tracked.exists()

    applied = cleanup_generated_outputs(data_dir, project_name=PROJECT, apply=True)
    assert applied["removed_count"] == 1
    assert not orphan.exists()
    assert tracked.exists()
    assert paths.generated_index_path.name == GENERATED_INDEX_FILENAME


def test_rebuild_wiki_bridge_writes_claim_topic_entity_indexes(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "architecture.md").write_text(
        "# Architecture\nSQLite FTS5 powers retrieval.\nCodex uses ProjectProfile docs.",
        encoding="utf-8",
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name=PROJECT,
                category="decision",
                content="Use SQLite FTS5 for local retrieval.",
                source="manual",
            )
        )
    )
    run(
        backend.structured_store.save_confirmed_rule(
            ConfirmedRule(
                project_name=PROJECT,
                pattern="prefer narrow generated cache rebuilds",
                trigger="editing knowledge-cache artifacts",
                source_candidate_id="seed",
            )
        )
    )
    run(
        backend.structured_store.save_relation_fact(
            RelationFact(
                project_name=PROJECT,
                source_entity="KnowledgeCache",
                relation_type="depends_on",
                target_entity="SQLite",
                evidence="Knowledge cache metadata is persisted in SQLite-backed storage.",
                source="manual",
            )
        )
    )
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/architecture.md"],
    )

    result = run(
        rebuild_wiki_bridge(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )

    paths = knowledge_cache_paths(data_dir, PROJECT)
    claims_payload = json.loads((paths.generated_root / "claims.json").read_text(encoding="utf-8"))
    topics_payload = json.loads((paths.generated_root / "topics.json").read_text(encoding="utf-8"))
    entities_payload = json.loads((paths.generated_root / "entities.json").read_text(encoding="utf-8"))
    index_payload = json.loads(paths.generated_index_path.read_text(encoding="utf-8"))

    assert result["claim_count"] == len(claims_payload["claims"])
    assert result["topic_count"] == len(topics_payload["topics"])
    assert result["entity_count"] == len(entities_payload["entities"])
    assert index_payload["tracked_outputs"] == ["claims.json", "topics.json", "entities.json"]
    assert index_payload["counts"]["claims"] == len(claims_payload["claims"])
    assert all(claim["authority"] == "generated_claim" for claim in claims_payload["claims"])
    assert all(claim["source_refs"] for claim in claims_payload["claims"])
    assert any(
        ref["drilldown"].get("memory_entry_id")
        for claim in claims_payload["claims"]
        for ref in claim["source_refs"]
    )
    assert any(topic["topic"] == "decision" for topic in topics_payload["topics"])
    assert any(entity["entity"] == "KnowledgeCache" for entity in entities_payload["entities"])


def test_generated_wiki_bridge_does_not_enter_default_search_truth_surfaces(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "generated.md").write_text(
        "GeneratedOnlyToken appears only inside curated wiki bridge material.",
        encoding="utf-8",
    )
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/generated.md"],
    )
    run(
        rebuild_wiki_bridge(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )

    entries, observations = run(
        search_memory(
            backend,
            project_name=PROJECT,
            query="GeneratedOnlyToken",
        )
    )
    assert entries == []
    assert observations == []
