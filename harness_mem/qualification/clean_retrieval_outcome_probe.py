"""Direct proof that ordinary retrieval excludes raw session evidence."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import server
from harness_mem.mcp.read_search_handlers import tool_search_memory
from harness_mem.mcp.read_wake_handlers import tool_wake
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run_clean_retrieval_outcome_probe() -> dict[str, bool]:
    with TemporaryDirectory(prefix="harness-mem-clean-retrieval-") as temporary:
        backend = LocalMemoryBackend(Path(temporary) / "data")
        asyncio.run(backend.init())
        server.set_backend_override(backend)
        try:
            project_name = "clean-retrieval-probe"
            current = MemoryEntry(
                id="current-memory",
                project_name=project_name,
                category="decision",
                content="cleanretrievaltoken current canonical memory.",
                source="fixture",
                status="auto_confirmed",
            )
            provisional = MemoryEntry(
                id="provisional-memory",
                project_name=project_name,
                category="decision",
                content="cleanretrievaltoken provisional candidate must stay hidden.",
                source="fixture",
                status="provisional",
            )
            historical = MemoryEntry(
                id="historical-memory",
                project_name=project_name,
                category="decision",
                content="cleanretrievaltoken historical memory must stay hidden.",
                source="fixture",
                status="auto_confirmed",
                valid_to=datetime.now(timezone.utc) - timedelta(minutes=1),
            )
            for entry in (current, provisional, historical):
                asyncio.run(backend.structured_store.save_memory_entry(entry))
            observation_id = asyncio.run(
                backend.verbatim_store.save(
                    Observation(
                        id="raw-observation",
                        session_id="raw-session",
                        client="codex",
                        raw_content="cleanretrievaltoken raw session evidence.",
                        content_type="turn",
                        metadata={"project_name": project_name},
                    )
                )
            )

            default = tool_search_memory(
                query="cleanretrievaltoken",
                project_name=project_name,
            )
            deep = tool_search_memory(
                query="cleanretrievaltoken",
                project_name=project_name,
                deep_recall=True,
            )
            wake = tool_wake(
                project_name=project_name,
                current_task="cleanretrievaltoken",
                detail_level="compact",
            )
            deep_wake = tool_wake(
                project_name=project_name,
                current_task="cleanretrievaltoken",
                deep_recall=True,
                detail_level="full",
            )

            default_statements = {
                str(item.get("statement")) for item in default.get("memories") or []
            }
            deep_observation_ids = {
                str(item.get("id")) for item in deep.get("observations") or []
            }
            fields = {
                "default_current_truth_retrievable": current.content in default_statements,
                "default_excludes_provisional_and_historical": (
                    provisional.content not in default_statements
                    and historical.content not in default_statements
                ),
                "default_has_no_raw_observation": "raw session evidence"
                not in json.dumps(default),
                "default_has_no_audit_metadata": set(default) == {
                    "project_name",
                    "query",
                    "status",
                    "memories",
                },
                "deep_recall_returns_raw_observation": observation_id in deep_observation_ids,
                "wake_default_has_no_raw_observation": (
                    "raw session evidence" not in json.dumps(wake)
                    and "source_coverage" not in wake
                ),
                "wake_deep_recall_returns_raw_observation": (
                    int((deep_wake.get("source_coverage") or {}).get("observation", 0))
                    == 1
                    and deep_wake.get("effective_deep_recall") is True
                ),
            }
            fields["verified"] = all(fields.values())
            return fields
        finally:
            server.set_backend_override(None)
            asyncio.run(backend.close())


def main() -> int:
    result = run_clean_retrieval_outcome_probe()
    # Importing the MCP server redirects descriptor 1 to stderr to protect the
    # JSON-RPC transport. Its duplicate preserves the process's original
    # stdout for a qualification command's sole machine-readable result.
    payload = (json.dumps(result, sort_keys=True) + "\n").encode("utf-8")
    original_stdout = getattr(server, "_REAL_STDOUT_FD", None)
    if original_stdout is not None:
        os.write(original_stdout, payload)
    else:  # pragma: no cover - only if the platform lacks descriptor support.
        os.write(1, payload)
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
