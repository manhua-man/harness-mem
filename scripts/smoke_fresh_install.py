"""Verify a wheel-only first run from a clean temporary home/workspace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()

    expected_version = args.expected_version.removeprefix("v")
    version = subprocess.check_output(
        [sys.executable, "-c", "import harness_mem; print(harness_mem.__version__)"],
        text=True,
    ).strip()
    if version != expected_version:
        raise RuntimeError(f"installed version mismatch: {version} != {expected_version}")

    with tempfile.TemporaryDirectory(prefix="harness-mem-first-install-") as temp:
        home = Path(temp) / "home"
        workspace = Path(temp) / "workspace"
        home.mkdir()
        workspace.mkdir()
        (workspace / ".git").mkdir()

        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "HARNESS_MEM_CLIENT": "cursor",
                "HARNESS_MEM_PROJECT_ROOT": str(workspace),
                "HARNESS_MEM_DISABLE_EMBEDDINGS": "1",
            }
        )
        hash_vector = subprocess.check_output(
            [
                sys.executable,
                "-c",
                (
                    "from harness_mem.transcript_chunking import transcript_bytes_revision; "
                    "print(transcript_bytes_revision(b'\\xef\\xbb\\xbfuser:\\r\\nassistant:\\x00\\xff\\n'))"
                ),
            ],
            cwd=workspace,
            env=env,
            text=True,
        ).strip()
        expected_hash_vector = (
            "sha256:ff3a9081f301fcb0a6c45ccedcb26455"
            "caefce97d8a46da1cfab7e52b51c72a2"
        )
        if hash_vector != expected_hash_vector:
            raise RuntimeError(
                f"cross-platform transcript hash mismatch: {hash_vector}"
            )
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
                "method": "tools/call",
                "params": {"name": "get_project_status", "arguments": {}},
            },
        ]
        process = subprocess.run(
            [sys.executable, "-m", "harness_mem.mcp.server"],
            cwd=workspace,
            env=env,
            input="".join(json.dumps(request) + "\n" for request in requests),
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if process.returncode != 0:
            raise RuntimeError(f"MCP first run failed: {process.stderr}")
        responses = [json.loads(line) for line in process.stdout.splitlines() if line.strip()]
        if len(responses) != 2 or any("error" in response for response in responses):
            raise RuntimeError(f"unexpected MCP responses: {responses}")
        status_text = responses[1]["result"]["content"][0]["text"]
        status = json.loads(status_text)
        health = status["integration_health"]
        if health["project"]["status"] != "ok" or health["hooks"]["status"] != "ok":
            raise RuntimeError(f"first-run integration is unhealthy: {health}")

        expected_hooks = (
            workspace / ".cursor" / "hooks" / "session-start.sh",
            workspace / ".cursor" / "hooks" / "after-agent.sh",
        )
        if not all(path.is_file() for path in expected_hooks):
            raise RuntimeError(f"MCP bootstrap did not install Cursor hooks: {expected_hooks}")

    print(f"fresh install ok: harness-mem {version} on {sys.platform}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
