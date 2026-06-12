"""Maintenance commands.

v1.6.0 introduced ``maintenance assign-memory-types``: a one-shot,
idempotent backfill that persists the ``memory_type`` field for legacy
``MemoryEntry`` blobs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from harness_mem.knowledge_cache import (
    cleanup_generated_outputs,
    ensure_knowledge_cache_layout,
    knowledge_cache_paths,
    write_knowledge_cache_boundary,
    build_knowledge_sources,
    rebuild_wiki_bridge,
)
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    find_project_root,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.core.schemas.memory_entry import MemoryType, _derive_memory_type
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore
from harness_mem.storage.store_v2_migration import (
    StorageV2MigrationError,
    apply_store_v2_migration,
    build_migration_plan,
    export_store_v2_json_snapshot,
)
from harness_mem.storage.canonical_store import (
    build_canonical_store,
    export_json_snapshot,
)


_BLOB_GLOB = "*.json"


def _list_memory_entry_blobs(data_dir: Path) -> list[Path]:
    blob_dir = data_dir / "structured" / "memory_entries"
    if not blob_dir.exists():
        return []
    return sorted(blob_dir.glob(_BLOB_GLOB))


async def cmd_assign_memory_types(
    project_name: str | None,
    *,
    apply: bool,
) -> int:
    """Backfill ``memory_type`` on legacy MemoryEntry blobs."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance assign-memory-types",
    )
    if not resolved_project:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        blobs = _list_memory_entry_blobs(DEFAULT_DATA_DIR)
        already_typed = 0
        candidates: list[tuple[Path, dict[str, Any], MemoryType]] = []

        for blob_path in blobs:
            try:
                data = json.loads(blob_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if data.get("project_name") != resolved_project:
                continue
            if "memory_type" in data and data["memory_type"] is not None:
                already_typed += 1
                continue
            derived = _derive_memory_type(data.get("category"))
            candidates.append((blob_path, data, derived))

        update_count = len(candidates)

        if not apply:
            print(
                f"Would update {update_count} MemoryEntry rows "
                f"({already_typed} already typed)."
            )
            for blob_path, data, derived in candidates[:10]:
                category = data.get("category") or "unknown"
                entry_id = data.get("id") or blob_path.stem
                print(f"- {entry_id} (category={category}) -> {derived}")
            if len(candidates) > 10:
                print(f"  ... and {len(candidates) - 10} more")
            print("No changes written. Use --apply to commit.")
            log_command_invoked(
                "maintenance.assign-memory-types",
                project_name=resolved_project,
                extra={
                    "apply": False,
                    "would_update": update_count,
                    "already_typed": already_typed,
                },
            )
            return 0

        for blob_path, data, derived in candidates:
            data["memory_type"] = derived
            blob_path.write_text(
                json.dumps(data, indent=2, default=str),
                encoding="utf-8",
            )

        print(f"Updated {update_count} MemoryEntry rows.")
        log_command_invoked(
            "maintenance.assign-memory-types",
            project_name=resolved_project,
            extra={
                "apply": True,
                "updated": update_count,
                "already_typed": already_typed,
            },
        )
        return 0
    finally:
        await backend.close()


async def cmd_rebuild_vector_index(project_name: str | None = None) -> int:
    """Rebuild persisted vector rows for structured and verbatim stores."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance rebuild-vector-index",
    )
    if not resolved_project:
        return 1

    print(f"Rebuilding vector index: {resolved_project}")
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        from harness_mem.commands.support import get_embedding_model_id

        model_id = get_embedding_model_id()
        print(f"Model: {model_id}")

        structured_store = cast(LocalStructuredStore, backend.structured_store)
        verbatim_store = cast(LocalVerbatimStore, backend.verbatim_store)
        structured_index = structured_store._index
        verbatim_index = verbatim_store._index
        for index in (structured_index, verbatim_index):
            conn = index._conn_write()
            conn.execute("DROP TABLE IF EXISTS vec_embeddings")
            conn.commit()
            index.init_db()

        entries = await structured_store.list_memory_entries(
            resolved_project,
            limit=100000,
        )
        for i, entry in enumerate(entries, 1):
            print(f"Rebuilding vector index: {i}/{len(entries)} entries")
            structured_index.persist_embedding(entry.id, entry.content, model_id)

        observations = await verbatim_store.list(limit=100000)
        project_observations = [
            observation
            for observation in observations
            if observation.metadata.get("project_name") == resolved_project
        ]
        for i, observation in enumerate(project_observations, 1):
            print(f"Rebuilding vector index: {i}/{len(project_observations)} observations")
            verbatim_index.persist_embedding(
                observation.id,
                observation.raw_content,
                model_id,
            )

        print(
            f"Done: {len(entries)} entries, "
            f"{len(project_observations)} observations"
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        await backend.close()


async def cmd_rebuild_verbatim_index(project_name: str | None = None) -> int:
    """Rebuild exact regex trigram postings for observation raw_content."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance rebuild-verbatim-index",
    )
    if not resolved_project:
        return 1

    print(f"Rebuilding verbatim exact index: {resolved_project}")
    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        verbatim_store = cast(LocalVerbatimStore, backend.verbatim_store)
        indexed, postings = await verbatim_store.rebuild_exact_index(resolved_project)
        print(f"Done: {indexed} observations, {postings} trigram postings")
        log_command_invoked(
            "maintenance.rebuild-verbatim-index",
            project_name=resolved_project,
            extra={"indexed_observations": indexed, "postings": postings},
        )
        return 0
    except Exception as exc:
        print(f"Error: {exc}")
        return 1
    finally:
        await backend.close()


async def cmd_prepare_knowledge_cache(project_name: str | None = None) -> int:
    """Prepare the v2.6.0 knowledge-cache boundary metadata for a project."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance prepare-knowledge-cache",
    )
    if not resolved_project:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        profile = await LocalProjectProfileStore(DEFAULT_DATA_DIR).get(resolved_project)
        paths = knowledge_cache_paths(DEFAULT_DATA_DIR, resolved_project)
        ensure_knowledge_cache_layout(paths)
        sources = await build_knowledge_sources(
            backend,
            project_name=resolved_project,
            profile=profile,
            project_root=find_project_root(resolved_project),
        )
        write_knowledge_cache_boundary(
            paths,
            project_name=resolved_project,
            sources=sources,
        )
        print(f"Prepared knowledge cache boundary: {resolved_project}")
        print(f"Manual root: {paths.manual_root}")
        print(f"Generated root: {paths.generated_root}")
        print(f"Sync map: {paths.sync_map_path}")
        print(f"Source manifest: {paths.source_manifest_path}")
        print(f"Sources tracked: {len(sources)}")
        log_command_invoked(
            "maintenance.prepare-knowledge-cache",
            project_name=resolved_project,
            extra={"source_count": len(sources)},
        )
        return 0
    finally:
        await backend.close()


async def cmd_cleanup_generated_cache(
    project_name: str | None,
    *,
    apply: bool,
) -> int:
    """Clean orphaned generated knowledge-cache outputs without touching truth."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance cleanup-generated-cache",
    )
    if not resolved_project:
        return 1

    result = cleanup_generated_outputs(
        DEFAULT_DATA_DIR,
        project_name=resolved_project,
        apply=apply,
    )
    if apply:
        print(
            f"Removed {result['removed_count']} orphaned generated output(s) "
            f"for {resolved_project}."
        )
    else:
        print(
            f"Would remove {result['orphaned_count']} orphaned generated output(s) "
            f"for {resolved_project}."
        )
        print("No changes written. Use --apply to commit.")
    for output_path in result["orphaned_outputs"][:10]:
        print(f"- {output_path}")
    if len(result["orphaned_outputs"]) > 10:
        print(f"  ... and {len(result['orphaned_outputs']) - 10} more")
    log_command_invoked(
        "maintenance.cleanup-generated-cache",
        project_name=resolved_project,
        extra={
            "apply": apply,
            "orphaned_count": result["orphaned_count"],
            "removed_count": result["removed_count"],
        },
    )
    return 0


async def cmd_migrate_store_v2(
    project_name: str | None,
    *,
    apply: bool,
    export_rollback: str | None = None,
) -> int:
    """Run the explicit v4.0.0 Storage v2 migration contract."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance migrate-store-v2",
    )
    if not resolved_project:
        return 1

    try:
        if export_rollback:
            result = export_store_v2_json_snapshot(
                DEFAULT_DATA_DIR,
                Path(export_rollback),
                project_name=resolved_project,
                apply=apply,
            )
            if apply:
                print(f"Exported Storage v2 rollback snapshot: {resolved_project}")
            else:
                print(f"Storage v2 rollback export dry run: {resolved_project}")
            print(f"Export dir: {result['export_dir']}")
            print(f"Would export JSON files: {result['would_export_json_file_count']}")
            print(f"Exported JSON files: {result['exported_json_file_count']}")
            print(f"Rollback checksum match: {str(result['rollback_checksum_match']).lower()}")
            if not apply:
                print("No changes written. Use --apply to write the rollback snapshot.")
            print(json.dumps(result, indent=2, sort_keys=True))
            log_command_invoked(
                "maintenance.migrate-store-v2",
                project_name=resolved_project,
                extra={
                    "action": "export_rollback",
                    "apply": apply,
                    "would_export_json_file_count": result[
                        "would_export_json_file_count"
                    ],
                    "exported_json_file_count": result["exported_json_file_count"],
                    "rollback_checksum_match": result["rollback_checksum_match"],
                },
            )
            return 0 if result["rollback_checksum_match"] else 1

        if not apply:
            plan = build_migration_plan(DEFAULT_DATA_DIR, project_name=resolved_project)
            print(f"Storage v2 migration dry run: {resolved_project}")
            print(f"Legacy JSON files: {plan['legacy_json_file_count']}")
            print(f"Invalid JSON files: {plan['invalid_json_count']}")
            print(f"Logical checksum: {plan['logical_checksum']}")
            print("Default storage changed: false")
            print("No changes written. Use --apply to write the side-by-side canonical DB.")
            print(json.dumps(plan, indent=2, sort_keys=True))
            log_command_invoked(
                "maintenance.migrate-store-v2",
                project_name=resolved_project,
                extra={
                    "action": "dry_run",
                    "legacy_json_file_count": plan["legacy_json_file_count"],
                    "invalid_json_count": plan["invalid_json_count"],
                },
            )
            return 0 if plan["invalid_json_count"] == 0 else 1

        result = apply_store_v2_migration(DEFAULT_DATA_DIR, project_name=resolved_project)
        canonical = build_canonical_store(DEFAULT_DATA_DIR, project_name=resolved_project)
        print(f"Applied Storage v2 side-by-side migration: {resolved_project}")
        print(f"Canonical DB: {result['canonical_db_path']}")
        print(f"Migrated rows: {result['migrated_row_count']}")
        print(f"Checksum match: {str(result['checksum_match']).lower()}")
        print(f"Canonical entity rows: {canonical['canonical_row_count']}")
        print("Default storage changed: false")
        print(json.dumps({**result, "canonical_store": canonical}, indent=2, sort_keys=True))
        log_command_invoked(
            "maintenance.migrate-store-v2",
            project_name=resolved_project,
            extra={
                "action": "apply",
                "migrated_row_count": result["migrated_row_count"],
                "checksum_match": result["checksum_match"],
                "canonical_row_count": canonical["canonical_row_count"],
            },
        )
        return 0 if result["checksum_match"] and canonical["checksum_match"] else 1
    except StorageV2MigrationError as exc:
        print(f"Error: {exc}")
        return 1


async def cmd_export_json_snapshot(
    project_name: str | None,
    export_dir: str,
    *,
    apply: bool,
) -> int:
    """Export the v4.0.1 canonical store to a human-readable JSON snapshot."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance export-json-snapshot",
    )
    if not resolved_project:
        return 1

    try:
        result = export_json_snapshot(
            DEFAULT_DATA_DIR,
            Path(export_dir),
            project_name=resolved_project,
            apply=apply,
        )
    except StorageV2MigrationError as exc:
        print(f"Error: {exc}")
        return 1

    if apply:
        print(f"Exported Storage v2 JSON snapshot: {resolved_project}")
    else:
        print(f"Storage v2 JSON snapshot dry run: {resolved_project}")
    print(f"Export dir: {result['export_dir']}")
    print(f"Would export JSON files: {result['would_export_json_file_count']}")
    print(f"Exported JSON files: {result['exported_json_file_count']}")
    print(f"Snapshot checksum match: {str(result['snapshot_checksum_match']).lower()}")
    if not apply:
        print("No changes written. Use --apply to write the JSON snapshot.")
    print(json.dumps(result, indent=2, sort_keys=True))
    log_command_invoked(
        "maintenance.export-json-snapshot",
        project_name=resolved_project,
        extra={
            "apply": apply,
            "would_export_json_file_count": result["would_export_json_file_count"],
            "exported_json_file_count": result["exported_json_file_count"],
            "snapshot_checksum_match": result["snapshot_checksum_match"],
        },
    )
    return 0 if result["snapshot_checksum_match"] else 1


async def cmd_rebuild_wiki_bridge(project_name: str | None = None) -> int:
    """Rebuild generated wiki-bridge artifacts from accepted sources."""
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance rebuild-wiki-bridge",
    )
    if not resolved_project:
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        profile = await LocalProjectProfileStore(DEFAULT_DATA_DIR).get(resolved_project)
        result = await rebuild_wiki_bridge(
            backend,
            data_dir=DEFAULT_DATA_DIR,
            project_name=resolved_project,
            profile=profile,
            project_root=find_project_root(resolved_project),
        )
        print(f"Rebuilt wiki bridge: {resolved_project}")
        print(f"Claims: {result['claim_count']}")
        print(f"Invalid claims: {result['invalid_claim_count']}")
        print(f"Topics: {result['topic_count']}")
        print(f"Entities: {result['entity_count']}")
        print(f"Sources: {result['source_count']}")
        print(f"Cache hit ratio: {result['cache_hit_ratio']:.2f}")
        print(f"Compile duration: {result['compile_duration_ms']} ms")
        print(f"Output token estimate: {result['output_token_estimate']}")
        print(
            "Claim diff: "
            f"+{result['claim_diff']['added']} "
            f"-{result['claim_diff']['removed']} "
            f"~{result['claim_diff']['changed']} "
            f"={result['claim_diff']['unchanged']}"
        )
        print(f"Source map: {result['source_map_path']}")
        print(f"Index: {result['index_path']}")
        log_command_invoked(
            "maintenance.rebuild-wiki-bridge",
            project_name=resolved_project,
            extra={
                "claim_count": result["claim_count"],
                "invalid_claim_count": result["invalid_claim_count"],
                "topic_count": result["topic_count"],
                "entity_count": result["entity_count"],
                "cache_hit_ratio": result["cache_hit_ratio"],
            },
        )
        return 0
    finally:
        await backend.close()
