# Roadmap Status

> Last verified: 2026-05-24 against repo files, implementation modules, and tests.
> Version truth is `pyproject.toml` + `harness_mem.__version__`.

This file is the quick answer to "which roadmap slices are actually done?"
The detailed design docs stay in the individual roadmap files; this page records
current implementation truth and intentional boundaries.

## Current Version

| Source | Value |
|---|---|
| `pyproject.toml` | `2.1.0` |
| `harness_mem/__init__.py` | `2.1.0` |
| `CHANGELOG.md` | `2.1.0` section present |

v2.1 is justified because the current tree changes the product surface: CLI is
now maintenance-only, REST API is removed, and docs now state that MCP is the
hidden transport behind IDE commands / Skills / agent workflows.

## Completion Matrix

| Slice | Status | Repo evidence | Boundary / caveat |
|---|---|---|---|
| v1.5.x | Complete historical foundation | `docs/roadmap-v15x.md`, `CHANGELOG.md` v1.5.x entries | Historical CLI/REST wording may describe pre-v2.1 surfaces. Current daily entry is no longer CLI. |
| v1.6.0 | Complete | `MemoryEntry.memory_type`; LongMemEval per-type docs and tests | Added typing/reporting; did not change wake selection by itself. |
| v1.6.1 | Complete | `wake_selection.py`, bucket budget config/tests, `DistillContext` readonly tests, `memory_type` filter tests | Bucket budget can be disabled; distill writes only candidate-layer suggestions. |
| v1.6.2 | Runtime complete | persistent vector storage/tests, `maintenance rebuild-vector-index`, vector doctor checks, embedding shootout docs | Manual benchmark gates are documented separately; default model stayed `all-MiniLM-L6-v2`. |
| v1.7.0-v1.7.3 | Complete | temporal fields, current/history reads, supersede candidate loop, bounded `trace_relations`, `search_raw`, temporal/verbatim tests | Relation graph engine exists, but natural-session population remains sparse unless LLM-driven distill or explicit relation suggestions feed it. |
| v1.8.0 | Complete conservative loop | `ProceduralCandidate`, confirmed `Skill`, `search_skills`, `record_skill_result`, MCP skill tools, procedural tests/fixtures | This is not autonomous learning: skills do not enter default wake, do not auto-confirm, do not cross projects, and no daemon exists. |
| v2.0.0 | Complete | heuristic `distill` CLI and MCP `distill_sessions` removed; distill path is LLM-agent only | `/hm:distill` remains the user workflow, backed by `prepare_session_distill` + `suggest_*`. |
| v2.1.0 | In current working tree | CLI parser exposes only maintenance commands; REST package/tests deleted; README/AGENTS/OpenSpec rewritten around Slash/Skill/agent workflows | Breaking surface cleanup, but MCP tool signatures and data schema are intentionally stable. |

## Not Done

These items are intentionally not claimed as shipped:

| Item | Status |
|---|---|
| Background daemon / IDE hook / turn-end self-check "随手记" | Not implemented. Current candidate writing happens only in explicit distill/user-requested flows. |
| Cross-project skill sharing | Not implemented. v1.8 skills are project-scoped. |
| Procedural skills in default wake selection | Not implemented by design. `search_skills` is explicit. |
| Autonomous deletion or truth mutation by AI | Not implemented by design. Truth changes go through candidate/supersede paths. |
| REST API as a product entry | Removed in v2.1. |
| CLI daily workflow (`wake`, `search`, `timeline`, candidate review) | Removed from the CLI surface in v2.1. Daily usage goes through IDE commands / Skills / agent workflows backed by MCP. |
| v1.9 Memory Metabolism / Dream | Vision only; not implemented. |

## Short Answer

v1.8 was done, but only as the conservative procedural-skill loop. It did not
ship background self-learning or automatic skill injection. The current state is
best labeled v2.1 because the main change after v2.0 is product-surface cleanup:
CLI maintenance-only, REST removed, and the daily path recentered on
`/hm:distill`, `/hm:wake`, `/hm:search`, Skills, and natural-language agent
instructions.
