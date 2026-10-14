# Deferred work and scope ledger

This is the current 0.9.x scope ledger. Historical 0.8.x scope-lock documents
remain release records and do not override this list.

Rows that describe an older release retain that release's numbers. The current
`0.9.28` surface has 20 public MCP tools and no knowledge history or undo chain.

Planning reconciliation: 2026-10-14. The
[current iteration plan](../roadmap.md#current-iteration-plan) owns candidate
versions; [the direction backlog](next-iteration-directions.md) owns unselected
work and entry conditions. Historical "shipped" rows prove their release scope,
not current wake relevance, final-response budgets or live-host quality.

| Item | Status | Reason / revisit rule |
|------|--------|-----------------------|
| Golden CI infrastructure + fixture expansion | shipped in 0.9.0 | Retrieval-isolated and scale coverage now gate quality claims. |
| Admission preflight / grill metadata | deferred | Keep admission in existing Skills and `govern_memory`; add runtime metadata only with measured review value. |
| Rust zero-copy parameter passing | deferred | No golden hotspot proof yet. |
| RRF algorithm tuning / adaptive IDF | deferred | Requires a measurable golden-suite win without stability loss. |
| PyPI publishing | out of product | GitHub Releases remain the canonical package channel. |
| Duplicate `mcp-router` / `mcp_router` JSON snapshots | removed in 0.9.6 | The byte-identical, unpackaged aggregate snapshots had no repository consumer and advertised stale tools. Live Router aliases remain supported. |
| `code/mcps/grok_com_github/**` maintenance | out of product | Not a harness-mem product surface. |
| Active docs and host-command convergence | shipped in 0.9.1 | Retired governance vocabulary is removed and generated copies are guarded against drift. |
| Deterministic offered-job distill | shipped in 0.9.3 | Optional `distill_job_id` exact targeting respects project scope, active-lane fairness, and retry backoff. Originally planned for 0.9.2. |
| Split `tool_handlers.py` by bounded capability | shipped in 0.9.3 | Read/status/dream/distill/governance bodies sat behind the existing facade; that release had 27 public tools. `0.9.28` has 20. Originally planned for 0.9.2. |
| Recovery center and memory-quality scorecard | shipped in 0.9.3 | Risk-classified Doctor actions, privacy deletion receipts, outcome quality metrics, and stuck-queue explanations ship without automatic destructive repair. |
| Terminal distill outcome and processed-source cleanup | shipped in 0.9.5 (folded from 0.9.4) | Existing jobs record promoted/no-candidate and retained/deleted/failure outcomes; raw deletion remains default-off, receipt-first, and truth-preserving. |
| Shared-container per-session deletion | deferred | Hermes/OpenCode SQLite and Antigravity shared JSONL require separately replay-tested transactional deleters; until then they report unsupported and remain untouched. |
| Candidate evidence basis + verification outcome | shipped in 0.9.5 | Evidence origin (`repository`, `user_statement`, `transcript`) remains separate from verification outcome (`verified`, `unverified`, `contradicted`, `not_applicable`). The existing candidate, finalize, Dream, event-ledger, cleanup, and status surfaces own the contract; no manual promotion gate or new MCP tool was added. See `docs/roadmap/v0.9.5-evidence-grounded-dream.md`. |
| Relevant, concise daily reading | implemented, unreleased: 0.9.29 work | Ranking, taskless availability, measured response selection, continuation and whole-entry reading are integrated. |
| Actual task use and reduced repeated context | planned: 0.9.30 | Improve recall timing and repeated context; compare complete task results. |
| Natural knowledge grouping and wider semantic quality | later direction | Compare long-session quality, independent facts, duplication and readable grouping. |
| Daily integration across supported hosts | current product scope | All seven hosts share the remember/recall/correct/resume contract. Track native command, source and Hook evidence per host; earlier Codex acceptance was one execution sample, not a Codex-only product boundary. |
| Natural host triggers | path-specific verification | Observe real callbacks when claiming native triggering; fixture or scripted Hook success does not prove the corresponding application fired it. |
| Hermes background gateway and Doctor profile coverage | separate follow-up | Background remains deferred; recheck the recorded Doctor coverage gap against current code before scheduling a fix. |
| External web/API revalidation | later direction | Revisit the original source and update changed knowledge through existing verification. |
| Knowledge dashboard, cloud sync and extra daily entries | not selected | No demonstrated need in the present recall work; a new concrete user outcome is required before reconsidering. |

Current lexical ranking fixes proceed in 0.9.29. Revisit larger retrieval or
runtime optimizations when normal-task measurements show where they help.
