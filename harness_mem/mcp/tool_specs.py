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


VALID_TOOL_PROFILES = ("memory",)

PUBLIC_MCP_TOOL_NAMES = frozenset(
    {
        "search_memory",
        "wake",
        "timeline",
        "temporal_query",
        "file_context",
        "get_observations",
        "get_task_handoffs",
        "get_confirmed_rules",
        "get_project_status",
        "get_project_profile",
        "set_active_project",
        "trace_relations",
        "search_raw",
        "search_skills",
        "get_skill",
        "ingest_sessions",
        "prepare_session_distill",
        "list_candidates",
        "get_candidate_detail",
        "auto_review_candidates",
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
        "dream_ledger",
        "dream_run",
        "dream_auto_tick",
        "undo_dream_item",
        "record_context_outcome",
    }
)

PROFILE_TOOL_NAMES = {
    "memory": PUBLIC_MCP_TOOL_NAMES,
}


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
                    "description": "v1.6.1: optional filter on MemoryEntry.memory_type. Multiple values are OR-ed.",
                },
                "include_history": {
                    "type": "boolean",
                    "description": "v1.7.0: include historical structured truth. Default false returns current truth only.",
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
        "description": "List all observations for a given session in a project.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "session_id": {"type": "string", "description": "Session ID to filter by"},
            },
            "required": ["project_name", "session_id"],
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
            "Return active project, memory counts, and slash-native next-step triage hints "
            "without requiring CLI status."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted)",
                },
            },
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
    "update_project_profile": {
        "description": (
            "Non-interactive project profile update. Adds (or, with replace=true, "
            "substitutes) profile fields. Fields omitted from the call are left "
            "untouched. Lists are deduplicated when merged "
            "so repeated calls with the same value are idempotent. Profiles feed "
            "wake-up directly, so this is the fastest way to teach the system a "
            "stable convention without going through the candidate review loop."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "description": {
                    "type": "string",
                    "description": "Short description of the project",
                },
                "stacks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Languages and frameworks (e.g. ['rust', 'tauri', 'typescript'])",
                },
                "key_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Important file paths",
                },
                "conventions": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Project conventions or guard rails",
                },
                "service_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Service names or URLs",
                },
                "database_hints": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Database connection strings or types",
                },
                "weak_link_signals": {
                    "type": "boolean",
                    "description": (
                        "Opt-in for v2.3.1 weak-link signal application "
                        "(wake re-grouping into Recent active / Stable / "
                        "quiet + search boost on repeat hits). Default false."
                    ),
                },
                "mcp_tool_profile": {
                    "type": "string",
                    "enum": list(VALID_TOOL_PROFILES),
                    "description": (
                        "Deprecated no-op. Public MCP now has one memory "
                        "surface; historical profile overrides are ignored."
                    ),
                },
                "maintenance_profile": {
                    "type": "string",
                    "enum": ["weekly-dream", "post-distill-metabolism"],
                    "description": (
                        "Optional guided opt-in maintenance preset. Stored on "
                        "ProjectProfile; status returns dry-run summaries but no "
                        "daemon or maintenance run is enabled by default."
                    ),
                },
                "retrieval_profile": {
                    "type": "string",
                    "enum": ["light", "quality"],
                    "description": (
                        "Optional project-level retrieval profile. None/light "
                        "keeps the default path. 'quality' opts into bounded "
                        "query rewrite/fanout metadata with a noop reranker; "
                        "it does not enable HyDE, ANN, Tantivy, or LanceDB."
                    ),
                },
                "replace": {
                    "type": "boolean",
                    "description": "When true, replace each provided list outright instead of merging.",
                    "default": False,
                },
            },
            "required": ["project_name"],
        },
    },
    "wake": {
        "description": (
            "Generate the wake-up context (project profile + recent rules + "
            "handoffs) for the given project, or the active project when "
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
            },
        },
    },
    "ingest_sessions": {
        "description": "Ingest local agent sessions for a project through MCP.",
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
                        "antigravity",
                        "opencode",
                        "hermes",
                    ],
                    "description": "Session client to ingest (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to ingest (default: 10)",
                    "default": 10,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore ingest cursor and rescan matching sessions",
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
                    "description": "Project root for cwd-scoped matching (default: current directory)",
                },
            },
            "required": ["project_name"],
        },
    },
    "prepare_session_distill": {
        "description": "One-shot project-scoped ingest plus recent observation packet for AI-led session-distill.",
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
                        "antigravity",
                        "opencode",
                        "hermes",
                    ],
                    "description": "Session client to ingest (default: auto)",
                    "default": "auto",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum sessions to ingest (default: 5)",
                    "default": 5,
                },
                "full_rescan": {
                    "type": "boolean",
                    "description": "Ignore ingest cursor and rescan matching sessions",
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
                    "description": "Project root for cwd-scoped matching",
                },
                "observation_limit": {
                    "type": "integer",
                    "description": "Recent observations to include in the evidence packet (default: 5)",
                    "default": 5,
                },
                "max_chars_per_observation": {
                    "type": "integer",
                    "description": "Maximum raw_content chars per observation (default: 6000)",
                    "default": 6000,
                },
                "run_ingest": {
                    "type": "boolean",
                    "description": "Run ingest before building the packet (default: true)",
                    "default": True,
                },
            },
            "required": ["project_name"],
        },
    },
    "list_candidates": {
        "description": "List structured memory candidates for human review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "status": {
                    "type": "string",
                    "enum": ["pending", "accepted", "rejected"],
                    "description": "Candidate status to list (default: pending)",
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
    "auto_review_candidates": {
        "description": (
            "Run conservative heuristic auto-review across pending memory entries "
            "and rule candidates. Returns the standard summary shape "
            "(auto_confirmed / auto_rejected / "
            "kept_pending / needs_user_confirmation). Public MCP always keeps "
            "this tool preview-only; durable changes go through explicit "
            "confirm/reject tools."
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
    "list_reflection_jobs": {
        "description": (
            "Read-only list of v2.4.0 reflection jobs for a project. "
            "Filters by project_name, status, and kind; orders by "
            "created_at descending. Default limit 50, max 200 (limit "
            "is clamped server-side). Returns ``{success, jobs}`` where "
            "``jobs`` is a list of ReflectionJob.to_dict() payloads — "
            "empty when no jobs match. Invalid status / kind values "
            "return ``{success: false, error}`` listing the valid set. "
            "This tool never mutates job state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Filter by project name (optional)",
                },
                "status": {
                    "type": "string",
                    "enum": [
                        "pending",
                        "processing",
                        "completed",
                        "failed",
                        "retryable",
                        "needs_distill",
                    ],
                    "description": "Filter by job status (optional)",
                },
                "kind": {
                    "type": "string",
                    "enum": ["reflection", "dream"],
                    "description": "Filter by job kind (optional). v3.1 adds 'dream'.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum jobs to return (default 50, max 200, clamped server-side)",
                    "default": 50,
                },
            },
        },
    },
    "get_reflection_job": {
        "description": (
            "Read-only fetch of a single v2.4.0 reflection job by id. "
            "Returns ``{success: true, job}`` where ``job`` is the full "
            "ReflectionJob.to_dict() payload, or "
            "``{success: false, error}`` when the id does not exist. "
            "This tool never mutates job state."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "job_id": {
                    "type": "string",
                    "description": "Reflection job id to fetch",
                },
            },
            "required": ["job_id"],
        },
    },
    "health_summary": {
        "description": (
            "Read-only project health summary (reflection queue + candidate "
            "health + signal freshness + chronic failures + maintenance hints)."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to active project when omitted).",
                },
            },
        },
    },
    "surface_cost_report": {
        "description": (
            "Read-only v3.4.0 local MCP surface cost observer report. "
            "Aggregates recent tool output token estimates, high-output calls, "
            "and drilldown hints from the local event log without storing raw "
            "tool arguments or response content."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Optional project filter.",
                },
                "days": {
                    "type": "integer",
                    "description": "Lookback window in days (default 7).",
                    "default": 7,
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum recent cost events to inspect (default 200, max 1000).",
                    "default": 200,
                },
            },
        },
    },
    "metabolism_preview": {
        "description": (
            "Preview the next metabolism run's input window without writing "
            "suggestions or mutating truth. Reads recent observations, stale "
            "pending candidates, recently-superseded historical truths, "
            "low-success skills, and repeat search-hit aggregates over the "
            "lookback window, applies per-dimension caps and a heuristic soft "
            "token budget, then persists a MetabolismRun(kind=\"preview\", "
            "status=\"preview\") for audit. Returns {success, run_id, "
            "project_name, time_range, dimensions, notes, signals_used}. "
            "v2.3.0: preview only, no daemon, no suggestions, no truth mutation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "budget": {
                    "type": "object",
                    "description": "Optional per-dimension caps and soft token cap. Missing fields fall back to ReplayBudget defaults.",
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
    "metabolism_run": {
        "description": (
            "Run a metabolism pass over signals + replay window and "
            "persist suggestion candidates for later review. Uses the "
            "same window selection as metabolism_preview, then runs the "
            "merge / stale proposers (auto-supersede deferred to v2.3.2) "
            "and writes each suggestion as a pending candidate plus a "
            "MetabolismRun(kind=\"metabolism\", status=\"completed\") "
            "audit record. Unlike metabolism_preview this DOES persist new "
            "candidate rows — use it when you want suggestions to land in "
            "the review queue, not just see what they would be. v2.3.1: "
            "merge candidates write proposed_content=\"\" (the Agent fills "
            "the merged content at confirm time); stale candidates set "
            "valid_to=now on confirm without producing a replacement. "
            "Returns {success, run_id, project_name, time_range, "
            "dimensions, notes, output_counts}."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {
                    "type": "string",
                    "description": "Project name (defaults to the active project when omitted).",
                },
                "budget": {
                    "type": "object",
                    "description": "Optional per-dimension caps and soft token cap. Missing fields fall back to ReplayBudget defaults.",
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
            "Run one host/client scheduler tick for v3.1 auto dream. The tick "
            "only enqueues ReflectionJob(kind='dream') when "
            "dream.auto.enabled and scheduler gates allow it."
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


TOOL_CLUSTERS = {
    # Daily read/context surfaces.
    "search_memory": "core_read",
    "timeline": "core_read",
    "temporal_query": "core_read",
    "get_observations": "core_read",
    "get_task_handoffs": "core_read",
    "get_confirmed_rules": "core_read",
    "get_project_profile": "core_read",
    "file_context": "core_read",
    "get_project_status": "core_read",
    "set_active_project": "core_read",
    "wake": "core_read",
    # Advanced or lower-frequency read/profile surfaces.
    "trace_relations": "review_read",
    "search_raw": "review_read",
    "search_skills": "review_read",
    "get_skill": "review_read",
    "update_project_profile": "advanced",
    "record_context_outcome": "advanced",
    # Candidate/truth loop.
    "ingest_sessions": "truth_loop",
    "prepare_session_distill": "truth_loop",
    "list_candidates": "truth_loop",
    "get_candidate_detail": "truth_loop",
    "auto_review_candidates": "truth_loop",
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
    # Internal maintenance surfaces.
    "metabolism_preview": "maintenance",
    "metabolism_run": "maintenance",
    # Dream is a default product capability; the cluster name is separate from
    # whether a tool appears in the public MCP surface.
    "dream_ledger": "dream",
    "dream_run": "dream",
    "dream_auto_tick": "dream",
    "undo_dream_item": "dream",
    # Maintainer/release/observer surfaces.
    "list_reflection_jobs": "maintainer",
    "get_reflection_job": "maintainer",
    "health_summary": "maintainer",
    "surface_cost_report": "maintainer",
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
    if schema_keys != handler_keys or schema_keys != cluster_keys:
        missing_handlers = schema_keys - handler_keys
        unknown_handlers = handler_keys - schema_keys
        missing_clusters = schema_keys - cluster_keys
        unknown_clusters = cluster_keys - schema_keys
        details = []
        if missing_handlers:
            details.append(f"missing handlers for: {sorted(missing_handlers)}")
        if unknown_handlers:
            details.append(f"unknown handlers for: {sorted(unknown_handlers)}")
        if missing_clusters:
            details.append(f"missing clusters for: {sorted(missing_clusters)}")
        if unknown_clusters:
            details.append(f"unknown clusters for: {sorted(unknown_clusters)}")
        raise KeyError("; ".join(details))

    for profile, tool_names in PROFILE_TOOL_NAMES.items():
        missing_profile_tools = tool_names - schema_keys
        if missing_profile_tools:
            raise KeyError(
                f"{profile} profile references unknown tools: "
                f"{sorted(missing_profile_tools)}"
            )

    return {
        name: ToolSpec(
            description=schema["description"],
            input_schema=schema["input_schema"],
            cluster=TOOL_CLUSTERS[name],
            handler=handlers[name],
        )
        for name, schema in _SCHEMAS.items()
    }


__all__ = [
    "PROFILE_TOOL_NAMES",
    "PUBLIC_MCP_TOOL_NAMES",
    "TOOL_CLUSTERS",
    "ToolSpec",
    "VALID_TOOL_PROFILES",
    "build_tools",
]
