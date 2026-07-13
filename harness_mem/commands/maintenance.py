"""Maintenance commands."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, cast

from harness_mem.config.merge import MergedConfig
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
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
from harness_mem.event_log import replay_state_events, state_audit_summary


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
        structured_index = structured_store.index
        verbatim_index = verbatim_store.index
        for index in (structured_index, verbatim_index):
            with index.locked_connection() as conn:
                conn.execute("DROP TABLE IF EXISTS vec_embeddings")
                conn.commit()
            index.drop_vec0_index()
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

        vec0_indexed = 0
        for index in (structured_index, verbatim_index):
            vec0_indexed += index.rebuild_vec0_index(model_id=model_id)

        print(
            f"Done: {len(entries)} entries, "
            f"{len(project_observations)} observations, "
            f"{vec0_indexed} vec0 row(s) indexed"
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


async def cmd_state_audit(project_name: str | None) -> int:
    """Print append-only state audit ledger summary."""

    summary = state_audit_summary(DEFAULT_DATA_DIR, project_name=project_name)
    replay = replay_state_events(DEFAULT_DATA_DIR, project_name=project_name)
    print("State audit ledger")
    print(f"Project: {summary['project_name'] or '*'}")
    print(f"Events: {summary['event_count']}")
    print(f"Replay targets: {replay['target_count']}")
    print(f"Ledger: {summary['ledger']}")
    print(json.dumps({**summary, "replay": replay}, indent=2, sort_keys=True))
    log_command_invoked(
        "maintenance.state-audit",
        project_name=project_name,
        extra={"event_count": summary["event_count"]},
    )
    return 0


async def run_post_turn_maintenance(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    project_root: str,
    config: MergedConfig,
    source: str = "ide_hook",
    trigger_id: str | None = None,
) -> dict[str, Any]:
    """Sync transcript evidence and queue Agent-led distillation work."""
    from harness_mem.mcp import tool_handlers as mcp_tool_handlers

    previous_backend_provider = getattr(mcp_tool_handlers, "_backend_provider", None)
    previous_observer_data_dir = getattr(mcp_tool_handlers, "_observer_data_dir_provider", None)
    previous_cost_surface_budgets = getattr(mcp_tool_handlers, "_cost_surface_budgets_provider", None)
    previous_logger = getattr(mcp_tool_handlers, "logger", logging.getLogger("harness_mem.host_entry"))
    try:
        mcp_tool_handlers.configure_tool_handler_dependencies(
            backend_provider=lambda: backend,
            observer_data_dir=lambda: backend.data_dir,
            cost_surface_budgets=lambda _project_name: None,
            logger_instance=logging.getLogger("harness_mem.host_entry"),
        )

        def _prepare_session_distill() -> dict[str, Any]:
            return mcp_tool_handlers.tool_prepare_session_distill(
                project_name=project_name,
                client="auto",
                limit=5,
                scope="project",
                project_root=project_root,
                observation_limit=5,
                max_chars_per_observation=6000,
                run_ingest=True,
                _distill_source=source,
            )

        try:
            evidence_packet = await asyncio.to_thread(_prepare_session_distill)
        except Exception as exc:  # noqa: BLE001 - maintenance should still continue.
            evidence_packet = {
                "success": False,
                "project_name": project_name,
                "project_root": project_root,
                "error": f"{type(exc).__name__}: {exc}"[:512],
            }

        job_id = evidence_packet.get("distill_job_id")
        job = backend.reflection_job_store.get(str(job_id)) if job_id else None
        return {
            "action": "post-turn-maintenance",
            "success": bool(evidence_packet.get("success", False)),
            "status": (
                "failed"
                if not evidence_packet.get("success", False)
                else "queued"
                if job is not None and job.status == "needs_distill"
                else "in_progress"
                if job is not None and job.status == "processing"
                else "completed"
            ),
            "project_name": project_name,
            "project_root": project_root,
            "source": source,
            "trigger_id": trigger_id,
            "evidence_packet": evidence_packet,
            "distill_job": job.to_dict() if job is not None else None,
            "summary": {
                "evidence_packet_ready": bool(evidence_packet.get("success", False)),
                "observation_count": evidence_packet.get("observation_count", 0),
                "distill_queued": job is not None and job.status == "needs_distill",
                "distill_job_id": job.id if job is not None else None,
            },
        }
    finally:
        if previous_backend_provider is None or previous_observer_data_dir is None or previous_cost_surface_budgets is None:
            mcp_tool_handlers.reset_tool_handler_dependencies()
        else:
            mcp_tool_handlers.configure_tool_handler_dependencies(
                backend_provider=previous_backend_provider,
                observer_data_dir=previous_observer_data_dir,
                cost_surface_budgets=previous_cost_surface_budgets,
                logger_instance=previous_logger,
            )
