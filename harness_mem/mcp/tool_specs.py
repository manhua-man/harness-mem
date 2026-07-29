"""MCP tool schema registry for harness-mem.

This module owns every tool's JSON Schema (``description`` + ``input_schema``).
It deliberately does **not** know about the handler functions — those live
in ``harness_mem.mcp.tool_handlers`` and are injected at module-import time
via :func:`build_tools`.

Why the split:

- The schema block was ~666 lines (1/3 of server.py). Pulling it out makes
  the runtime file readable without changing any tool behavior.
- Schemas are pure data. Keeping them away from the handler functions
  removes a heavy noise-to-signal section from the server module.
- The factory pattern (``build_tools(handlers)``) avoids circular imports:
  ``tool_specs`` does not import ``server``; ``server`` imports
  ``tool_specs`` once and passes its handler dict in.

The schemas here are the public MCP contracts. When a tool's input schema
changes, update this file and the caller-facing documentation together.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict

from harness_mem.governance_status import (
    GOVERNANCE_STATUS_LIST,
    LIST_CANDIDATES_STATUS_DESCRIPTION,
)


class ToolSpec(TypedDict):
    description: str
    input_schema: dict[str, Any]
    cluster: str
    handler: Callable[..., dict[str, Any]]


class _SchemaOnly(TypedDict):
    """A ToolSpec without the handler. Internal: the handler is injected
    by :func:`build_tools` so this module stays runtime-free."""

    description: str
    input_schema: dict[str, Any]


PUBLIC_MCP_TOOL_NAMES = frozenset(
    {
        "search_memory",
        "autopilot_search_tick",
        "wake",
        "timeline",
        "temporal_query",
        "file_context",
        "get_observations",
        "get_task_handoffs",
        "get_confirmed_rules",
        "get_project_status",
        "get_project_profile",
        "trace_relations",
        "search_raw",
        "search_skills",
        "get_skill",
        "prepare_session_distill",
        "submit_distill_chunk",
        "finalize_session_distill",
        "list_candidates",
        "get_candidate_detail",
        "auto_review_candidates",
        "govern_memory",
        "dream_ledger",
        "dream_run",
        "dream_auto_tick",
        "undo_dream_item",
        "record_context_outcome",
    }
)

# Ordered map of tool name → schema. Order is the discovery order MCP
# clients see; keep new tools at the bottom of their cluster (read /
# ingest / review / suggest) to keep the registry scannable.
_SCHEMAS: dict[str, _SchemaOnly] = {
    "search_memory": {
        "description": (
            "Search structured memory entries and verbatim observations for a "
            "project. Output keeps legacy memory_entries / relation_facts / "
            "observations arrays and adds an additive recall contract with "
            "evidence, sources, steps, planning, and status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "query": {"type": "string", "description": "Search query"},
                "scope": {"type": "string", "enum": ["project", "all"], "description": "Search scope: project or all (default: project)"},
                "mode": {"type": "string", "enum": ["auto", "fts", "hybrid"], "description": "Search mode (default: auto)"},
                "memory_type": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
                    "description": "Optional MemoryEntry.memory_type filter; multiple values are OR-ed.",
                },
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.0: include historical structured truth. Default false returns current truth only.",
                    "default": False,
                },
                "include_provisional": {
                    "type": "boolean",
                    "description": "v0.8.8: include provisional auto-promoted truth (down-weighted). Default false.",
                    "default": False,
                },
                "deep_recall": {
                    "type": "boolean",
                    "description": "v4.0.4: include cold/archive lifecycle tiers. Default false searches hot/warm only.",
                    "default": False,
                },
                "retrieval_profile": {
                    "type": "string",
                    "enum": ["light", "quality"],
                    "description": (
                        "v5.9.1: opt-in retrieval profile for this call. "
                        "'light' keeps the default path; 'quality' enables "
                        "deterministic query rewrite/fanout metadata with a "
                        "noop reranker. It does not enable HyDE or a heavy "
                        "reranker by default."
                    ),
                },
                "task": {
                    "type": "string",
                    "description": "v4.1: optional current task used by context sufficiency checks.",
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "v4.1: advisory context budget for ContextPlan / wake packet traces.",
                    "default": 6000,
                },
            },
            "required": ["query"],
        },
    },
    "autopilot_search_tick": {
        "description": (
            "Host-neutral runtime scheduler for automatic task-aware memory "
            "search. Given an agent event (PI context/tool_result/save_point, "
            "Claude Code PostToolUse, Cursor after-agent, etc.), it decides "
            "whether a concrete memory-backed uncertainty exists. When it "
            "does, it runs bounded search_memory and returns context_injection "
            "for the next provider request; otherwise it returns the skip "
            "reason. This is not a session-start wake replacement."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "event_name": {
                    "type": "string",
                    "description": "Normalized or native event name, e.g. context, tool_result, PostToolUse, prepareNextTurn.",
                },
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted).",
                },
                "current_task": {
                    "type": "string",
                    "description": "Current task or subtask the agent is working on.",
                },
                "user_prompt": {
                    "type": "string",
                    "description": "Latest user prompt, when available.",
                },
                "messages": {
                    "type": "array",
                    "items": {},
                    "description": "Optional recent message/event snippets from the host.",
                },
                "tool_name": {
                    "type": "string",
                    "description": "Tool name for tool_call/tool_result events.",
                },
                "tool_input": {
                    "type": "object",
                    "description": "Tool input for tool_call/tool_result events.",
                },
                "tool_result": {
                    "description": "Tool result or compact error payload for tool_result events.",
                },
                "is_error": {
                    "type": "boolean",
                    "description": "Whether the tool result is an error.",
                    "default": False,
                },
                "candidate_claims": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Durable memory/rule claims being considered at a save point.",
                },
                "changed_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Files touched or in scope for this event.",
                },
                "recent_queries": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Recent autopilot queries to suppress duplicates.",
                },
                "include_provisional": {
                    "type": "boolean",
                    "description": "Allow provisional auto-promoted truth in the search path.",
                    "default": False,
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "Advisory budget for the bounded search tick.",
                    "default": 1600,
                },
                "retrieval_profile": {
                    "type": "string",
                    "enum": ["light", "quality"],
                    "description": "Optional retrieval profile passed through to search_memory.",
                },
            },
            "required": ["event_name"],
        },
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
    },
    "trace_relations": {
        "description": (
            "Trace bounded current relation paths for a project entity. "
            "Output includes weighted path scores and an additive recall "
            "contract for evidence/source/step inspection. "
            "Returns empty unless relation facts have been populated for "
            "the project — heuristic distill rarely produces them from "
            "natural prose (loop_harness scenario 6 measured 0 facts from "
            "5 memory entries on real-style sessions). Populate via "
            "suggest_relation_fact or an LLM-driven distill pass."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "source_entity": {"type": "string", "description": "Relation source entity"},
                "relation_type": {
                    "type": "string",
                    "description": "Optional relation type filter, e.g. depends_on",
                },
                "max_depth": {
                    "type": "integer",
                    "description": "Maximum traversal depth (default 2, hard cap 3)",
                    "default": 2,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum paths to return (default 10)",
                    "default": 10,
                },
                "min_confidence": {
                    "type": "number",
                    "description": "Minimum edge confidence (default 0.0)",
                    "default": 0.0,
                },
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.2: include historical relation facts. Default false returns current relations only.",
                    "default": False,
                },
            },
            "required": ["project_name", "source_entity"],
        },
    },
    "temporal_query": {
        "description": (
            "Query the v3.3 temporal read model for current, historical, or "
            "as_of confirmed truth. Returns valid/recorded time, provenance, "
            "supersede chain, timeline, explanations, and abstention metadata. "
            "Read-only: rebuilds the projection from confirmed truth and never "
            "mutates memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "query": {
                    "type": "string",
                    "description": "Optional substring query over subject, predicate, and object",
                },
                "subject": {
                    "type": "string",
                    "description": "Optional subject filter. Relation facts use source_entity; rules use trigger; memory entries use category.",
                },
                "predicate": {
                    "type": "string",
                    "description": "Optional predicate filter. Relation facts use relation_type.",
                },
                "truth_type": {
                    "type": "string",
                    "enum": ["memory_entry", "relation_fact", "confirmed_rule"],
                    "description": "Optional projected truth type filter.",
                },
                "mode": {
                    "type": "string",
                    "enum": ["current", "history", "as_of"],
                    "description": "current=currently valid, history=expired truth, as_of=valid at the supplied timestamp.",
                    "default": "current",
                },
                "as_of": {
                    "type": "string",
                    "description": "ISO datetime for valid-time lookup. Used with mode=as_of; also honored when supplied directly.",
                },
                "valid_from": {
                    "type": "string",
                    "description": "ISO datetime lower bound for valid-time overlap filter.",
                },
                "valid_to": {
                    "type": "string",
                    "description": "ISO datetime upper bound for valid-time overlap filter.",
                },
                "recorded_from": {
                    "type": "string",
                    "description": "ISO datetime lower bound for recorded_at filter.",
                },
                "recorded_to": {
                    "type": "string",
                    "description": "ISO datetime upper bound for recorded_at filter.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum records to return (default 20, hard cap 100).",
                    "default": 20,
                },
                "require_unique_current": {
                    "type": "boolean",
                    "description": "When true, multiple current records in current mode produce temporal_conflict abstention.",
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
    },
    "search_raw": {
        "description": "Regex search raw observation evidence with exact snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
                    "default": "project",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum matches to return (default 20)",
                    "default": 20,
                },
            },
            "required": ["pattern"],
        },
    },
    "search_skills": {
        "description": "Search confirmed procedural skills.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name (required when scope=project)"},
                "query": {"type": "string", "description": "Task or workflow query"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
                    "default": "project",
                },
                "include_shared": {
                    "type": "boolean",
                    "description": "When true, include workspace/global shared skills alongside project skills",
                    "default": False,
                },
                "shared_scope": {
                    "type": "string",
                    "enum": ["exclude", "include", "only"],
                    "description": "Shared-skill search mode. exclude=default project-only, include=project plus shared, only=shared only",
                    "default": "exclude",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum skills to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    "get_skill": {
        "description": "Get a full confirmed skill payload by id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Confirmed skill ID"},
            },
            "required": ["skill_id"],
        },
    },
    "get_observations": {
        "description": (
            "Fetch project observations by session_id or observation_ids. "
            "Recent-context wake IDs can be passed directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID to filter by"},
                "observation_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Observation IDs from recent-context wake output; "
                        "full IDs, O-prefixed IDs, and unique prefixes are accepted"
                    ),
                },
            },
            "required": ["project_name"],
            "anyOf": [
                {"required": ["session_id"]},
                {"required": ["observation_ids"]},
            ],
        },
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
    },
    "get_confirmed_rules": {
        "description": "Return all confirmed rules for a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.0: include historical confirmed rules. Default false returns current rules only.",
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
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
    },
    "file_context": {
        "description": (
            "Return compact, source-attributed memory already associated with a "
            "file path before reading the file itself. v4.3 also returns current "
            "file fingerprints, Python code symbols/imports, code evidence source "
            "ids, and stale checks for memory references to code. Advisory only; "
            "never blocks file reads."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
                "path": {
                    "type": "string",
                    "description": "File path to look up in memory",
                },
                "project_root": {
                    "type": "string",
                    "description": "Optional project root used to resolve relative paths for v4.3 code evidence.",
                },
            },
            "required": ["path"],
        },
    },
    "get_project_status": {
        "description": (
            "Return active project, memory counts, concise integration health, and "
            "slash-native next-step triage hints without requiring CLI status. "
            "Always pass the current workspace root and the calling IDE/Agent host so "
            "a global MCP router can bootstrap the correct project hooks."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
                "project_root": {
                    "type": "string",
                    "description": (
                        "Absolute root of the workspace currently owned by the calling Agent. "
                        "Pass this on every first status call in a workspace."
                    ),
                },
                "host_client": {
                    "type": "string",
                    "enum": [
                        "cursor",
                        "claude-code",
                        "grok",
                        "codex",
                        "hermes",
                        "opencode",
                        "antigravity",
                    ],
                    "description": (
                        "IDE/Agent making the call; used to install that host's native hooks "
                        "when MCP is running behind a global router."
                    ),
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["compact", "full"],
                    "description": (
                        "Response detail. compact is the default decision view; "
                        "full returns complete health and integration diagnostics."
                    ),
                    "default": "compact",
                },
            },
            "required": ["project_root", "host_client"],
        },
    },
    "set_active_project": {
        "description": (
            "Set the active project so wake / search / suggest defaults pick it up. "
            "The active project is the only thing that prevents memory written "
            "from different working directories from cross-contaminating; agents should call this "
            "once at the start of a session in a new project."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project to mark as active",
                },
            },
            "required": ["project_name"],
        },
    },
    "wake": {
        "description": (
            "Generate a recent-context index plus stable truth and active "
            "handoffs for the given project, or the active project when "
            "project_name is omitted. Returns the wake-up text in `output` so "
            "the agent can ingest it directly."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
                "no_auto_ingest": {
                    "type": "boolean",
                    "description": "Skip the auto-ingest pass before generating wake-up text.",
                    "default": False,
                },
                "include_skill_hints": {
                    "type": "boolean",
                    "description": "Opt-in compact skill hints appended to wake output.",
                },
                "skill_hint_limit": {
                    "type": "integer",
                    "description": "Maximum compact skill hints to append when include_skill_hints is enabled.",
                },
                "current_task": {
                    "type": "string",
                    "description": "v4.1: optional current task used to build a task-aware wake packet.",
                },
                "budget_tokens": {
                    "type": "integer",
                    "description": "v4.1: advisory wake packet budget.",
                    "default": 6000,
                },
                "deep_recall": {
                    "type": "boolean",
                    "description": "v4.1: include cold/archive memory in task-aware wake planning.",
                    "default": False,
                },
                "include_provisional": {
                    "type": "boolean",
                    "description": "v0.8.8: include provisional auto-promoted truth in task-aware wake planning.",
                    "default": False,
                },
            },
        },
    },
    "ingest_sessions": {
        "description": (
            "Low-level transcript sync used by /hm:distill and diagnostics; "
            "prefer prepare_session_distill for memory creation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "client": {
                    "type": "string",
                    "enum": [
                        "auto",
                        "agent",
                        "claude-code",
                        "codex",
                        "codex-archive",
                        "cursor",
                        "grok",
                        "antigravity",
                        "opencode",
                        "hermes",
                    ],
                    "description": "Transcript source to sync (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to sync (default: 10)",
                    "default": 10,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore sync cursor and rescan matching sessions",
                    "default": False,
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Session scope for global stores (default: project)",
                    "default": "project",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for directory-first project resolution (default: current directory)",
                },
            },
        },
    },
    "prepare_session_distill": {
        "description": (
            "Low-level /hm:distill stage: sync recent transcripts, claim queued "
            "distill work, then return evidence for AI-led candidate drafting. "
            "This tool does not synthesize or summarize by itself."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "client": {
                    "type": "string",
                    "enum": [
                        "auto",
                        "agent",
                        "claude-code",
                        "codex",
                        "codex-archive",
                        "cursor",
                        "grok",
                        "antigravity",
                        "opencode",
                        "hermes",
                    ],
                    "description": "Transcript source to sync before distill (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to sync before distill (default: 5)",
                    "default": 5,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore sync cursor and rescan matching sessions",
                    "default": False,
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Session scope for global stores (default: project)",
                    "default": "project",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root for directory-first project resolution",
                },
                "observation_limit": {
                    "type": "integer",
                    "description": "Recent observations to include in the evidence packet (default: 5)",
                    "default": 5,
                },
                "max_chars_per_observation": {
                    "type": "integer",
                    "description": "Deprecated compatibility field; packets are no longer truncated",
                    "default": 6000,
                },
                "run_ingest": {
                    "type": "boolean",
                    "description": "Run low-level transcript sync before building the packet (default: true)",
                    "default": True,
                },
                "distill_job_id": {
                    "type": "string",
                    "description": (
                        "Optional active job id to claim exactly. Used by bounded "
                        "automatic maintenance so offered jobs are processed deterministically."
                    ),
                },
                "defer_job_id": {
                    "type": "string",
                    "description": "Failed job to release as retryable and skip for this call.",
                },
                "defer_reason": {
                    "type": "string",
                    "description": "Bounded failure reason stored with defer_job_id.",
                },
                "chunk_limit": {
                    "type": "integer",
                    "description": "Lossless transcript chunks to claim in this Agent call (default: 1, max: 3)",
                    "default": 1,
                },
                "evidence_mode": {
                    "type": "string",
                    "enum": ["raw", "semantic"],
                    "description": (
                        "Evidence delivery mode. raw preserves the existing per-chunk "
                        "Agent loop; semantic lets runtime hash-verify/checkpoint every raw "
                        "chunk and returns the smaller parser-derived session rendering."
                    ),
                    "default": "raw",
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["compact", "full"],
                    "description": (
                        "Semantic evidence detail. compact returns a budgeted exchange "
                        "outline; full returns the complete v1 semantic rendering."
                    ),
                    "default": "compact",
                },
                "budget_tokens": {
                    "type": "integer",
                    "minimum": 256,
                    "maximum": 12000,
                    "description": "Advisory token budget for compact semantic evidence.",
                    "default": 3000,
                },
                "drilldown_exchange_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "maxItems": 8,
                    "description": (
                        "Read complete semantic windows for selected one-based exchange "
                        "indexes before querying candidate-grade raw proof."
                    ),
                },
                "drilldown_chunk_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "maxItems": 8,
                    "description": (
                        "Read-only raw chunk indexes to return after a job reaches reviewing; "
                        "use for candidate-grade evidence drilldown."
                    ),
                },
                "drilldown_query": {
                    "type": "string",
                    "maxLength": 200,
                    "description": (
                        "Read-only search over raw chunks after the job reaches reviewing. "
                        "Returns up to 8 matching chunks when semantic evidence needs proof."
                    ),
                },
            },
        },
    },
    "submit_distill_chunk": {
        "description": (
            "Checkpoint the Agent's structured reading of one complete lossless "
            "transcript chunk. The lease token comes from prepare_session_distill."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string", "description": "Distill job id"},
                "chunk_id": {"type": "string", "description": "Claimed transcript chunk id"},
                "lease_owner": {"type": "string", "description": "Lease token returned with the chunk"},
                "result": {
                    "type": "object",
                    "description": "Structured chunk findings, including outcomes, claims, failures, and unresolved work",
                },
            },
            "required": ["job_id", "chunk_id", "lease_owner", "result"],
        },
    },
    "finalize_session_distill": {
        "description": (
            "Finalize one fully processed session after end-of-session semantic "
            "review. Auto-review and Dream run only for an internally consistent "
            "promotion decision, and only over candidates produced by this job."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "job_id": {"type": "string", "description": "Review-ready distill job id"},
                "semantic_review": {
                    "type": "object",
                    "description": "Final outcome, contradictions, unfinished work, and evidence assessment",
                    "properties": {
                        "final_user_request": {"type": "string"},
                        "final_outcome": {"type": "string"},
                        "last_turn_status": {
                            "type": "string",
                            "enum": ["answered", "unfinished", "unknown"],
                        },
                        "contradictions": {"type": "array", "items": {"type": "string"}},
                        "unfinished_work": {"type": "array", "items": {"type": "string"}},
                        "evidence_status": {
                            "type": "string",
                            "enum": ["answered", "partial", "contradicted", "not_applicable"],
                        },
                        "promotion_decision": {
                            "type": "string",
                            "enum": ["promote", "partial", "no_promotion", "blocked"],
                        },
                    },
                    "required": [
                        "final_user_request",
                        "final_outcome",
                        "last_turn_status",
                        "contradictions",
                        "unfinished_work",
                        "evidence_status",
                        "promotion_decision",
                    ],
                },
            },
            "required": ["project_name", "job_id", "semantic_review"],
        },
    },
    "list_candidates": {
        "description": (
            "List structured memory candidates for human review or audit inbox. "
            "Status values are layered governance states — use pending / "
            "provisional / auto_confirmed for audit; not all seven are "
            "interchangeable review filters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "status": {
                    "type": "string",
                    "enum": list(GOVERNANCE_STATUS_LIST),
                    "description": LIST_CANDIDATES_STATUS_DESCRIPTION,
                    "default": "pending",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum candidates to return across all candidate types (default: 100)",
                    "default": 100,
                },
            },
            "required": ["project_name"],
        },
    },
    "get_candidate_detail": {
        "description": "Read one candidate or reviewable structured item by id without mutating review state.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Candidate or reviewable item id"},
                "candidate_kind": {
                    "type": "string",
                    "enum": [
                        "memory_entry",
                        "relation_fact",
                        "rule_candidate",
                        "supersede",
                        "merge_suggestion_candidate",
                        "stale_truth_suggestion_candidate",
                    ],
                    "description": "Optional kind hint; omit to search all reviewable candidate stores.",
                },
            },
            "required": ["candidate_id"],
        },
    },
    "govern_memory": {
        "description": (
            "Composite write surface for candidate creation, review decisions, "
            "task handoffs, corrections, and supersede governance. Use action="
            "suggest with arguments.kind=memory|rule|relation; action=decide "
            "with kind, decision=confirm|reject, and candidate_id; action=handoff; "
            "action=correct_rule; or action=supersede. This replaces the former "
            "family of low-level suggest_*/confirm_*/reject_* MCP tools. "
            "Distill-bound suggestions should include evidence_basis, "
            "verification_outcome, and content-free verification_refs so Dream "
            "can verify repository or explicit user-statement evidence."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["suggest", "decide", "handoff", "correct_rule", "supersede"],
                },
                "arguments": {
                    "type": "object",
                    "description": "Action-specific arguments; project_name is required for project writes.",
                    "additionalProperties": True,
                },
            },
            "required": ["action", "arguments"],
        },
    },
    "auto_review_candidates": {
        "description": (
            "Run evidence-grounded auto-review across pending memory entries, "
            "rule candidates, and relation facts. Repository and explicit "
            "user-statement evidence are revalidated against the current source; "
            "transcript-only, unverified, or contradicted durable truths are blocked. "
            "Returns the standard summary shape "
            "(auto_confirmed / auto_rejected / "
            "kept_pending / needs_user_confirmation). With apply=true, low-risk "
            "decisions are applied with audit events while ambiguous or high-risk "
            "items stay reviewable. This is a project-level maintenance tool; "
            "lossless sessions must finish through finalize_session_distill."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "apply": {
                    "type": "boolean",
                    "description": (
                        "When true, apply auto_confirm / auto_reject decisions. "
                        "When false (default), preview without writes."
                    ),
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
    },
    "suggest_supersede": {
        "description": "Suggest a supersede candidate to mark old truth historical.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "target_type": {
                    "type": "string",
                    "enum": ["memory_entry", "relation_fact", "confirmed_rule"],
                    "description": "Truth type to supersede",
                },
                "target_id": {"type": "string", "description": "Existing truth id to mark historical"},
                "replacement_type": {
                    "type": "string",
                    "enum": ["memory_entry", "relation_fact", "confirmed_rule"],
                    "description": "Replacement truth type",
                },
                "replacement_id": {"type": "string", "description": "Replacement truth id"},
                "reason": {"type": "string", "description": "Why the replacement is needed"},
                "evidence": {"type": "string", "description": "Evidence for the replacement"},
                "source": {"type": "string", "description": "Source id (optional)"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            },
            "required": ["project_name", "target_type", "target_id", "replacement_type", "replacement_id", "reason", "evidence"],
        },
    },
    "confirm_supersede": {
        "description": "Confirm a supersede candidate and link truth records.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Supersede candidate ID to confirm"},
            },
            "required": ["candidate_id"],
        },
    },
    "reject_supersede": {
        "description": "Reject a supersede candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Supersede candidate ID to reject"},
            },
            "required": ["candidate_id"],
        },
    },
    "suggest_correction": {
        "description": (
            "Replace an existing confirmed rule in one shot. Creates a new "
            "ConfirmedRule, marks the old rule historical (valid_to set, "
            "supersedes/superseded_by linked), and returns the supersede "
            "chain ids so the caller can show the user what changed. Use "
            "this when reality changed (framework upgrade, policy reversal) "
            "and a previously confirmed rule is now actively wrong. Do NOT "
            "use this for adding a brand-new rule — use create_rule_candidate "
            "+ confirm_rule for that."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "supersedes_rule_id": {
                    "type": "string",
                    "description": "ConfirmedRule id this correction replaces",
                },
                "pattern": {
                    "type": "string",
                    "description": "Replacement rule pattern text",
                },
                "trigger": {
                    "type": "string",
                    "description": "Replacement rule trigger text",
                },
                "reason": {
                    "type": "string",
                    "description": "Why the old rule is being replaced (recorded on the supersede chain)",
                },
                "examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional examples for the new rule",
                },
                "source_session_id": {
                    "type": "string",
                    "description": "Session id this correction was triggered from",
                },
            },
            "required": [
                "project_name",
                "supersedes_rule_id",
                "pattern",
                "trigger",
                "reason",
            ],
        },
    },
    "record_context_outcome": {
        "description": (
            "Record whether returned wake/search context was used, ignored, "
            "or misleading for the caller's task. This writes only a "
            "RetrievalSignal(context_outcome) shadow record and never mutates "
            "confirmed truth. Opt-in ranking may later use the signal as a "
            "small explainable hint."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "surface": {
                    "type": "string",
                    "description": "Surface that returned the context, e.g. wake, search_memory, file_context.",
                },
                "source_ids": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Returned source ids being rated.",
                },
                "outcome": {
                    "type": "string",
                    "enum": ["used", "ignored", "misleading"],
                    "description": "Whether the surfaced context helped the task.",
                },
                "reason": {
                    "type": "string",
                    "description": "Optional short note. Avoid raw task content.",
                },
            },
            "required": ["project_name", "surface", "source_ids", "outcome"],
        },
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
                "distill_job_id": {
                    "type": "string",
                    "description": "Review-ready distill job id for exactly-once candidate creation",
                },
            },
            "required": ["project_name", "pattern", "trigger"],
        },
    },
    "suggest_memory_entry": {
        "description": "Suggest a memory entry (fact, decision, etc.) for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "category": {"type": "string", "enum": ["architecture", "convention", "api", "bug", "decision"]},
                "content": {"type": "string", "description": "Knowledge content"},
                "source": {"type": "string", "description": "Source observation id or session id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "distill_job_id": {
                    "type": "string",
                    "description": "Review-ready distill job id for exactly-once candidate creation",
                },
            },
            "required": ["project_name", "category", "content", "source"],
        },
    },
    "confirm_memory_entry": {
        "description": "Confirm a pending memory entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "Memory entry ID to confirm"},
            },
            "required": ["entry_id"],
        },
    },
    "reject_memory_entry": {
        "description": "Reject a pending memory entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "entry_id": {"type": "string", "description": "Memory entry ID to reject"},
            },
            "required": ["entry_id"],
        },
    },
    "suggest_relation_fact": {
        "description": "Suggest a typed relation between entities for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "source_entity": {"type": "string", "description": "Origin entity"},
                "target_entity": {"type": "string", "description": "Target entity"},
                "relation_type": {"type": "string", "description": "Relation type (e.g. depends_on)"},
                "evidence": {"type": "string", "description": "Evidence for this relation"},
                "source": {"type": "string", "description": "Source id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
                "distill_job_id": {
                    "type": "string",
                    "description": "Review-ready distill job id for exactly-once candidate creation",
                },
            },
            "required": ["project_name", "source_entity", "target_entity", "relation_type", "evidence", "source"],
        },
    },
    "confirm_relation_fact": {
        "description": "Confirm a pending relation fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "Relation fact ID to confirm"},
            },
            "required": ["fact_id"],
        },
    },
    "reject_relation_fact": {
        "description": "Reject a pending relation fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "fact_id": {"type": "string", "description": "Relation fact ID to reject"},
            },
            "required": ["fact_id"],
        },
    },
    "create_task_handoff": {
        "description": "Create a task handoff to record progress.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "task_id": {"type": "string", "description": "Task identifier"},
                "summary": {"type": "string", "description": "Progress summary"},
                "status": {"type": "string", "description": "Current status"},
                "next_steps": {"type": "array", "items": {"type": "string"}},
                "blockers": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["project_name", "task_id", "summary", "status"],
        },
    },
    "dream_ledger": {
        "description": (
            "Return the latest v3.1 DreamRun ledger for a project, or one "
            "DreamRun by id. This is the backing MCP surface for /hm:dream: "
            "it reads the audit ledger and never mutates truth."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "run_id": {
                    "type": "string",
                    "description": "Optional DreamRun id for drilldown.",
                },
            },
        },
    },
    "dream_run": {
        "description": (
            "Run one v3.1 dream maintenance pass now. It parses and handles "
            "every selected dream result to a terminal state and writes a "
            "DreamRun ledger with audit and undo metadata."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project directory used to load .harness-mem.toml (defaults to cwd).",
                },
                "budget": {
                    "type": "object",
                    "description": "Optional replay-window caps. Missing fields fall back to ReplayBudget defaults.",
                    "properties": {
                        "max_observations": {"type": "integer", "minimum": 0},
                        "max_pending_candidates": {"type": "integer", "minimum": 0},
                        "max_historical_truths": {"type": "integer", "minimum": 0},
                        "max_low_success_skills": {"type": "integer", "minimum": 0},
                        "max_repeat_search_hits": {"type": "integer", "minimum": 0},
                        "max_total_tokens": {"type": "integer", "minimum": 0},
                        "signal_lookback_days": {"type": "integer", "minimum": 1},
                    },
                    "additionalProperties": False,
                },
            },
        },
    },
    "dream_auto_tick": {
        "description": (
            "Run one host/client auto tick for v3.1 dream. The tick only "
            "enqueues a dream job when dream.auto.enabled and dream auto gates "
            "allow it."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project directory used to load .harness-mem.toml (defaults to cwd).",
                },
            },
        },
    },
    "undo_dream_item": {
        "description": (
            "Undo one applied DreamItem by replaying the undo metadata stored "
            "in its DreamRun ledger. Truth is restored or soft-deleted; "
            "confirmed records are not hard-deleted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "run_id": {
                    "type": "string",
                    "description": "DreamRun id containing the item to undo.",
                },
                "item_id": {
                    "type": "string",
                    "description": "DreamItem id to undo.",
                },
            },
            "required": ["run_id", "item_id"],
        },
    },
}

# Kept in the registry for internal orchestration, but never exposed through
# MCP tools/list or exported descriptors.
INTERNAL_MCP_TOOL_NAMES = frozenset(
    {
        "set_active_project",
        "ingest_sessions",
        # Compatibility handlers retained for internal orchestration and old
        # local code. They are intentionally absent from MCP tools/list.
        "suggest_memory_entry",
        "suggest_rule",
        "suggest_relation_fact",
        "create_task_handoff",
        "suggest_supersede",
        "confirm_supersede",
        "reject_supersede",
        "suggest_correction",
        "create_rule_candidate",
        "confirm_rule",
        "reject_rule",
        "confirm_memory_entry",
        "reject_memory_entry",
        "confirm_relation_fact",
        "reject_relation_fact",
    }
)


TOOL_CLUSTERS = {
    # Daily read/context surfaces.
    "search_memory": "core_read",
    "autopilot_search_tick": "core_read",
    "timeline": "core_read",
    "temporal_query": "core_read",
    "get_observations": "core_read",
    "get_task_handoffs": "core_read",
    "get_confirmed_rules": "core_read",
    "get_project_profile": "core_read",
    "file_context": "core_read",
    "get_project_status": "core_read",
    "set_active_project": "internal",
    "wake": "core_read",
    # Advanced or lower-frequency read surfaces.
    "trace_relations": "review_read",
    "search_raw": "review_read",
    "search_skills": "review_read",
    "get_skill": "review_read",
    "ingest_sessions": "internal",
    "record_context_outcome": "advanced",
    # Candidate/truth loop.
    "prepare_session_distill": "truth_loop",
    "submit_distill_chunk": "truth_loop",
    "finalize_session_distill": "truth_loop",
    "list_candidates": "truth_loop",
    "get_candidate_detail": "truth_loop",
    "auto_review_candidates": "truth_loop",
    "govern_memory": "truth_loop",
    "suggest_supersede": "truth_loop",
    "confirm_supersede": "truth_loop",
    "reject_supersede": "truth_loop",
    "suggest_correction": "truth_loop",
    "create_rule_candidate": "truth_loop",
    "confirm_rule": "truth_loop",
    "reject_rule": "truth_loop",
    "suggest_rule": "truth_loop",
    "suggest_memory_entry": "truth_loop",
    "confirm_memory_entry": "truth_loop",
    "reject_memory_entry": "truth_loop",
    "suggest_relation_fact": "truth_loop",
    "confirm_relation_fact": "truth_loop",
    "reject_relation_fact": "truth_loop",
    "create_task_handoff": "truth_loop",
    # Dream is a default product capability; the cluster name is separate from
    # whether a tool appears in the public MCP surface.
    "dream_ledger": "dream",
    "dream_run": "dream",
    "dream_auto_tick": "dream",
    "undo_dream_item": "dream",
}


def build_tools(
    handlers: dict[str, Callable[..., dict[str, Any]]],
) -> dict[str, ToolSpec]:
    """Combine the schema registry with caller-provided handler functions.

    Raises ``KeyError`` if ``handlers`` is missing a key the schema knows
    about, or if it contains a key the schema doesn't (caller probably
    typoed). This keeps registration mistakes loud at import time instead
    of surfacing as a missing-tool 404 at request time.
    """
    schema_keys = set(_SCHEMAS)
    handler_keys = set(handlers)
    cluster_keys = set(TOOL_CLUSTERS)
    public_keys = set(PUBLIC_MCP_TOOL_NAMES)
    internal_keys = set(INTERNAL_MCP_TOOL_NAMES)
    registered_keys = public_keys | internal_keys
    if (
        schema_keys != registered_keys
        or schema_keys != handler_keys
        or schema_keys != cluster_keys
    ):
        unclassified_schemas = schema_keys - registered_keys
        missing_registered_schemas = registered_keys - schema_keys
        missing_handlers = schema_keys - handler_keys
        unknown_handlers = handler_keys - schema_keys
        missing_clusters = schema_keys - cluster_keys
        unknown_clusters = cluster_keys - schema_keys
        details = []
        if unclassified_schemas:
            details.append(f"unclassified schemas registered: {sorted(unclassified_schemas)}")
        if missing_registered_schemas:
            details.append(f"missing registered schemas for: {sorted(missing_registered_schemas)}")
        if missing_handlers:
            details.append(f"missing handlers for: {sorted(missing_handlers)}")
        if unknown_handlers:
            details.append(f"unknown handlers for: {sorted(unknown_handlers)}")
        if missing_clusters:
            details.append(f"missing clusters for: {sorted(missing_clusters)}")
        if unknown_clusters:
            details.append(f"unknown clusters for: {sorted(unknown_clusters)}")
        raise KeyError("; ".join(details))

    return {
        name: ToolSpec(
            description=schema["description"],
            input_schema=schema["input_schema"],
            cluster=TOOL_CLUSTERS[name],
            handler=handlers[name],
        )
        for name, schema in _SCHEMAS.items()
        if name in public_keys
    }


__all__ = [
    "PUBLIC_MCP_TOOL_NAMES",
    "TOOL_CLUSTERS",
    "ToolSpec",
    "build_tools",
]
