#!/usr/bin/env python3
"""
harness-mem MCP Server — structured memory access for AI agents
=================================================================
Install: claude mcp add harness-mem -- python -m harness_mem.mcp.server

Tools:
  search_memory          — search structured + verbatim memory
  timeline               — observation timeline
  get_observations      — list observations for a session
  get_task_handoffs     — recent task handoffs
  get_confirmed_rules   — confirmed rules for a project
  get_project_profile   — project profile
  get_project_status    — current project memory status and active project
  dream_ledger          — inspect dream maintenance ledger
  dream_run             — explicitly run one audited dream pass
  ingest_sessions       — project-scoped environment-aware session ingest
  prepare_session_distill — one-shot ingest + evidence packet for AI distill
  list_candidates       — pending/accepted/rejected review candidates
  auto_review_candidates — heuristic auto-confirm / auto-reject pass (preview or apply)
  suggest_correction    — one-shot rule replacement (new rule + supersede chain)
  create_rule_candidate — create a rule candidate
  confirm_rule          — promote candidate to confirmed rule

Current module boundary:
  server.py        — stdio protection, backend singleton, JSON-RPC dispatch
  tool_specs.py    — MCP schemas, public surface membership, cluster metadata
  tool_registry.py — single-surface visibility and tools/list payloads
  executor.py      — tools/call execution policy and write gate enforcement
  tool_handlers.py — tool implementations and handler registry
"""

import os
import sys

# --- MCP stdio protection -----------------------------------------------
# Redirect stdout → stderr before heavy imports so that any stray print()
# statements from dependencies never corrupt the JSON-RPC stream on stdout.
_REAL_STDOUT_FD = None
_REAL_STDOUT_ENCODING = sys.stdout.encoding or "utf-8"
_REAL_STDOUT_ERRORS = sys.stdout.errors or "replace"
try:
    _REAL_STDOUT_FD = os.dup(1)
    os.dup2(2, 1)
except (OSError, AttributeError):
    pass
sys.stdout = sys.stderr

import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

from harness_mem import __version__ as _HARNESS_MEM_VERSION  # noqa: E402
from harness_mem.config.errors import ConfigError  # noqa: E402
from harness_mem.config.merge import load_merged_config  # noqa: E402
from harness_mem.commands.support import (  # noqa: E402
    find_project_root,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.version import runtime_version_payload  # noqa: E402
from harness_mem.mcp.executor import execute_tool_call  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stderr)
logger = logging.getLogger("harness_mem_mcp")

DEFAULT_DATA_DIR = Path.home() / ".harness-mem" / "data"

# Singleton backend — initialized once per MCP server process lifetime.
_backend: LocalMemoryBackend | None = None


def _get_backend() -> LocalMemoryBackend:
    global _backend
    if _backend is None:
        _backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
        # Synchronous init via asyncio.run since MCP handlers are sync.
        asyncio.run(_backend.init())
    return _backend


def set_backend_override(backend: LocalMemoryBackend | None) -> None:
    """Override the singleton backend (used by tests to inject tmp_path backend)."""
    global _backend
    _backend = backend


def _observer_data_dir() -> Path:
    """Return the data dir cost observer should use without forcing backend init."""
    if _backend is not None:
        return _backend.data_dir
    return DEFAULT_DATA_DIR


def _cost_surface_budgets(project_name: str | None) -> dict[str, int] | None:
    """Load project cost budgets when a project root/config can be resolved."""
    if not project_name:
        return None
    root = find_project_root(project_name)
    if root is None:
        return None
    try:
        cfg = load_merged_config(str(root))
    except ConfigError:
        return None
    return {
        "wake": cfg.cost_budget_wake_tokens,
        "search": cfg.cost_budget_search_tokens,
        "file_context": cfg.cost_budget_file_context_tokens,
        "dream": cfg.cost_budget_dream_tokens,
        "distill": cfg.cost_budget_distill_tokens,
    }


def _project_name_for_cost(
    arguments: dict[str, Any],
    result: dict[str, Any] | Any,
) -> str | None:
    value = arguments.get("project_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    if isinstance(result, dict):
        result_value = result.get("project_name")
        if isinstance(result_value, str) and result_value.strip():
            return result_value.strip()
    return None

# =============================================================================
# MCP TOOL REGISTRY
# =============================================================================

import asyncio  # noqa: E402 (moved here so the stdio redirect above is clean)

from harness_mem.mcp.tool_handlers import (  # noqa: E402
    build_tool_handlers,
    configure_tool_handler_dependencies,
)
from harness_mem.mcp.tool_specs import (  # noqa: E402,F401
    ToolSpec,
    build_tools,
)
from harness_mem.mcp.tool_registry import (  # noqa: E402
    list_tools_result,
    resolve_mcp_tool_profile,
)

configure_tool_handler_dependencies(
    backend_provider=_get_backend,
    observer_data_dir=_observer_data_dir,
    cost_surface_budgets=_cost_surface_budgets,
    logger_instance=logger,
)

# Re-export handler functions from ``server`` for tests and older internal
# imports while keeping their implementation in ``tool_handlers``.
TOOL_HANDLERS = build_tool_handlers()
for _handler in TOOL_HANDLERS.values():
    globals()[_handler.__name__] = _handler
TOOLS: dict[str, ToolSpec] = build_tools(TOOL_HANDLERS)

# =============================================================================
# JSON-RPC REQUEST HANDLER
# =============================================================================

SUPPORTED_PROTOCOL_VERSIONS = [
    "2025-11-25",
    "2025-06-18",
    "2025-03-26",
    "2024-11-05",
]


def handle_request(request: dict) -> dict | None:
    method = request.get("method") or ""
    params = request.get("params") or {}
    req_id = request.get("id")

    if method == "initialize":
        client_version = params.get("protocolVersion", SUPPORTED_PROTOCOL_VERSIONS[-1])
        negotiated = (
            client_version
            if client_version in SUPPORTED_PROTOCOL_VERSIONS
            else SUPPORTED_PROTOCOL_VERSIONS[0]
        )
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": negotiated,
                "capabilities": {"tools": {}},
                "serverInfo": {
                    "name": "harness-mem",
                    "version": _HARNESS_MEM_VERSION,
                    **runtime_version_payload(),
                },
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method.startswith("notifications/"):
        # Notifications carry no id — per JSON-RPC spec they get no response
        return None

    if method == "tools/list":
        profile_info = resolve_mcp_tool_profile(params)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": list_tools_result(TOOLS, profile_info),
        }

    if method == "tools/call":
        return execute_tool_call(
            tools=TOOLS,
            params=params,
            req_id=req_id,
            data_dir=_observer_data_dir,
            cost_budgets=_cost_surface_budgets,
            project_name_for_cost=_project_name_for_cost,
            logger=logger,
        )

    # Notifications (missing id) must never get a response
    if req_id is None:
        return None

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"},
    }


# =============================================================================
# STDOUT RESTORATION + MAIN LOOP
# =============================================================================


def _restore_stdout():
    """Restore real stdout for MCP JSON-RPC output."""
    global _REAL_STDOUT_FD
    if _REAL_STDOUT_FD is not None:
        try:
            os.dup2(_REAL_STDOUT_FD, 1)
        except OSError:
            pass
        finally:
            try:
                os.close(_REAL_STDOUT_FD)
            except OSError:
                pass
        _REAL_STDOUT_FD = None
    try:
        sys.stdout = os.fdopen(
            os.dup(1),
            "w",
            buffering=1,
            encoding=_REAL_STDOUT_ENCODING,
            errors=_REAL_STDOUT_ERRORS,
        )
    except OSError:
        sys.stdout = sys.__stdout__


def main():
    _restore_stdout()
    logger.info("harness-mem MCP Server starting...")
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            request = json.loads(line)
            response = handle_request(request)
            if response is not None:
                sys.stdout.write(json.dumps(response) + "\n")
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            logger.error(f"Server error: {e}")


if __name__ == "__main__":
    main()
