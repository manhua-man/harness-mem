"""Import command implementation."""

from __future__ import annotations

from pathlib import Path

from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    log_cli_event,
    log_command_invoked,
    resolve_project_name,
)
from harness_mem.event_log import EventType
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.tools.import_bridge import ImportBridge


async def cmd_import(
    file_path: str,
    project_name: str | None = None,
) -> int:
    """Import memory drafts from a JSON file into the candidate layer."""
    project_name = resolve_project_name(project_name, action_label="import")
    if not project_name:
        return 1

    path = Path(file_path)
    if not path.exists():
        print(f"Error: File not found: {file_path}")
        return 1

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        bridge = ImportBridge(backend)
        counts = await bridge.import_file(path, project_name=project_name)
        
        total = counts["memory_entries"] + counts["relation_facts"]
        if total == 0:
            print(f"No valid entries found in {file_path}")
            return 0
            
        print(f"Successfully imported {total} candidates for project '{project_name}':")
        if counts["memory_entries"]:
            print(f"  - {counts['memory_entries']} Memory Entries (status: pending)")
        if counts["relation_facts"]:
            print(f"  - {counts['relation_facts']} Relation Facts (status: pending)")
            
        print("\nNext step: Review these candidates with MCP list_candidates")
        
        log_command_invoked("import", project_name=project_name, extra={"file": file_path, "count": total})
        log_cli_event(
            EventType.MEMORY_DISTILLED,
            project_name=project_name,
            command="import",
            extra={"count": total}
        )
        return 0
    finally:
        await backend.close()
