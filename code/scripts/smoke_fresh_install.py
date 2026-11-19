"""Verify a wheel-only first run from a clean temporary home/workspace."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-version", required=True)
    args = parser.parse_args()

    expected_version = args.expected_version.removeprefix("v")
    scripts = Path(sysconfig.get_path("scripts"))
    suffix = ".exe" if os.name == "nt" else ""
    cli = scripts / f"harness-mem{suffix}"
    mcp = scripts / f"harness-mem-mcp{suffix}"
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
                "CODEX_HOME": str(home / ".codex"),
                "HARNESS_MEM_DATA_DIR": str(home / ".harness-mem" / "data"),
                "PYTHONPATH": "",
                "HARNESS_MEM_CLIENT": "codex",
                "HARNESS_MEM_PROJECT_ROOT": str(workspace),
                "HARNESS_MEM_DISABLE_EMBEDDINGS": "1",
            }
        )
        version = subprocess.check_output(
            [
                sys.executable,
                "-c",
                "import harness_mem; print(harness_mem.__version__)",
            ],
            cwd=workspace,
            env=env,
            text=True,
        ).strip()
        if version != expected_version:
            raise RuntimeError(
                f"installed version mismatch: {version} != {expected_version}"
            )
        workspace_before = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
        }
        quickstart = subprocess.run(
            [
                str(cli),
                "quickstart",
                "--client",
                "codex",
            ],
            cwd=workspace,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if quickstart.returncode != 0:
            detail = quickstart.stderr or quickstart.stdout
            raise RuntimeError(f"Quickstart failed: {detail}")
        skill_root = home / ".codex" / "skills"
        installed_skills = sorted(
            path.parent.name for path in skill_root.glob("*/SKILL.md")
        )
        if installed_skills:
            raise RuntimeError(
                f"Quickstart installed unexpected Codex skills: {installed_skills}"
            )
        user_hooks = home / ".codex" / "hooks.json"
        hooks = json.loads(user_hooks.read_text(encoding="utf-8"))["hooks"]
        for event, adapter in (
            ("SessionStart", "codex-start"), ("UserPromptSubmit", "codex-start"), ("Stop", "codex-stop"),
        ):
            if not any(
                f"--adapter {adapter}" in item.get("command", "")
                for group in hooks.get(event, [])
                for item in group.get("hooks", [])
            ):
                raise RuntimeError(f"Quickstart did not register {event}")
        workspace_after = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
        }
        if workspace_after != workspace_before:
            raise RuntimeError(
                "global Quickstart modified the project: "
                f"before={sorted(workspace_before)}, after={sorted(workspace_after)}"
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
        initialize = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-11-25",
                "clientInfo": {"name": "Codex"},
            },
        }
        initialize_process = subprocess.run(
            [str(mcp)],
            cwd=workspace,
            env=env,
            input=json.dumps(initialize) + "\n",
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if initialize_process.returncode != 0:
            raise RuntimeError(
                f"MCP initialize failed: {initialize_process.stderr}"
            )
        initialize_response = json.loads(initialize_process.stdout.strip())
        if "error" in initialize_response:
            raise RuntimeError(
                f"unexpected MCP initialize response: {initialize_response}"
            )
        server_version = initialize_response["result"]["serverInfo"]["version"]
        if server_version != expected_version:
            raise RuntimeError(f"unexpected MCP server version: {server_version}")
        workspace_after_initialize = {
            path.relative_to(workspace).as_posix()
            for path in workspace.rglob("*")
        }
        if workspace_after_initialize != workspace_before:
            raise RuntimeError(
                "MCP initialize modified the project before first use: "
                f"before={sorted(workspace_before)}, "
                f"after={sorted(workspace_after_initialize)}"
            )

        requests = [
            initialize,
            {"jsonrpc": "2.0", "id": 3, "method": "tools/list"},
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "get_project_status",
                    "arguments": {
                        "project_root": str(workspace),
                        "host_client": "codex",
                    },
                },
            },
        ]
        process = subprocess.run(
            [str(mcp)],
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
        if len(responses) != 3 or any("error" in response for response in responses):
            raise RuntimeError(f"unexpected MCP responses: {responses}")
        names = {tool["name"] for tool in responses[1]["result"]["tools"]}
        if not {"get_project_status", "prepare_session_distill", "search_memory"} <= names:
            raise RuntimeError(f"missing MCP entry points: {sorted(names)}")
        status_text = responses[2]["result"]["content"][0]["text"]
        status = json.loads(status_text)
        expected_status = {
            "success": True,
            "project_name": workspace.name,
            "message": (
                "Memory storage is ready; Hook files are prepared. "
                "If not yet trusted, review user Hooks in Codex Settings, then start a new task."
            ),
        }
        if status != expected_status:
            raise RuntimeError(f"unexpected first-run status: {status}")

        if json.loads(user_hooks.read_text(encoding="utf-8"))["hooks"] != hooks:
            raise RuntimeError("First status check changed the configured user Hooks")

    print(
        json.dumps(
            {
                "verified": True,
                "version": version,
                "platform": sys.platform,
                "user_hooks_registered": True,
                "no_command_skill_installed": True,
                "mcp_tools_listed": sorted(names),
                "quickstart_project_untouched": True,
                "mcp_initialize_project_untouched": True,
                "single_host_flow": True,
                "first_status_project_ready": True,
                "first_status_is_short": True,
                "first_status_preserves_hooks": True,
                "codex_hook_trust_step_reported": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
