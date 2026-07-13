from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


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
    assert responses[1]["result"]["tool_count"] == 39


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


def test_first_initialize_hook_install_does_not_pollute_ndjson_stdout(
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
    assert (workspace / ".cursor" / "hooks" / "session-start.sh").is_file()
