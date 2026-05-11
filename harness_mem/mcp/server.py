#!/usr/bin/env python3
"""
harness-mem MCP Server — structured memory access for Claude Code
=================================================================
Install: claude mcp add harness-mem -- python -m harness_mem.mcp.server

Tools:
  search_memory          — search structured + verbatim memory
  timeline               — observation timeline
  get_observations      — list observations for a session
  get_task_handoffs     — recent task handoffs
  get_confirmed_rules   — confirmed rules for a project
  get_project_profile   — project profile
  create_rule_candidate — create a rule candidate
  confirm_rule          — promote candidate to confirmed rule
"""

import os
import sys

# --- MCP stdio protection -----------------------------------------------
# Redirect stdout → stderr before heavy imports so that any stray print()
# statements from dependencies never corrupt the JSON-RPC stream on stdout.
_REAL_STDOUT = sys.stdout
_REAL_STDOUT_FD = None
try:
    _REAL_STDOUT_FD = os.dup(1)
    os.dup2(2, 1)
except (OSError, AttributeError):
    pass
sys.stdout = sys.stderr

import json  # noqa: E402
import logging  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any, Callable, TypedDict  # noqa: E402

from harness_mem.read_api import (  # noqa: E402
    search_memory,
    search_relation_facts,
    serialize_memory_entry_search_result,
    serialize_observation,
    serialize_observation_search_result,
    serialize_relation_fact_search_result,
    serialize_timeline_observation,
    timeline_observations,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend  # noqa: E402
from harness_mem.storage.local_project_profile_store import (  # noqa: E402
    LocalProjectProfileStore,
)

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


# =============================================================================
# READ TOOLS
# =============================================================================


def tool_search_memory(
    project_name: str | None,
    query: str,
    scope: str = "project",
    mode: str = "auto",
    temporal_bias: bool = False,
) -> dict:
    """Search structured memory entries + verbatim observations."""
    backend = _get_backend()

    if scope == "project" and not project_name:
        return {
            "success": False,
            "error": "project_name is required when scope=project",
        }

    entries, obs_list = asyncio.run(
        search_memory(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            mode=mode,
            memory_entry_limit=20,
            observation_limit=20,
            temporal_bias=temporal_bias,
        )
    )
    relation_facts = asyncio.run(
        search_relation_facts(
            backend,
            project_name=project_name,
            query=query,
            scope=scope,
            limit=20,
        )
    )
    for entry in entries:
        asyncio.run(backend.structured_store.touch_memory_entry(entry.id))

    combined_results = entries or relation_facts or obs_list
    effective_mode = getattr(combined_results[0], "_search_mode", mode) if combined_results else mode
    fallback_reason = getattr(combined_results[0], "_search_fallback_reason", None) if combined_results else None

    return {
        "project_name": project_name,
        "query": query,
        "scope": scope,
        "requested_mode": mode,
        "temporal_bias": temporal_bias,
        "effective_mode": effective_mode,
        "fallback_reason": fallback_reason,
        "memory_entries": [serialize_memory_entry_search_result(entry, mode) for entry in entries],
        "relation_facts": [
            serialize_relation_fact_search_result(fact) for fact in relation_facts
        ],
        "observations": [
            serialize_observation_search_result(observation, mode, query) for observation in obs_list
        ],
        "memory_entry_count": len(entries),
        "relation_fact_count": len(relation_facts),
        "observation_count": len(obs_list),
    }


def tool_timeline(project_name: str, limit: int = 50) -> dict:
    """Return chronological observation timeline for a project."""
    backend = _get_backend()
    obs_list = asyncio.run(timeline_observations(backend, project_name=project_name, limit=limit))

    return {
        "project_name": project_name,
        "limit": limit,
        "observations": [serialize_timeline_observation(observation) for observation in obs_list],
        "count": len(obs_list),
    }


def tool_get_observations(project_name: str, session_id: str) -> dict:
    """List all observations for a given session."""
    backend = _get_backend()
    all_obs = asyncio.run(backend.verbatim_store.list(limit=10000))
    session_obs = [
        o
        for o in all_obs
        if o.session_id == session_id
        and o.metadata.get("project_name") == project_name
    ]

    return {
        "project_name": project_name,
        "session_id": session_id,
        "observations": [serialize_observation(observation) for observation in session_obs],
        "count": len(session_obs),
    }


def tool_get_task_handoffs(project_name: str, limit: int = 5) -> dict:
    """Return recent task handoffs for a project."""
    backend = _get_backend()
    handoffs = asyncio.run(
        backend.structured_store.get_latest_handoffs(project_name, limit=limit)
    )
    return {
        "project_name": project_name,
        "limit": limit,
        "handoffs": [
            {
                "id": h.id,
                "task_id": h.task_id,
                "summary": h.summary,
                "status": h.status,
                "next_steps": h.next_steps,
                "blockers": h.blockers,
                "last_activity": h.last_activity.isoformat() if h.last_activity else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "updated_at": h.updated_at.isoformat() if h.updated_at else None,
                "provenance": h.provenance,
            }
            for h in handoffs
        ],
        "count": len(handoffs),
    }


def tool_get_confirmed_rules(project_name: str) -> dict:
    """Return all confirmed rules for a project."""
    backend = _get_backend()
    rules = asyncio.run(backend.structured_store.list_confirmed_rules(project_name))
    return {
        "project_name": project_name,
        "rules": [
            {
                "id": r.id,
                "pattern": r.pattern,
                "trigger": r.trigger,
                "examples": r.examples,
                "confirmed_at": r.confirmed_at.isoformat() if r.confirmed_at else None,
                "tags": r.tags,
                "provenance": r.provenance,
            }
            for r in rules
        ],
        "count": len(rules),
    }


def tool_get_project_profile(project_name: str) -> dict:
    """Return the project profile for a project."""
    store = asyncio.run(LocalProjectProfileStore(DEFAULT_DATA_DIR).get(project_name))
    if store is None:
        return {"project_name": project_name, "found": False}

    profile = store
    return {
        "found": True,
        "project_name": profile.project_name,
        "description": profile.description,
        "stacks": profile.stacks,
        "key_files": profile.key_files,
    }


# =============================================================================
# WRITE TOOLS
# =============================================================================


def tool_create_rule_candidate(
    project_name: str,
    session_id: str,
    pattern: str,
    trigger: str,
    examples: list[str] | None = None,
) -> dict:
    """Create a rule candidate from a correction."""
    from uuid import uuid4
    from harness_mem.core.schemas import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id,
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.6,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
    }


def tool_confirm_rule(rule_id: str) -> dict:
    """Promote a rule candidate to a confirmed rule."""
    from uuid import uuid4
    from datetime import datetime, timezone
    from harness_mem.core.schemas import ConfirmedRule

    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status == "accepted":
        return {"success": False, "error": f"Candidate already confirmed: {rule_id}"}

    confirmed = ConfirmedRule(
        id=str(uuid4()),
        project_name=candidate.project_name,
        pattern=candidate.pattern,
        trigger=candidate.trigger,
        examples=candidate.examples,
        confirmed_at=datetime.now(timezone.utc),
        source_candidate_id=candidate.id,
    )
    asyncio.run(backend.structured_store.save_confirmed_rule(confirmed))
    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "accepted"))

    return {
        "success": True,
        "confirmed_rule_id": confirmed.id,
        "pattern": confirmed.pattern,
        "trigger": confirmed.trigger,
    }


def tool_reject_rule(rule_id: str, reason: str | None = None) -> dict:
    """Reject a rule candidate."""
    backend = _get_backend()
    candidate = asyncio.run(backend.structured_store.get_rule_candidate(rule_id))
    if not candidate:
        return {"success": False, "error": f"Candidate not found: {rule_id}"}
    if candidate.status in ("accepted", "rejected"):
        return {"success": False, "error": f"Candidate already processed: {rule_id}"}

    asyncio.run(backend.structured_store.update_rule_candidate_status(rule_id, "rejected"))
    return {
        "success": True,
        "rejected_rule_id": rule_id,
        "reason": reason or "No reason provided",
    }


def tool_suggest_rule(
    project_name: str,
    pattern: str,
    trigger: str,
    session_id: str | None = None,
    examples: list[str] | None = None,
) -> dict:
    """Suggest a rule candidate for later review (lighter than confirm_rule)."""
    from uuid import uuid4
    from harness_mem.core.schemas import RuleCandidate

    backend = _get_backend()
    candidate = RuleCandidate(
        id=str(uuid4()),
        project_name=project_name,
        session_id=session_id or "",
        pattern=pattern,
        trigger=trigger,
        examples=examples or [],
        confidence=0.5,
        status="pending",
    )
    saved_id = asyncio.run(backend.structured_store.save_rule_candidate(candidate))
    return {
        "success": True,
        "candidate_id": saved_id,
        "pattern": candidate.pattern,
        "trigger": candidate.trigger,
        "status": "suggested",
    }


# =============================================================================
# MCP TOOL REGISTRY
# =============================================================================

import asyncio  # noqa: E402 (moved here so the stdio redirect above is clean)

class ToolSpec(TypedDict):
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


TOOLS: dict[str, ToolSpec] = {
    "search_memory": {
        "description": "Search structured memory entries and verbatim observations for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "enum": ["project", "all"], "description": "Search scope: project or all (default: project)"},
                "mode": {"type": "string", "enum": ["auto", "fts", "hybrid"], "description": "Search mode (default: auto)"},
                "temporal_bias": {"type": "boolean", "description": "Tie-break hybrid results by recency (default: false)"},
            },
            "required": ["query"],
        },
        "handler": tool_search_memory,
    },
    "timeline": {
        "description": "Return chronological observation timeline for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "limit": {
                    "type": "integer",
                    "description": "Max observations to return (default 50)",
                    "default": 50,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_timeline,
    },
    "get_observations": {
        "description": "List all observations for a given session in a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID to filter by"},
            },
            "required": ["project_name", "session_id"],
        },
        "handler": tool_get_observations,
    },
    "get_task_handoffs": {
        "description": "Return recent task handoffs for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "limit": {
                    "type": "integer",
                    "description": "Max handoffs to return (default 5)",
                    "default": 5,
                },
            },
            "required": ["project_name"],
        },
        "handler": tool_get_task_handoffs,
    },
    "get_confirmed_rules": {
        "description": "Return all confirmed rules for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
            },
            "required": ["project_name"],
        },
        "handler": tool_get_confirmed_rules,
    },
    "get_project_profile": {
        "description": "Return the project profile for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
            },
            "required": ["project_name"],
        },
        "handler": tool_get_project_profile,
    },
    "create_rule_candidate": {
        "description": "Create a rule candidate from a correction pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID where the correction occurred"},
                "pattern": {"type": "string", "description": "Rule pattern"},
                "trigger": {"type": "string", "description": "Trigger scenario"},
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Example instances (optional)",
                },
            },
            "required": ["project_name", "session_id", "pattern", "trigger"],
        },
        "handler": tool_create_rule_candidate,
    },
    "confirm_rule": {
        "description": "Promote a rule candidate to a confirmed rule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string", "description": "Rule candidate ID to confirm"},
            },
            "required": ["rule_id"],
        },
        "handler": tool_confirm_rule,
    },
    "reject_rule": {
        "description": "Reject a rule candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "rule_id": {"type": "string", "description": "Rule candidate ID to reject"},
                "reason": {"type": "string", "description": "Reason for rejection (optional)"},
            },
            "required": ["rule_id"],
        },
        "handler": tool_reject_rule,
    },
    "suggest_rule": {
        "description": "Suggest a rule for later review (lighter than confirm_rule).",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "pattern": {"type": "string", "description": "Rule pattern"},
                "trigger": {"type": "string", "description": "Trigger scenario"},
                "session_id": {"type": "string", "description": "Session ID (optional)"},
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Example instances (optional)",
                },
            },
            "required": ["project_name", "pattern", "trigger"],
        },
        "handler": tool_suggest_rule,
    },
}


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
                "serverInfo": {"name": "harness-mem", "version": "1.4.0"},
            },
        }

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}

    if method.startswith("notifications/"):
        # Notifications carry no id — per JSON-RPC spec they get no response
        return None

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "tools": [
                    {
                        "name": n,
                        "description": t["description"],
                        "inputSchema": t["input_schema"],
                    }
                    for n, t in TOOLS.items()
                ]
            },
        }

    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}

        if tool_name not in TOOLS:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
            }

        # Whitelist arguments to declared schema properties
        import inspect

        schema_props = TOOLS[tool_name]["input_schema"].get("properties", {})
        try:
            handler = TOOLS[tool_name]["handler"]
            sig = inspect.signature(handler)
            accepts_var_keyword = any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except (ValueError, TypeError):
            accepts_var_keyword = False

        if not accepts_var_keyword:
            tool_args = {k: v for k, v in tool_args.items() if k in schema_props}

        # Coerce integer/float types per schema
        for key, value in list(tool_args.items()):
            prop_schema = schema_props.get(key, {})
            declared_type = prop_schema.get("type")
            try:
                if declared_type == "integer" and not isinstance(value, int):
                    tool_args[key] = int(value)
                elif declared_type == "number" and not isinstance(value, (int, float)):
                    tool_args[key] = float(value)
            except (ValueError, TypeError):
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": f"Invalid value for parameter '{key}'"},
                }

        try:
            result = TOOLS[tool_name]["handler"](**tool_args)
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"content": [{"type": "text", "text": json.dumps(result, indent=2)}]},
            }
        except Exception:
            logger.exception(f"Tool error in {tool_name}")
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32000, "message": "Internal tool error"},
            }

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
    global _REAL_STDOUT, _REAL_STDOUT_FD
    if _REAL_STDOUT_FD is not None:
        try:
            os.dup2(_REAL_STDOUT_FD, 1)
            os.close(_REAL_STDOUT_FD)
        except OSError:
            pass
        _REAL_STDOUT_FD = None
    sys.stdout = _REAL_STDOUT


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
