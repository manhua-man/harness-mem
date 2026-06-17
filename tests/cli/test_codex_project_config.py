from __future__ import annotations

import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from harness_mem import __version__


pytestmark = pytest.mark.cli

REPO_ROOT = Path(__file__).resolve().parents[2]
CODEX_CONFIG = REPO_ROOT / ".codex" / "config.toml"


def test_codex_project_config_starts_harness_mem_mcp_from_repo_root():
    """The repo should self-describe a working Codex MCP server setup."""
    python_cmd = shutil.which("python")
    if python_cmd is None:
        pytest.skip("python is not available on PATH")

    config = tomllib.loads(CODEX_CONFIG.read_text(encoding="utf-8"))
    server = config["mcp_servers"]["harness_mem"]

    assert server["command"] == "python"
    assert server["args"] == ["-m", "harness_mem.mcp.server"]
    assert server["cwd"] == ".."
    assert server["startup_timeout_sec"] == 120

    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "0"},
        },
    }
    proc = subprocess.run(
        [python_cmd, *server["args"]],
        cwd=(CODEX_CONFIG.parent / server["cwd"]).resolve(),
        input=json.dumps(request) + "\n",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )

    assert proc.returncode == 0
    response = json.loads(proc.stdout.strip())
    assert response["id"] == 1
    assert response["result"]["serverInfo"]["name"] == "harness-mem"
    assert response["result"]["serverInfo"]["version"] == __version__
