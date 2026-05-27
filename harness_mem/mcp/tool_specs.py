"""MCP tool schema registry for harness-mem.

This module owns every tool's JSON Schema (``description`` + ``input_schema``).
It deliberately does **not** know about the handler functions — those live
in ``harness_mem.mcp.server`` next to the runtime backend singleton, and are
injected at module-import time via :func:`build_tools`.

Why the split:

- The schema block was ~666 lines (1/3 of server.py). Pulling it out makes
  the runtime file readable without changing any tool behavior.
- Schemas are pure data. Keeping them away from the handler functions
  removes a heavy noise-to-signal section from the server module.
- The factory pattern (``build_tools(handlers)``) avoids circular imports:
  ``tool_specs`` does not import ``server``; ``server`` imports
  ``tool_specs`` once and passes its handler dict in.

The schemas here mirror the OpenSpec contracts in ``openspec/specs/mcp/``.
When a tool's input schema changes, update both this file and the spec.
"""

from __future__ import annotations

from typing import Any, Callable, TypedDict


class ToolSpec(TypedDict):
    description: str
    input_schema: dict[str, Any]
    handler: Callable[..., dict[str, Any]]


class _SchemaOnly(TypedDict):
    """A ToolSpec without the handler. Internal: the handler is injected
    by :func:`build_tools` so this module stays runtime-free."""

    description: str
    input_schema: dict[str, Any]


# Ordered map of tool name → schema. Order is the discovery order MCP
# clients see; keep new tools at the bottom of their cluster (read /
# ingest / review / suggest) to keep the registry scannable.
_SCHEMAS: dict[str, _SchemaOnly] = {
    "search_memory": {
        "description": "Search structured memory entries and verbatim observations for a project.",
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
                "limit": {
                    "type": "integer",
                    "description": "Maximum skills to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
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
    "get_project_status": {
        "description": "Return active project and memory counts without requiring CLI status.",
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
    "auto_review_candidates": {
        "description": (
            "Run conservative heuristic auto-review across pending memory entries "
            "and rule candidates. Returns the summary shape from "
            "openspec/specs/mcp/spec.md (auto_confirmed / auto_rejected / "
            "kept_pending / needs_user_confirmation). Use apply=true to apply "
            "the decisions via the same status mutators users would invoke "
            "manually; apply=false (default) returns a preview without "
            "modifying any candidate."
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
    "suggest_skill": {
        "description": "Suggest a procedural skill candidate for later review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "project_name": {"type": "string", "description": "Project name"},
                "activation_condition": {"type": "string", "description": "When this workflow should run"},
                "steps": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Ordered workflow steps",
                },
                "termination_condition": {"type": "string", "description": "When this workflow is complete"},
                "success_examples": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Successful execution examples",
                },
                "source_session_id": {"type": "string", "description": "Source session id"},
                "source": {"type": "string", "description": "Source observation/file/candidate id"},
                "confidence": {"type": "number", "description": "Confidence score 0.0-1.0"},
            },
            "required": ["project_name", "activation_condition", "steps", "termination_condition"],
        },
    },
    "confirm_skill": {
        "description": "Confirm a procedural skill candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Procedural candidate ID to confirm"},
            },
            "required": ["candidate_id"],
        },
    },
    "reject_skill": {
        "description": "Reject a procedural skill candidate.",
        "input_schema": {
            "type": "object",
            "properties": {
                "candidate_id": {"type": "string", "description": "Procedural candidate ID to reject"},
            },
            "required": ["candidate_id"],
        },
    },
    "record_skill_result": {
        "description": "Record one execution outcome for a confirmed skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "skill_id": {"type": "string", "description": "Confirmed skill ID"},
                "success": {"type": "boolean", "description": "Whether the execution succeeded"},
            },
            "required": ["skill_id", "success"],
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
    if schema_keys != handler_keys:
        missing_handlers = schema_keys - handler_keys
        unknown_handlers = handler_keys - schema_keys
        details = []
        if missing_handlers:
            details.append(f"missing handlers for: {sorted(missing_handlers)}")
        if unknown_handlers:
            details.append(f"unknown handlers for: {sorted(unknown_handlers)}")
        raise KeyError("; ".join(details))

    return {
        name: ToolSpec(
            description=schema["description"],
            input_schema=schema["input_schema"],
            handler=handlers[name],
        )
        for name, schema in _SCHEMAS.items()
    }


__all__ = ["ToolSpec", "build_tools"]
