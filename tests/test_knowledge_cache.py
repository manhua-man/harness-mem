from __future__ import annotations

import json
from pathlib import Path

from harness_mem import cli
from harness_mem.core.schemas.confirmed_rule import ConfirmedRule
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.core.schemas.relation_fact import RelationFact
from harness_mem.knowledge_cache import (
    GENERATED_CLAIM_DIFF_FILENAME,
    GENERATED_CLAIMS_FILENAME,
    GENERATED_ENTITIES_FILENAME,
    GENERATED_INDEX_FILENAME,
    GENERATED_SOURCE_MAP_FILENAME,
    GENERATED_TOPICS_FILENAME,
    build_knowledge_sources,
    cleanup_generated_outputs,
    ensure_knowledge_cache_layout,
    knowledge_cache_health,
    knowledge_cache_paths,
    load_compact_wake_payload,
    rebuild_wiki_bridge,
    render_compact_wake_payload,
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
    assert index_payload["tracked_outputs"] == [
        GENERATED_CLAIMS_FILENAME,
        GENERATED_TOPICS_FILENAME,
        GENERATED_ENTITIES_FILENAME,
        GENERATED_SOURCE_MAP_FILENAME,
        GENERATED_CLAIM_DIFF_FILENAME,
    ]
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


def test_v32_source_map_claims_and_compile_metrics_are_written(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "architecture.md").write_text(
        "# Architecture\nGenerated compiler claims cite source hashes.",
        encoding="utf-8",
    )
    run(
        backend.structured_store.save_memory_entry(
            MemoryEntry(
                project_name=PROJECT,
                category="decision",
                content="Generated claims must stay separate from accepted truth.",
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
    source_map = json.loads(
        (paths.generated_root / GENERATED_SOURCE_MAP_FILENAME).read_text(encoding="utf-8")
    )
    claims_payload = json.loads(
        (paths.generated_root / GENERATED_CLAIMS_FILENAME).read_text(encoding="utf-8")
    )
    index_payload = json.loads(paths.generated_index_path.read_text(encoding="utf-8"))

    assert result["source_count"] == len(source_map["sources"])
    assert result["invalid_claim_count"] == 0
    assert source_map["authority"] == "generated_source_map"
    assert all(item["source_hash"] for item in source_map["sources"])
    assert all("provenance" in item for item in source_map["sources"])
    assert all(claim["citation_spans"] for claim in claims_payload["claims"])
    assert all(claim["content_hash"] for claim in claims_payload["claims"])
    assert index_payload["compiler_version"] == "v3.2"
    assert index_payload["compile_metrics"]["source_count"] == result["source_count"]
    assert index_payload["compile_metrics"]["claim_count"] == result["claim_count"]
    assert index_payload["compile_metrics"]["output_token_estimate"] > 0


def test_v32_compact_payload_rejects_claim_with_hash_drift(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "compact.md").write_text(
        "HashDriftToken appears only in generated material.",
        encoding="utf-8",
    )
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/compact.md"],
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

    paths = knowledge_cache_paths(data_dir, PROJECT)
    index_payload = json.loads(paths.generated_index_path.read_text(encoding="utf-8"))
    for source in index_payload["sources"]:
        if source["source_id"].startswith("curated-doc://"):
            source["source_hash"] = "drifted"
    paths.generated_index_path.write_text(
        json.dumps(index_payload, indent=2),
        encoding="utf-8",
    )

    payload = load_compact_wake_payload(data_dir, project_name=PROJECT)
    assert payload is not None
    assert not any("HashDriftToken" in claim["text"] for claim in payload.claims)
    assert payload.freshness_summary["invalid_claim_count"] >= 1
    assert payload.freshness_summary["citation_valid_claim_count"] == payload.claim_count

    health = run(
        knowledge_cache_health(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )
    assert health["generated_review_queue_count"] >= 1
    assert any(
        item["reason"] in {"hash_drift", "invalid_citation"}
        for item in health["generated_review_queue"]
    )


def test_v32_incremental_rebuild_reuses_unchanged_claims_and_reports_diff(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "architecture.md").write_text(
        "IncrementalToken stays unchanged across rebuilds.",
        encoding="utf-8",
    )
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/architecture.md"],
    )

    first = run(
        rebuild_wiki_bridge(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )
    second = run(
        rebuild_wiki_bridge(
            backend,
            data_dir=data_dir,
            project_name=PROJECT,
            profile=profile,
            project_root=project_root,
        )
    )

    paths = knowledge_cache_paths(data_dir, PROJECT)
    claims_payload = json.loads(
        (paths.generated_root / GENERATED_CLAIMS_FILENAME).read_text(encoding="utf-8")
    )
    diff_payload = json.loads(
        (paths.generated_root / GENERATED_CLAIM_DIFF_FILENAME).read_text(encoding="utf-8")
    )
    index_payload = json.loads(paths.generated_index_path.read_text(encoding="utf-8"))

    assert first["claim_count"] == second["claim_count"]
    assert second["cache_hit_ratio"] == 1.0
    assert all(claim["cache_status"] == "reused" for claim in claims_payload["claims"])
    assert diff_payload["summary"]["unchanged"] == second["claim_count"]
    assert index_payload["compile_metrics"]["cache_hit_ratio"] == 1.0


def test_compact_wake_payload_reads_generated_claims_without_promoting_truth(
    backend,
    data_dir: Path,
    tmp_path: Path,
) -> None:
    project_root = tmp_path / PROJECT
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "compact.md").write_text(
        "CompactOnlyToken appears only in curated generated bridge material.",
        encoding="utf-8",
    )
    profile = ProjectProfile(
        project_name=PROJECT,
        curated_doc_paths=["docs/compact.md"],
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

    payload = load_compact_wake_payload(data_dir, project_name=PROJECT)
    assert payload is not None
    assert payload.authority == "generated_claim"
    assert payload.claim_count >= 1
    assert any("curated-doc://" in source_id for source_id in payload.source_ids)

    rendered = render_compact_wake_payload(payload)
    assert "# Compact Wake  (generated summary, not confirmed truth)" in rendered
    assert "# Trust" in rendered
    assert "CompactOnlyToken" in rendered
    assert "# Drilldown" in rendered
    assert "# Source IDs" in rendered
    assert "does not replace confirmed truth" in rendered

    entries, observations = run(
        search_memory(
            backend,
            project_name=PROJECT,
            query="CompactOnlyToken",
        )
    )
    assert entries == []
    assert observations == []
