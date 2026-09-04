from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.mcp.executor import execute_tool_call
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _content_length_frame(payload: dict) -> bytes:
    body = json.dumps(payload).encode("utf-8")
    return b"Content-Length: " + str(len(body)).encode("ascii") + b"\r\n\r\n" + body


def _read_content_length_messages(data: bytes) -> list[dict]:
    messages: list[dict] = []
    offset = 0
    while offset < len(data):
        header_end = data.find(b"\r\n\r\n", offset)
        assert header_end != -1, data[offset:]
        header_blob = data[offset:header_end].decode("ascii")
        content_length: int | None = None
        for line in header_blob.splitlines():
            name, _, value = line.partition(":")
            if name.lower() == "content-length":
                content_length = int(value.strip())
                break
        assert content_length is not None
        body_start = header_end + 4
        body_end = body_start + content_length
        body = data[body_start:body_end]
        assert len(body) == content_length
        messages.append(json.loads(body.decode("utf-8")))
        offset = body_end
    return messages


def _server_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HARNESS_MEM_DISABLE_EMBEDDINGS"] = "1"
    env["HOME"] = str(tmp_path)
    env["USERPROFILE"] = str(tmp_path)
    env["PYTHONPATH"] = str(Path.cwd())
    return env


def _run_server(payload: bytes, tmp_path: Path) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server"],
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_server_env(tmp_path),
        timeout=15,
        check=False,
    )


def _seed_current_knowledge(data_dir: Path, source: Path) -> KnowledgeEntry:
    async def _seed() -> KnowledgeEntry:
        backend = LocalMemoryBackend(data_dir)
        await backend.init()
        try:
            entry = KnowledgeEntry(
                id="mcp-env-data-dir-entry",
                project_name="demo",
                module_path=["MCP transport"],
                title="MCP reads the configured data directory",
                statement="The MCP process uses HARNESS_MEM_DATA_DIR for normal search.",
                verified_at=datetime.now(timezone.utc),
            )
            candidate = KnowledgeCandidate(
                id="mcp-env-data-dir-candidate",
                project_name="demo",
                candidate_type="memory",
                statement=entry.statement,
            )
            decision = AssimilationDecision(
                id="mcp-env-data-dir-decision",
                project_name="demo",
                candidate_id=candidate.id,
                disposition="add",
                canonical_truth_ids=[entry.id],
                reason="Process-level MCP data-directory contract fixture.",
            )
            source_ref = ProjectKnowledgeSourceRef(
                label=source.name,
                target=source.resolve().as_uri(),
                kind="repository",
                digest="a" * 64,
            )
            store = backend.structured_store.knowledge_store
            await store.save_candidate(candidate)
            await store.apply_truth_mutation(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=decision,
                added_entries=[entry],
                predecessor_entries=[],
                source_refs_by_entry={entry.id: [source_ref]},
            )
            await store.cleanup_candidate(candidate.id)
            return entry
        finally:
            await backend.close()

    return asyncio.run(_seed())


def test_stdio_content_length_initialize_and_tools_list(tmp_path: Path) -> None:
    payload = b"".join(
        [
            _content_length_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-11-25"},
                }
            ),
            _content_length_frame(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            ),
        ]
    )

    proc = _run_server(payload, tmp_path)

    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    responses = _read_content_length_messages(proc.stdout)
    assert [response["id"] for response in responses] == [1, 2]
    assert responses[0]["result"]["serverInfo"]["name"] == "harness-mem"
    assert responses[1]["result"]["tool_count"] == 27


def test_stdio_ndjson_initialize_stays_supported(tmp_path: Path) -> None:
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25"},
    }

    proc = _run_server(json.dumps(request).encode("utf-8") + b"\n", tmp_path)

    assert proc.returncode == 0, proc.stderr.decode("utf-8", errors="replace")
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    assert len(lines) == 1
    response = json.loads(lines[0].decode("utf-8"))
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "harness-mem"


def test_stdio_search_uses_harness_mem_data_dir(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "SOURCE.md"
    source.write_text("# MCP data directory contract\n", encoding="utf-8")
    data_dir = tmp_path / "configured-data"
    entry = _seed_current_knowledge(data_dir, source)
    env = _server_env(tmp_path)
    env["HARNESS_MEM_DATA_DIR"] = str(data_dir)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25"},
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "search_memory",
                "arguments": {
                    "query": entry.title,
                    "project_name": entry.project_name,
                },
            },
        },
    ]

    proc = subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server"],
        cwd=workspace,
        input="".join(json.dumps(request) + "\n" for request in requests).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    payload = json.loads(responses[1]["result"]["content"][0]["text"])
    assert payload["status"] == "answered"
    assert payload["memories"] == [
        {"title": entry.title, "statement": entry.statement}
    ]


def test_initialize_stays_read_only_and_keeps_ndjson_stdout_clean(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".git").mkdir()
    env = _server_env(tmp_path)
    env["HARNESS_MEM_CLIENT"] = "cursor"
    env["HARNESS_MEM_PROJECT_ROOT"] = str(workspace)
    requests = [
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "Cursor"},
            },
        },
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/list",
            "params": {},
        },
    ]
    proc = subprocess.run(
        [sys.executable, "-m", "harness_mem.mcp.server"],
        cwd=workspace,
        input="".join(json.dumps(request) + "\n" for request in requests).encode(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        timeout=15,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr.decode(errors="replace")
    responses = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert [response["id"] for response in responses] == [1, 2]
    assert not (workspace / ".cursor").exists()


def test_tool_result_text_preserves_unicode_without_ascii_expansion(
    tmp_path: Path,
) -> None:
    tools = {
        "wake": {
            "description": "test",
            "input_schema": {"type": "object", "properties": {}},
            "cluster": "read",
            "handler": lambda: {"output": "中文会话证据"},
        }
    }

    response = execute_tool_call(
        tools=tools,  # type: ignore[arg-type]
        params={"name": "wake", "arguments": {}},
        req_id=1,
        data_dir=lambda: tmp_path,
        cost_budgets=lambda _project_name: None,
        project_name_for_cost=lambda _args, _result: "demo",
        logger=logging.getLogger("test.mcp-unicode"),
    )

    payload = response["result"]["content"][0]["text"]
    assert "中文会话证据" in payload
    assert "\\u4e2d" not in payload
