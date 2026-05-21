"""Maintenance commands.

v1.6.0 introduced ``maintenance assign-memory-types``: a one-shot,
idempotent backfill that persists the ``memory_type`` field for legacy
``MemoryEntry`` blobs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.core.schemas.memory_entry import MemoryType, _derive_memory_type
from harness_mem.storage.local_structured_store import LocalStructuredStore
from harness_mem.storage.local_verbatim_store import LocalVerbatimStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


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
            if i % 10 == 0:
                print(f"  entries {i}/{len(entries)}")
            structured_index.persist_embedding(entry.id, entry.content, model_id)

        observations = await verbatim_store.list(limit=100000)
        project_observations = [
            observation
            for observation in observations
            if observation.metadata.get("project_name") == resolved_project
        ]
        for i, observation in enumerate(project_observations, 1):
            if i % 10 == 0:
                print(f"  observations {i}/{len(project_observations)}")
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
