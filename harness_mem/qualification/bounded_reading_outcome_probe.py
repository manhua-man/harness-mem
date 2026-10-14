"""Exercise complete reading through SQLite, MCP stdio and Hook rendering.

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
from harness_mem.mcp import server
from harness_mem.mcp.read_projection import project_memory_entries, reading_tokens
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _request(name: str, arguments: dict) -> dict:
    return {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": arguments}}


def _payload(response: dict) -> tuple[dict, str]:
    text = response["result"]["content"][0]["text"]
    return json.loads(text), text


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


def run_bounded_reading_outcome_probe() -> dict[str, Any]:
    with TemporaryDirectory(prefix="harness-mem-bounded-reading-") as temporary:
        root = Path(temporary)
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        server.set_backend_override(backend)
        try:
            entries = asyncio.run(_seed(backend, root))
            requests: list[dict] = []
            arguments: dict[str, Any] = {"query": "", "budget_tokens": 900}
            # Collect the returned calls, then replay them through a separate
            # stdio process that reopens the same durable SQLite database.
            for _ in range(len(entries) * 2 + 1):
                request = _request("search_memory", arguments)
                requests.append(request)
                response = server.handle_request(request)
                assert response is not None
                page, _text = _payload(response)
                if "continuation" not in page:
                    break
                arguments = page["continuation"]["arguments"]
            else:
                raise RuntimeError("reading continuation did not finish")
            browse_count = len(requests)
            requests.extend([
                _request("search_memory", {"query": "Aurora Quickstart", "budget_tokens": 900}),
                _request("wake", {"current_task": " \t ", "budget_tokens": 900}),
                _request("wake", {"current_task": "browsingtoken", "budget_tokens": 900}),
                _request("autopilot_search_tick", {
                    "event_name": "tool_result", "current_task": "browsingtoken",
                    "tool_result": "browsingtoken failed", "is_error": True,
                    "budget_tokens": 1400,
                }),
            ])
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
            server.set_backend_override(None)
            asyncio.run(backend.close())

        environment = os.environ.copy()
        environment.update({
            "HARNESS_MEM_DATA_DIR": str(root / "data"),
            "HARNESS_MEM_DISABLE_EMBEDDINGS": "1",
            "HOME": str(root), "USERPROFILE": str(root),
            "PYTHONPATH": str(Path(__file__).resolve().parents[2]),
        })
        process = subprocess.run(
            [sys.executable, "-m", "harness_mem.mcp.server"],
            input="".join(json.dumps(request, ensure_ascii=False) + "\n" for request in requests).encode("utf-8"),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            cwd=root, env=environment, timeout=45, check=False,
        )
        responses = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        payloads = [_payload(response) for response in responses]
        browse = payloads[:browse_count]
        actual = [row["statement"] for page, _text in browse for row in page["memories"] if "statement" in row]
        normal_sizes = [reading_tokens(text) for page, text in browse if page.get("detail") != "full"]
        quickstart, blank, wake, automatic = [payload for payload, _text in payloads[browse_count:]]
        injection = automatic.get("context_injection") or {}
        automatic_readable = any(row.get("statement") for row in injection.get("memories", []))
        if not automatic_readable and injection.get("continuation"):
            call = injection["continuation"]
            followed = subprocess.run(
                [sys.executable, "-m", "harness_mem.mcp.server"],
                input=(json.dumps(_request(call["tool"], call["arguments"])) + "\n").encode(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                cwd=root, env=environment, timeout=45, check=False,
            )
            response = json.loads(followed.stdout.splitlines()[0])
            expanded, _text = _payload(response)
            automatic_readable = followed.returncode == 0 and any(row.get("statement") for row in expanded.get("memories", []))
        fields = {
            "stdio_process_succeeded": process.returncode == 0 and len(payloads) == len(requests),
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
            "hook_task_output_within_requested_size": reading_tokens(hook_task) <= 900 and "final-condition-" in hook_task,
            "hook_blank_does_not_dump_statements": "browsingtoken" not in hook_blank and "current memories available" in hook_blank,
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
    # The imported MCP server protects descriptor 1 from incidental prints.
    # Use its saved original descriptor for this command's sole JSON result.
    payload = (json.dumps(report, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    os.write(getattr(server, "_REAL_STDOUT_FD", 1), payload)
    return 0 if report["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
