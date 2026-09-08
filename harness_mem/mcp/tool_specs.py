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

_CURRENT_CANDIDATE_STATUSES = (
    "pending",
    "deferred",
    "conflict",
    "rejected",
    "assimilated",
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
        "file_context",
        "get_observations",
        "get_task_handoffs",
        "get_project_status",
        "get_project_profile",
        "search_raw",
        "prepare_session_distill",
        "submit_distill_chunk",
        "finalize_session_distill",
        "list_candidates",
        "get_candidate_detail",
        "govern_memory",
        "dream_ledger",
        "dream_run",
        "dream_auto_tick",
        "record_context_outcome",
    }
)

# Ordered map of tool name → schema. Order is the discovery order MCP
# clients see; keep new tools at the bottom of their cluster (read /
# ingest / review / suggest) to keep the registry scannable.
_SCHEMAS: dict[str, _SchemaOnly] = {
    "search_memory": {
        "description": (
            "Search current long-term memory for a project. The output contains "
            "only readable titles and statements. Use search_raw when exact "
            "conversation evidence is needed."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (required when scope=project)",
                },
                "query": {"type": "string", "description": "Search query"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
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
                "budget_tokens": {
                    "type": "integer",
                    "description": "Advisory budget for the bounded search tick.",
                    "default": 1600,
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
                    "description": "Optional observation count; omitted returns all matching observations",
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
                "project_name": {
                    "type": "string",
                    "description": "Project name (required when scope=project)",
                },
                "pattern": {"type": "string", "description": "Python regex pattern"},
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "Search scope: project or all (default: project)",
                    "default": "project",
                },
                "limit": {
                    "type": "integer",
                    "description": "Optional match count; omitted returns all matching evidence",
                },
            },
            "required": ["pattern"],
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
                "session_id": {
                    "type": "string",
                    "description": "Session ID to filter by",
                },
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
                    "description": "Optional handoff count; omitted returns all matching handoffs",
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
            "file path before reading the file itself. It also returns current "
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
                    "description": "Optional project root used to resolve relative paths for code evidence.",
                },
            },
            "required": ["path"],
        },
    },
    "get_project_status": {
        "description": (
            "Prepare the current project and its host Hook when needed, then return "
            "one short readiness message. Always pass the current workspace root and "
            "calling IDE/Agent host. Use harness-mem doctor for diagnostics."
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
            },
            "required": ["project_root", "host_client"],
        },
    },
    "wake": {
        "description": (
            "Return current project memory and whether maintenance is waiting."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
                "current_task": {
                    "type": "string",
                    "description": "Optional current task used to build a task-aware wake packet.",
                },
            },
        },
    },
    "prepare_session_distill": {
        "description": (
            "Prepare one remember-this-session decision packet. An explicit session_id "
            "selects that session directly, including parked work. Semantic mode "
            "checks the complete source so the common path can finalize without "
            "another prepare call."
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
                    "description": "Optional session count to sync before distill; omitted means all matching sessions",
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
                    "description": "Optional observation count; omitted includes all matching observations",
                },
                "run_ingest": {
                    "type": "boolean",
                    "description": "Run low-level transcript sync before building the packet (default: true)",
                    "default": True,
                },
                "distill_job_id": {
                    "type": "string",
                    "description": (
                        "Optional active job id to claim exactly. Used by automatic "
                        "maintenance so the selected job is processed deterministically."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Optional user-facing session id to select directly. The "
                        "latest matching project job is activated when parked."
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
                    "description": "Optional chunk count for caller-controlled batching; omitted claims all remaining chunks",
                },
                "evidence_mode": {
                    "type": "string",
                    "enum": ["raw", "semantic"],
                    "description": (
                        "Evidence delivery mode. raw preserves the existing per-chunk "
                        "Agent loop; semantic lets runtime hash-verify/checkpoint every raw "
                        "chunk and returns the smaller parser-derived session rendering."
                    ),
                    "default": "semantic",
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
                    "description": (
                        "Advisory target for the complete serialized response. "
                        "Compact evidence adapts to the remaining space; complete "
                        "coverage or explicit drilldown may expand with a receipt."
                    ),
                    "default": 3000,
                },
                "drilldown_exchange_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "description": (
                        "Read complete semantic windows for selected one-based exchange "
                        "indexes before querying candidate-grade raw proof."
                    ),
                },
                "drilldown_chunk_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
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
                        "Returns every matching chunk when semantic evidence needs proof."
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
                "chunk_id": {
                    "type": "string",
                    "description": "Claimed transcript chunk id",
                },
                "lease_owner": {
                    "type": "string",
                    "description": "Lease token returned with the chunk",
                },
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
                "job_id": {
                    "type": "string",
                    "description": "Review-ready distill job id",
                },
                "semantic_review": {
                    "type": "object",
                    "description": "Final outcome, contradictions, unfinished work, and evidence assessment",
                    "properties": {
                        "session_summary": {
                            "type": "string",
                            "minLength": 12,
                            "maxLength": 2000,
                            "description": (
                                "Concise human-readable account of what the session "
                                "was about, independent of memory promotion"
                            ),
                        },
                        "final_user_request": {"type": "string"},
                        "final_outcome": {"type": "string"},
                        "last_turn_status": {
                            "type": "string",
                            "enum": ["answered", "unfinished", "unknown"],
                        },
                        "contradictions": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "unfinished_work": {
                            "type": "array",
                            "items": {"type": "string"},
                        },
                        "evidence_status": {
                            "type": "string",
                            "enum": [
                                "answered",
                                "partial",
                                "contradicted",
                                "not_applicable",
                            ],
                        },
                        "promotion_decision": {
                            "type": "string",
                            "enum": ["promote", "partial", "no_promotion", "blocked"],
                        },
                        "zero_candidate_challenge": {
                            "type": "object",
                            "description": (
                                "Required for v1 jobs that produced no candidates. "
                                "Use the content hashes returned by semantic exchange drilldown."
                            ),
                            "properties": {
                                "version": {"type": "string", "enum": ["v1"]},
                                "source_revision": {"type": "string"},
                                "evidence_fidelity": {
                                    "type": "string",
                                    "enum": ["complete", "partial", "contradicted"],
                                },
                                "future_utility": {
                                    "type": "string",
                                    "enum": ["none", "session_only", "durable"],
                                },
                                "checks": {
                                    "type": "object",
                                    "properties": {
                                        name: {
                                            "type": "string",
                                            "enum": [
                                                "absent",
                                                "not_durable",
                                                "candidate_required",
                                            ],
                                        }
                                        for name in (
                                            "user_correction",
                                            "explicit_decision",
                                            "successful_solution",
                                            "repeated_failure",
                                            "rule_or_preference",
                                            "reusable_workflow_or_fact",
                                            "version_or_migration",
                                            "unfinished_handoff",
                                        )
                                    },
                                    "required": [
                                        "user_correction",
                                        "explicit_decision",
                                        "successful_solution",
                                        "repeated_failure",
                                        "rule_or_preference",
                                        "reusable_workflow_or_fact",
                                        "version_or_migration",
                                        "unfinished_handoff",
                                    ],
                                    "additionalProperties": False,
                                },
                                "inspected_exchange_refs": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "exchange_index": {
                                                "type": "integer",
                                                "minimum": 1,
                                            },
                                            "content_sha256": {
                                                "type": "string",
                                                "pattern": "^[0-9a-f]{64}$",
                                            },
                                        },
                                        "required": [
                                            "exchange_index",
                                            "content_sha256",
                                        ],
                                        "additionalProperties": False,
                                    },
                                },
                                "conclusion": {
                                    "type": "string",
                                    "enum": [
                                        "no_durable_candidate",
                                        "candidate_required",
                                    ],
                                },
                                "rationale": {"type": "string", "minLength": 12},
                            },
                            "required": [
                                "version",
                                "source_revision",
                                "evidence_fidelity",
                                "future_utility",
                                "checks",
                                "inspected_exchange_refs",
                                "conclusion",
                                "rationale",
                            ],
                            "additionalProperties": False,
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
            "List temporary knowledge candidates that still exist in the current "
            "processing workspace. Candidates are not long-term memory."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "status": {
                    "type": "string",
                    "enum": list(_CURRENT_CANDIDATE_STATUSES),
                    "description": "Temporary candidate status.",
                    "default": "pending",
                },
                "limit": {
                    "type": "integer",
                    "description": "Optional candidate count; omitted returns all matching candidates",
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
                "candidate_id": {
                    "type": "string",
                    "description": "Candidate or reviewable item id",
                },
                "candidate_kind": {
                    "type": "string",
                    "enum": [
                        "knowledge_candidate",
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
            "and task handoffs. Use action="
            "suggest with arguments.kind=memory|rule|relation; action=decide "
            "with kind=knowledge, decision=confirm|reject, project_name, "
            "candidate_id, and an explicit disposition. To delete incorrect current "
            "knowledge, use action=decide with kind=knowledge, decision=delete, "
            "project_name, and exactly one target_knowledge_ids value; omit candidate_id "
            "and knowledge_items. Use "
            "action=handoff. Replacement is a normal knowledge decision that "
            "deletes the old current row; it is not a separate history action. "
            "Suggestions are stored as temporary knowledge candidates, not legacy "
            "MemoryEntry truth. Distill-bound suggestions should include evidence_basis, "
            "verification_outcome, and content-free verification_refs so Dream "
            "can verify repository or explicit user-statement evidence. The "
            "runtime derives the Answer Gate status; only ANSWERED candidates "
            "may enter the truth layer. Distill suggestions must include an "
            "assimilation_disposition and assimilation_reason; add/refine/"
            "replace also require canonical_title and topic_path, while "
            "confirm requires exactly one id in assimilation_target_ids; refine/replace may name "
            "one or more current targets from the current knowledge view."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "suggest",
                        "decide",
                        "handoff",
                    ],
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
                    "description": (
                        "Optional returned source ids being rated. Omit when an opaque "
                        "retrieval_id is available."
                    ),
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
                "retrieval_id": {
                    "type": "string",
                    "description": (
                        "Opaque id returned by wake/search for exact surface-to-outcome "
                        "correlation. Contains no query or memory content."
                    ),
                },
            },
            "required": ["project_name", "surface", "outcome"],
        },
    },
    "dream_ledger": {
        "description": (
            "Return the latest background Dream status for a project, or one "
            "run by id. This is read-only and never changes memory."
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
            "Run one dream maintenance pass now. It parses and handles "
            "every selected dream result to a terminal state and writes a "
            "short DreamRun result."
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
    "dream_auto_tick": {
        "description": (
            "Run one host/client auto tick for dream. The tick only "
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
}

# Retired internal handler names. Keep this denylist so tests and serializers
# cannot accidentally reintroduce them into MCP tools/list, public hints, or
# exported descriptors.
INTERNAL_MCP_TOOL_NAMES = frozenset(
    {
        "set_active_project",
        "ingest_sessions",
        # Former orchestration handlers are intentionally absent from the MCP
        # schema and handler registries.
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
        "temporal_query",
        "undo_dream_item",
        "auto_review_candidates",
        "get_confirmed_rules",
        "get_skill",
        "search_skills",
        "trace_relations",
    }
)


TOOL_CLUSTERS = {
    # Daily read/context surfaces.
    "search_memory": "core_read",
    "autopilot_search_tick": "core_read",
    "timeline": "core_read",
    "get_observations": "core_read",
    "get_task_handoffs": "core_read",
    "get_project_profile": "core_read",
    "file_context": "core_read",
    "get_project_status": "core_read",
    "wake": "core_read",
    # Advanced or lower-frequency read surfaces.
    "search_raw": "review_read",
    "record_context_outcome": "advanced",
    # Candidate/truth loop.
    "prepare_session_distill": "truth_loop",
    "submit_distill_chunk": "truth_loop",
    "finalize_session_distill": "truth_loop",
    "list_candidates": "truth_loop",
    "get_candidate_detail": "truth_loop",
    "govern_memory": "truth_loop",
    # Dream is a default product capability; the cluster name is separate from
    # whether a tool appears in the public MCP surface.
    "dream_ledger": "dream",
    "dream_run": "dream",
    "dream_auto_tick": "dream",
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
    if (
        schema_keys != public_keys
        or schema_keys != handler_keys
        or schema_keys != cluster_keys
    ):
        unclassified_schemas = schema_keys - public_keys
        missing_registered_schemas = public_keys - schema_keys
        missing_handlers = schema_keys - handler_keys
        unknown_handlers = handler_keys - schema_keys
        missing_clusters = schema_keys - cluster_keys
        unknown_clusters = cluster_keys - schema_keys
        details = []
        if unclassified_schemas:
            details.append(
                f"unclassified schemas registered: {sorted(unclassified_schemas)}"
            )
        if missing_registered_schemas:
            details.append(
                f"missing registered schemas for: {sorted(missing_registered_schemas)}"
            )
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
