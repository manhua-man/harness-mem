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

from harness_mem.core.schemas.evidence import EvidenceRef

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
        "inspect_sessions",
        "prepare_session_distill",
        "submit_distill_chunk",
        "finalize_session_distill",
        "list_candidates",
        "get_candidate_detail",
        "govern_memory",
        "dream_ledger",
        "dream_run",
        "record_context_outcome",
    }
)

# Ordered map of tool name → schema. Order is the discovery order MCP
# clients see; keep new tools at the bottom of their cluster (read /
# ingest / review / suggest) to keep the registry scannable.
_SESSION_REFERENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {**{name: {"type": "string"} for name in ("client", "session_id", "source_id", "source_revision", "reference_id", "project_root", "project_name")},
                   "scope": {"type": "string", "enum": ["all", "project"]}},
    "required": ["client", "session_id", "source_id", "source_revision", "reference_id"],
}

_SCHEMAS: dict[str, _SchemaOnly] = {
    "inspect_sessions": {
        "description": "Read-only device-session inventory, source pages, themes or frozen-batch progress. Missing/absent/multiple workspace roots are valid; directories are optional. Discovery refs are not immutable revisions: prepare fully reads and freezes selected sources. No imports, jobs, memory writes or background work.",
        "input_schema": {
            "type": "object",
            "properties": {
                "scope": {"type": "string", "enum": ["all", "project"], "description": "All device sessions by default; project is an explicitly requested optional source filter."},
                "project_root": {"type": "string", "description": "Optional source filter, including a historical missing directory. Omit for all device sessions. Do not ask users to fill this field."},
                "project_name": {"type": "string", "description": "Optional context label; historical source roots never reserve this name. Selected sources are independently validated within their root."},
                "action": {"type": "string", "enum": ["inventory", "source", "overview"], "default": "inventory"},
                "clients": {"type": "array", "items": {"type": "string", "enum": ["claude-code", "codex", "cursor", "grok", "hermes", "opencode", "antigravity"]}},
                "session": _SESSION_REFERENCE_SCHEMA,
                "offset": {"type": "integer", "minimum": 0, "default": 0},
                "page_chars": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 16000},
                "batch_id": {"type": "string", "description": "Read progress of an existing frozen manual batch"},
                "sessions": {"type": "array", "items": _SESSION_REFERENCE_SCHEMA, "description": "Fixed source scope for a read-only theme overview"},
                "coverage": {"type": "array", "items": {"type": "object", "properties": {
                    "reference_id": {"type": "string"}, "content_sha256": {"type": "string"},
                    "offset": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 0},
                }, "required": ["reference_id", "content_sha256", "offset", "end"]}, "description": "Ranges returned by source pages that the Agent completely read"},
                "topics": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"}, "evidence": {"type": "array", "items": {"type": "object", "properties": {
                        "reference_id": {"type": "string"}, "start": {"type": "integer", "minimum": 0}, "end": {"type": "integer", "minimum": 1},
                    }, "required": ["reference_id", "start", "end"]}},
                }, "required": ["name", "evidence"]}, "description": "Agent-proposed themes with source locations; multiple themes per session are allowed"},
            },
            "required": [],
        },
    },
    "search_memory": {
        "description": (
            "Default scope=all, including global decisions. NEVER infer scope=project from task/workspace names; "
            "only an explicit USER request permits project-only filtering. If an inferred filter misses, "
            "follow retry_without_project_filter before assuming memory is absent. Respect explicit user restrictions. "
            "Use one focused topic for related missing decisions; reuse every returned fact it answers. "
            "Repeat only for unanswered questions or new conflicts; keyword variants are not independent verification. "
            "Check current applicability against sources. Returns titles and whole statements. "
            "Follow continuation for more results; detail=full opens an indexed long fact. "
            "Empty query browses natural modules. Exact conversation evidence: search_raw."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional context, not a filter with all. Required for explicit project-only scope; global decisions may otherwise be missed.",
                },
                "query": {"type": "string", "description": "The specific topic or missing decision to recover; avoid concatenating unrelated task keywords."},
                "budget_tokens": {
                    "type": "integer", "minimum": 1,
                    "description": "Complete-page size: cl100k_base or conservative UTF-8 bytes. Default: cost_budget.search_tokens.",
                },
                "cursor": {"type": "string", "description": "Position from the returned continuation call."},
                "detail": {
                    "type": "string", "enum": ["auto", "full"], "default": "auto",
                    "description": "auto: whole facts fitting the page; full: one complete fact, even beyond the page size.",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "all"],
                    "description": "all for ordinary tasks; project excludes global/other labels and requires explicit user restriction.",
                    "default": "all",
                },
            },
            "required": ["query"],
        },
    },
    "autopilot_search_tick": {
        "description": (
            "Host-neutral task-aware search scheduler for Agent events. Concrete memory-backed uncertainty "
            "runs bounded search_memory and returns context_injection; otherwise returns a skip reason. "
            "Not a session-start wake replacement."
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
                    "description": "Optional current-task context; automatic search still searches all memory by default.",
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
                    "description": "Size of the complete tick response, including feedback fields. Additional knowledge remains accessible through continuation.",
                    "minimum": 1,
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
                "project_name": {"type": "string"},
                "limit": {
                    "type": "integer",
                    "description": "Optional observation count; omitted returns all matching observations",
                },
            },
            "required": ["project_name"],
        },
    },
    "search_raw": {
        "description": "Regex search raw observations with exact snippets and matching current knowledge plus its bound evidence. Historical wording alone does not establish an unresolved current conflict.",
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
                "project_name": {"type": "string"},
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
                "project_name": {"type": "string"},
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
                "project_name": {"type": "string"},
            },
            "required": ["project_name"],
        },
    },
    "file_context": {
        "description": (
            "Read file-associated memory with source attribution, current file fingerprints, "
            "Python symbols/imports, code-evidence source IDs and stale-reference checks. "
            "Advisory; never blocks file reads."
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
            "Return relevant current memory across all projects and whether current-context maintenance is waiting. "
            "Without a task, return availability and a reading call rather than the whole library. "
            "Larger task results include a search_memory continuation call."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional current-task context; it does not restrict the default memory search.",
                },
                "current_task": {
                    "type": "string",
                    "description": "Optional current task used to build a task-aware wake packet.",
                },
                "budget_tokens": {
                    "type": "integer", "minimum": 1,
                    "description": "Size of the complete wake response. Omit to use cost_budget.wake_tokens. All remaining facts remain readable through continuation.",
                },
                "scope": {
                    "type": "string", "enum": ["all", "project"], "default": "all",
                    "description": "All current memory by default; project is an explicit optional filter.",
                },
            },
        },
    },
    "prepare_session_distill": {
        "description": (
            "Prepare source-verified review of an existing memory or processing job. Requires target_knowledge from search or an existing distill_job_id. "
            "Daily recording and session processing are automatic; this is not a manual remember or batch entry. "
            "Default semantic mode checks complete sources; submit reviewed memory_points in finalize without preparing again. "
            "include_current returns source-derived relevant current facts with the full source, without changing job ownership; mutually exclusive with current_query. "
            "current_query returns all matching current facts in the same packet and resolves their common owner, avoiding a separate search. "
            "For a correction, pass target_knowledge from search; its unique current owner is resolved automatically."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Optional context label, not a unique directory identity."},
                "include_current": {"type": "boolean", "default": False,
                                    "description": "Include related current memories using the complete immutable source text as query. Context only, no exhaustive semantic-match guarantee or automatic owner binding; explicit project scope stays strict."},
                "current_query": {"type": "string", "minLength": 1,
                                  "description": "Topic whose complete current memories should accompany this one prepared session/job; their common owner is resolved, no write implied."},
                "target_knowledge": {
                    "type": "array", "minItems": 1,
                    "description": "Exact current memories from search to correct; runtime resolves their common write owner. Reuse title, statement, optional module and project_name.",
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "title": {"type": "string"}, "statement": {"type": "string"},
                            "module": {"type": "array", "items": {"type": "string"}},
                            "project_name": {"type": "string"},
                        },
                        "anyOf": [{"required": ["title"]}, {"required": ["statement"]}],
                    },
                },
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
                    "description": "Transcript source to sync before distill",
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
                    "description": "all: selected device sessions without directory setup; project: explicit source filter.",
                    "default": "project",
                },
                "project_root": {
                    "type": "string",
                    "description": "Optional repository-evidence context; not required for device sessions or verified user statements.",
                },
                "observation_limit": {
                    "type": "integer",
                    "description": "Optional observation count; omitted includes all matching observations",
                },
                "run_ingest": {
                    "type": "boolean",
                    "description": "Run low-level transcript sync before building the packet",
                    "default": True,
                },
                "distill_job_id": {
                    "type": "string",
                    "description": (
                        "Review or resume this exact existing processing job; does not start manual session discovery."
                    ),
                },
                "session_id": {
                    "type": "string",
                    "description": (
                        "Native source of an explicit correction; use with exact target_knowledge from search."
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
                        "raw: per-chunk Agent loop. semantic: runtime hash-checks/checkpoints EVERY raw chunk and returns complete parsed exchanges."
                    ),
                    "default": "semantic",
                },
                "detail_level": {
                    "type": "string",
                    "enum": ["compact", "full"],
                    "description": (
                        "compact: complete exchanges/refs, no duplicate diagnostics. full: include diagnostics."
                    ),
                    "default": "compact",
                },
                "budget_tokens": {
                    "type": "integer",
                    "minimum": 256,
                    "description": (
                        "Advisory diagnostic budget, NEVER a source-reading limit; complete conversation remains returned."
                    ),
                    "default": 3000,
                },
                "drilldown_exchange_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "description": (
                        "Complete semantic windows at one-based indexes before raw-proof drilldown."
                    ),
                },
                "drilldown_chunk_indexes": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 0},
                    "description": (
                        "Read-only raw chunk indexes after reviewing, for candidate-grade evidence."
                    ),
                },
                "drilldown_query": {
                    "type": "string",
                    "maxLength": 200,
                    "description": (
                        "Read-only raw search after reviewing; returns every matching chunk for proof."
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
            "Finalize a fully read session and consistent semantic review, using only this job's candidates. "
            "Optionally submit all memory_points here; runtime stages them via the existing candidate owner before the same source/evidence/lease/transaction gates. "
            "readback_verified=true proves saved changes passed fresh SQLite + ordinary-search checks; "
            "reuse returned knowledge_changes instead of another readback call. Unfinished work remains partial."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
                "job_id": {
                    "type": "string",
                    "description": "Review-ready distill job id",
                },
                "memory_points": {
                    "type": "array",
                    "description": "All decisions for this prepared job; do not call suggest separately for these points. Runtime derives project, job, category and source explanation.",
                    "items": {
                        "type": "object", "additionalProperties": False,
                        "properties": {
                            "content": {"type": "string"},
                            "canonical_title": {"type": "string"},
                            "topic_path": {"type": "array", "items": {"type": "string"}},
                            "evidence_basis": {"type": "string", "enum": ["repository", "user_statement", "transcript", "source_report"]},
                            "verification_outcome": {"type": "string", "enum": ["verified", "unverified", "contradicted", "not_applicable"],
                                                     "description": "Writing dispositions require verified: the fully read typed source supports this exact point. user_statement verifies what the user stated; source_report verifies that speaker's bounded account, not external truth. not_applicable is for intentional non-writing points."},
                            "verification_refs": {"type": "array", "items": EvidenceRef.model_json_schema()},
                            "assimilation_disposition": {"type": "string", "enum": ["add", "confirm", "refine", "replace", "no_write", "handoff", "defer", "conflict", "reject"]},
                            "assimilation_reason": {"type": "string"},
                            "target_knowledge": {"type": "array", "items": {"type": "object"}},
                            "retained_state_item": {"type": "string", "description": "Only if this explicitly classified user current-state point was also mistakenly listed in unfinished_work: must exactly equal both point content and that work item. Excluded only after verified successful promotion; real handoffs stay."},
                        },
                        "required": ["content", "canonical_title", "topic_path", "evidence_basis", "verification_outcome", "verification_refs", "assimilation_disposition", "assimilation_reason"],
                    },
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
                            "description": "Actual unfinished actions only. Supported undecided/unknown states belong in memory_points, not this work list.",
                        },
                        "retained_state_refs": {
                            "type": "array", "description": "Optional compatibility binding for an explicitly classified current state also listed as work; batch memory_points derives these internally.",
                            "items": {"type": "object", "additionalProperties": False,
                                      "properties": {"candidate_id": {"type": "string"}, "unfinished_work_item": {"type": "string"}},
                                      "required": ["candidate_id", "unfinished_work_item"]},
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
                                "Optional detailed review for compatibility; an explicit no_promotion review needs no extra questionnaire. "
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
                "project_name": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": list(_CURRENT_CANDIDATE_STATUSES),
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
            "Writes temporary candidates, knowledge decisions or handoffs. suggest: kind=memory|rule|relation; "
            "memory requires category/content/source. Distill jobs: suggest, then finalize (do not decide early). "
            "Include distill_job_id, evidence_basis, verification_outcome and typed verification_refs; "
            "runtime derives Answer Gate, only ANSWERED can write truth. "
            "Also require assimilation_disposition and assimilation_reason; add/refine/replace require canonical_title and "
            "topic_path as whole-name JSON array, NEVER path string. confirm/refine/replace select exact current "
            "target_knowledge=[{title,statement,module}] from normal search (title or statement required; module optional); "
            "confirm may reuse its unchanged statement. Unresolved targets retain old memory and unfinished work; "
            "independent valid points may save. Internal IDs remain compatible for existing callers but "
            "must not be requested from users. "
            "decide: kind=knowledge, decision=confirm|reject, project_name, candidate_id, explicit disposition. "
            "Delete: decision=delete, project_name and exactly one target_knowledge selection; omit candidate_id/knowledge_items. "
            "Replacement deletes old current truth, not history. Candidates are not legacy MemoryEntry truth. "
            "Evidence basis/ref kind: repository|user_statement|transcript|source_report, NEVER session_exchange. "
            "source_report records only what an authenticated source speaker reported, not "
            "external current truth or user approval; use exchange_index, digest and speaker role. "
            "User refs need exchange_index + returned content_sha256, no transcript locator. "
            "Refs accept kind/locator/content_sha256/exchange_index/chunk_index/role, not source/job IDs. "
            "handoff requires project_name/task_id/summary/status and distill_job_id for distill work."
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
                    "properties": {
                        # These are names of existing handler arguments, not new
                        # validation constraints. additionalProperties remains
                        # true for the composite surface's other action fields.
                        "kind": {"description": "Existing action kind: memory, rule, relation or knowledge."},
                        "project_name": {"description": "Context label returned by the selected job/target."},
                        "category": {"description": "Required for memory suggestions."},
                        "content": {"description": "The narrow candidate statement, required for memory suggestions."},
                        "source": {"description": "Required source explanation for memory suggestions."},
                        "distill_job_id": {"description": "Returned job binding; required for distill suggestions."},
                        "assimilation_disposition": {"description": "add, refine, confirm, replace, no_write, handoff, defer, conflict or reject."},
                        "assimilation_reason": {"description": "Required explanation of the disposition."},
                        "canonical_title": {"description": "Exact field name for the knowledge title; NOT title."},
                        "topic_path": {"description": "JSON array of whole category names; never a path string."},
                        "evidence_basis": {"type": "string", "enum": ["repository", "user_statement", "transcript", "source_report"]},
                        "verification_outcome": {"type": "string", "enum": ["verified", "unverified", "contradicted", "not_applicable"]},
                        "verification_refs": {"type": "array", "items": EvidenceRef.model_json_schema(),
                                              "description": "Exact typed source references; user statements use kind=user_statement, exchange_index and the returned exchange digest."},
                        "target_knowledge": {
                            "type": "array",
                            "description": "Exact old memory text from ordinary search; no user-managed identifiers.",
                            "items": {
                                "type": "object",
                                "properties": {"title": {"type": "string"}, "statement": {"type": "string"},
                                               "project_name": {"type": "string", "description": "Optional unchanged context label returned by ordinary search."},
                                               "module": {"type": "array", "items": {"type": "string"}}},
                                "anyOf": [{"required": ["title"]}, {"required": ["statement"]}],
                                "additionalProperties": False,
                            },
                        },
                    },
                },
            },
            "required": ["action", "arguments"],
        },
    },
    "record_context_outcome": {
        "description": (
            "Record used/ignored/misleading context as a shadow RetrievalSignal(context_outcome); "
            "never changes confirmed truth. Opt-in ranking may use the signal as a small explainable hint."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string"},
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
}

# Retired internal handler names. Keep this denylist so tests and serializers
# cannot accidentally reintroduce them into MCP tools/list, public hints, or
# exported descriptors.
INTERNAL_MCP_TOOL_NAMES = frozenset(
    {
        "dream_auto_tick",
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
    "inspect_sessions": "review_read",
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
