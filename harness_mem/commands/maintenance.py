"""Maintenance commands.

v1.6.0 introduces ``maintenance assign-memory-types``: a one-shot, idempotent
backfill that persists the ``memory_type`` field for ``MemoryEntry`` blobs
written before v1.6.0. Loading legacy blobs already derives the field
on the fly via :meth:`MemoryEntry.from_dict`, but persisting it explicitly
unblocks v1.6.1 (which will add a SQLite column for filtering) and makes
the field directly visible in the on-disk JSON.

Design notes:

- ``dry_run=True`` is the default. ``--apply`` is required to mutate blobs.
- "Needs update" is determined by the *raw JSON* — if a blob already has a
  ``memory_type`` key (even if the value matches what derivation would
  produce) it is considered already typed and skipped. This keeps the
  command idempotent and never overwrites an explicit user choice.
- The command requires a project context (active project or ``--project``);
  there is no global "all projects" sweep in v1.6.0 to keep blast radius
  small.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.core.schemas.memory_entry import MemoryType, _derive_memory_type
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
    """Backfill ``memory_type`` on legacy MemoryEntry blobs.

    Returns 0 on success (including no-op), 1 on missing project context.
    """
    resolved_project = resolve_project_name(
        project_name,
        required=True,
        action_label="maintenance assign-memory-types",
    )
    if not resolved_project:
        return 1

    # Initialize the backend so log_command_invoked can attach project context;
    # we read JSON blobs directly (no SQL writes needed for v1.6.0).
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
                # Skip unreadable blobs rather than crash the whole sweep.
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
