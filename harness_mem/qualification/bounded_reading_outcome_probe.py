"""Exercise complete reading through SQLite, the local Search API and Hook rendering.

All knowledge is fictional and all data/configuration live in a temporary root.
This measures tool output, not model quality, billing or a natural host event.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.commands import token_estimator
from harness_mem.commands.wake import build_wake_injection
from harness_mem.core.schemas import (
    AssimilationDecision, KnowledgeCandidate, KnowledgeEntry, ProjectKnowledgeSourceRef,
)
from harness_mem.agent_runtime import active_backend
from harness_mem.mcp import tool_handlers
from harness_mem.search import search
from harness_mem.mcp.read_projection import project_memory_entries, reading_tokens
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


async def _seed(backend: LocalMemoryBackend, root: Path) -> list[KnowledgeEntry]:
    statements = [
        f"Aurora browsingtoken rule {index:03}. "
        + "Preserve the complete fact when reading and correcting current knowledge. " * 8
        + f"final-condition-{index:03}"
        for index in range(36)
    ]
    entries = [
        KnowledgeEntry(
            project_name="aurora", module_path=["Reading"],
            title=f"Reading rule {index:03}", statement=statement,
        )
        for index, statement in enumerate(statements)
    ]
    entries.extend([
        KnowledgeEntry(project_name="aurora", module_path=["Onboarding"],
                       title="Quickstart entry", statement="Install /hm once for the current host."),
        KnowledgeEntry(project_name="aurora", module_path=["General"],
                       title="Aurora MCP service", statement="Aurora MCP connects the local memory product."),
        KnowledgeEntry(project_name="aurora", module_path=["Reading"],
                       title="Z long reading rule", statement="browsingtoken " + "完整知识。" * 1600 + "最终条件保留。"),
    ])
    source = root / "fictional-sources.txt"
    source.write_text("\n".join(entry.statement for entry in entries), encoding="utf-8")
    reference = ProjectKnowledgeSourceRef(
        label=source.name, target=source.as_uri(), kind="repository",
        digest=hashlib.sha256(source.read_bytes()).hexdigest(),
    )
    candidate = KnowledgeCandidate(project_name="aurora", candidate_type="memory", statement="Fictional reading fixture.")
    decision = AssimilationDecision(
        project_name="aurora", candidate_id=candidate.id, disposition="add",
        canonical_truth_ids=[entry.id for entry in entries], reason="Isolated runtime probe.",
    )
    store = backend.structured_store.knowledge_store
    await store.save_candidate(candidate)
    await store.apply_current_change(
        candidate_before=candidate,
        candidate_after=candidate.model_copy(update={"status": "assimilated"}),
        decision=decision, added_entries=entries, predecessor_entries=[],
        source_refs_by_entry={entry.id: [reference] for entry in entries},
    )
    await store.cleanup_candidate(candidate.id)
    return entries


def _read_pages(data_dir: Path, maximum: int) -> list[dict]:
    arguments = {"query": "", "budget_tokens": 900}
    pages = []
    for _ in range(maximum):
        page = search(**arguments, data_dir=data_dir)
        pages.append(page)
        if "continuation" not in page:
            return pages
        arguments = page["continuation"]["arguments"]
    raise RuntimeError("reading continuation did not finish")


def run_bounded_reading_outcome_probe() -> dict[str, Any]:
    with TemporaryDirectory(prefix="harness-mem-bounded-reading-") as temporary:
        root = Path(temporary)
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        binding = active_backend.set(backend)
        try:
            entries = asyncio.run(_seed(backend, root))
            blank = tool_handlers.tool_wake(current_task=" ", budget_tokens=900)
            wake = tool_handlers.tool_wake(current_task="browsingtoken", budget_tokens=900)
            automatic = tool_handlers.tool_autopilot_search_tick(
                event_name="tool_result", current_task="browsingtoken", tool_result="browsingtoken failed",
                is_error=True, budget_tokens=1400,
            )
            hook_blank = asyncio.run(build_wake_injection(
                backend, "aurora", apply_surface_side_effects=False, budget_tokens=2000,
            ))
            hook_task = asyncio.run(build_wake_injection(
                backend, "aurora", current_task="browsingtoken", budget_tokens=900,
                apply_surface_side_effects=False,
            ))
            baseline = reading_tokens({
                "project_name": None, "query": "", "status": "answered",
                "memories": project_memory_entries(entries, include_project=True, include_modules=True),
            })
        finally:
            active_backend.reset(binding)
            asyncio.run(backend.close())

        environment = os.environ.copy()
        environment.update({
            "HARNESS_MEM_DATA_DIR": str(root / "data"),
            "HARNESS_MEM_DISABLE_EMBEDDINGS": "1",
            "USERPROFILE": str(root),
            # Keep dependency paths supplied by an isolated test environment.
            "PYTHONPATH": os.pathsep.join(filter(None, [
                str(Path(__file__).resolve().parents[2]), os.environ.get("PYTHONPATH", ""),
            ])),
        })
        process = subprocess.run(
            [sys.executable, "-c",
             "import json, sys; from pathlib import Path; "
             "from harness_mem.qualification.bounded_reading_outcome_probe import _read_pages; "
             "print(json.dumps(_read_pages(Path(sys.argv[1]), int(sys.argv[2]))))",
             str(root / "data"), str(len(entries) * 2 + 1)],
            cwd=root, env=environment, timeout=60, capture_output=True, check=True,
        )
        pages = json.loads(process.stdout)
        browse = [(page, json.dumps(page, ensure_ascii=False, separators=(",", ":"))) for page in pages]
        browse_count = len(browse)
        actual = [row["statement"] for page in pages for row in page["memories"] if "statement" in row]
        normal_sizes = [reading_tokens(page) for page in pages if page.get("detail") != "full"]
        quickstart = search("Aurora Quickstart", budget_tokens=900, data_dir=root / "data")
        injection = automatic.get("context_injection") or {}
        automatic_readable = any(row.get("statement") for row in injection.get("memories", []))
        candidate = next((row for row in injection.get("memories", []) if row.get("read_cursor")), None)
        if not automatic_readable and candidate:
            expanded = search(injection["query"], detail="full", read_cursor=candidate["read_cursor"], data_dir=root / "data")
            automatic_readable = (
                len(expanded.get("memories", [])) == 1
                and expanded["memories"][0]["title"] == candidate["title"]
                and bool(expanded["memories"][0].get("statement"))
            )
        if not automatic_readable and injection.get("continuation"):
            expanded = search(**injection["continuation"]["arguments"], data_dir=root / "data")
            automatic_readable = any(row.get("statement") for row in expanded.get("memories", []))
        fields = {
            "search_reopened_in_new_process": bool(pages),
            "all_facts_read_once_after_reopen": len(actual) == len(entries) and set(actual) == {entry.statement for entry in entries},
            "normal_pages_within_requested_size": all(size <= 900 for size in normal_sizes),
            "long_fact_complete": entries[-1].statement in actual,
            "quickstart_excludes_product_only_noise": quickstart["memories"] == [{
                "title": "Quickstart entry", "statement": "Install /hm once for the current host.", "project_name": "aurora",
            }],
            "blank_wake_is_availability_only": blank.get("available_count") == len(entries) and blank["long_term_memory"] == [],
            "task_wake_within_requested_size": reading_tokens(wake) <= 900 and bool(wake["long_term_memory"]),
            "automatic_complete_response_within_requested_size": reading_tokens(automatic) <= 1400 and automatic["success"] is True,
            "automatic_full_fact_accessible": automatic_readable,
            "hook_task_output_within_requested_size": (
                reading_tokens(hook_task) <= 900 and "read_cursor:" in hook_task
                and "final-condition-" not in hook_task
            ),
            "hook_blank_does_not_dump_statements": (
                "browsingtoken" not in hook_blank and "specific task when needed" in hook_blank
            ),
        }
        return {
            "verified": all(fields.values()), **fields,
            "metrics": {
                "fixture_facts": len(entries), "browse_calls": browse_count,
                "baseline_full_library_size": baseline,
                "first_page_size": reading_tokens(browse[0][1]),
                "max_normal_page_size": max(normal_sizes, default=0),
                "complete_browse_size": sum(reading_tokens(text) for _page, text in browse),
                "taskless_hook_size": reading_tokens(hook_blank),
                "automatic_response_size": reading_tokens(automatic),
                "counting": "cl100k_base_tokens" if token_estimator.tokenizer_kind == "tiktoken" else "utf8_byte_upper_bound",
            },
        }


def main() -> int:
    report = run_bounded_reading_outcome_probe()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
