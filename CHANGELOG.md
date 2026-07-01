# Changelog

## Unreleased

### Fixed

- MCP stdio now accepts standard `Content-Length` framed requests while keeping
  the existing newline-delimited JSON direct-client path.

## [0.8.9] - 2026-06-30

### Added

- Added `docs/autopilot-search-policy.md`, defining `wake -> search -> distill
  -> review -> dream` as an automatic Agent/runtime loop with task-aware search
  triggers, post-hoc audit semantics, and dream maintenance.
- Added the MCP `autopilot_search_tick` runtime scheduler. It maps
  context/tool/save-point events to bounded `search_memory` calls only when a
  concrete trigger is present, returning a source-attributed
  `context_injection` payload for the next Agent turn.
- Added contract tests for session-start skip behavior, convention uncertainty,
  tool-failure search, save-point claim grounding, and duplicate-query
  suppression.

### Changed

- Aligned README, MCP setup, `/hm:distill`, `session-distill`, and MCP tool
  descriptions around low-risk auto-review apply mode instead of a manual-only
  review gate.

## [0.8.8] - 2026-06-29

### Added

- Added `harness_mem/governance_status.py` and `docs/auto-promoted-memory-governance.md`
  for seven-status auto-promoted memory with post-hoc audit tiers.
- Added requirement-driven governance tests covering state transitions, auto-review
  promotion, confirm paths, and read-filter visibility.

### Changed

- `auto_review_candidates(apply=true)` now promotes low-risk candidates to
  `auto_confirmed`, risk-flagged passes to `provisional`, defers to `deferred`,
  and records governance events in `state-events.log`.
- `confirm_*` paths now set `user_confirmed` instead of legacy `accepted`.
- `wake` / `search_memory` / `list_memory_entries` treat `accepted`,
  `auto_confirmed`, and `user_confirmed` as full-weight readable truth; `provisional`
  is opt-in via `include_provisional`.
- Public MCP `auto_review_candidates` no longer forces preview-only apply.

## [0.8.7] - 2026-06-29

### Added

- Added `plugins/harness-mem/skills/grill-before-distill/SKILL.md`, grill-me
  standard admission on distill: deep interrogation for high-impact items, light
  checklist for ordinary candidates, lookback mode for confirmed truth (no MCP
  change).
- Added repo-local `answer-memory-evidence` and `ask-memory-boundary` skills as
  non-writing answerers for grill admission and review questions.
- Added `docs/memory-adoption.md`, operator policy for layered helpers
  (grill-before-distill, smart-search as a reference evidence pattern, Trellis
  pattern playbook) beside the default distill chain.

### Changed

- Updated `tools/session-distill`, `harness-mem`, and `harness-mem-autopilot`
  skills so distill runs prepare → draft claims → risk-scaled grill admission →
  `suggest_*`, with external evidence required before `confirm_*`.
- Updated `/hm:distill` command steps to match the aligned session-distill chain.

## [0.8.6] - 2026-06-29

### Changed

- Kept dream supersede output behind review: dream now queues supersede
  candidates as `pending_review` ledger items instead of auto-confirming truth
  lineage changes.
- Added optional structured wake action hints with `why_it_matters` without
  changing rendered wake text or adding MCP tools.

### Added

- Added exact public MCP tool allowlist regression coverage to preserve the
  single memory surface.

## [0.8.5] - 2026-06-29

### Changed

- Added low-confidence partial-match abstention and a lightweight 1-hop
  relation/decision boost, both exposed through additive retrieval metadata.

### Added

- Added a golden-suite A/B gate for adaptive retrieval experiments.

## [0.8.4] - 2026-06-29

### Changed

- Hardened current-truth reads so non-empty `superseded_by` links are treated
  as historical even if legacy data lacks `valid_to`.

### Added

- Added regression coverage for temporal query abstention/conflict behavior,
  supersede audit lineage, and MCP `deep_recall`.

## [0.8.3] - 2026-06-29

### Added

- Prepared the v0.8.3 Retrieval Quality Foundation baseline as a local,
  LLM-free read-path benchmark with golden fixtures for project isolation,
  stale truth exclusion, abstention, and vector-off fallback.
- Added CLI, MCP single-surface, plugin command sync, and storage/search
  invariant tests for the V4.2 boundary hardening pass.
- Added an env-gated MCP maintenance read/debug profile for operators to inspect
  reflection jobs, persisted metabolism audit runs, runtime health, and MCP cost
  reports without exposing mutating metabolism tools.
- Added regression coverage for wake action hints and cross-project
  observation/relation golden cases.

### Changed

- Kept recall explainability additive by exposing fixed
  `filter -> fts/vector -> merge -> hydrate/context` steps and optional
  `metadata.score_details` without changing the MCP tool list or
  `RecallResult` schema version.
- Removed top-level CLI `import` and `purge`; both now live under
  `harness-mem maintenance import` / `harness-mem maintenance purge` and default
  to dry-run previews unless `--apply` is passed.
- Kept CLI maintenance as a small flat operator surface for import/purge,
  index rebuilds, storage migration/export, and state audit; causal benchmark
  remains test-only, while generated-cache and wiki-bridge workflows were
  removed from the runtime package.
- Grouped plugin slash command sources by physical profile directory while
  keeping installed `/hm:*` command names flat.
- Removed the session-distill KB/PRD management surface; durable project,
  architecture, and product knowledge now flows through candidates and
  `/hm:review` instead of `knowledge-base.md` or PRD sync notes.
- Balanced SearchFacade result truncation across source kinds so memory hits do
  not starve relation or observation hits.
- Started the storage/search boundary split by keeping `LocalStructuredStore` as
  the compatibility facade while delegating durable truth updates to
  `TruthStore` and candidate status writes to `CandidateStore`.
- Kept metabolism and reflection jobs out of the default MCP surface; public
  `tools/list` no longer reports hidden maintenance tool counts.
- Updated `docs/roadmap.md`, `docs/recall-audit.md`, and release artifacts for
  the 0.8.x convergence line.

## [0.8.2] - 2026-06-25

### Added

- Added an additive MCP `recall` contract for `search_memory` and
  `trace_relations`, carrying evidence, sources, retrieval steps, planning
  metadata, and status without removing legacy response arrays.
- Added typed relation scoring for bounded relation tracing so causal and truth
  revision edges can outrank generic associations.
- Added a local append-only state audit ledger for candidate/review/supersede
  governance events, plus `maintenance state-audit`.
- Added a deterministic causal benchmark smoke test.
- Added focused pytest coverage for recall contracts, relation scoring, state
  audit events, MCP additive recall payloads, and the causal benchmark.
- Added a reproducible cold-start demo guide for the
  `wake -> search -> distill -> review` product path.
- Added a minimal public smoke workflow for install/build/runtime sanity checks.

### Changed

- Split MCP tool execution policy and handler implementations out of
  `mcp/server.py`; the server now owns stdio, backend initialization, registry
  assembly, and JSON-RPC dispatch.
- Added an explicit `review-read` MCP profile for deeper read drilldowns such as
  `trace_relations`, `search_raw`, `search_skills`, and `get_skill` while
  keeping the default `core-read` surface narrow.
- Split `tools/session-distill/lib/cli.py` command implementations into
  project, lifecycle, knowledge, and PRD handler modules while preserving the
  CLI compatibility wrappers.

### Fixed

- Aligned plugin metadata with the public `0.8.2` package version and
  Apache-2.0 license.
- Removed stale historical wording from the public runtime diagram.
- Removed the stale `direct_truth_write` guardrail token after confirming no
  live direct-truth-write surface remains.

### Validation

- `python -m compileall harness_mem`
- `python -m ruff check harness_mem plugins tools`
- `python -m pytest`
- `python -m harness_mem.cli --help`
- `python -m pytest tests/test_core_memory_absorption.py -k causal_benchmark`
- `cargo test --workspace`
- `cargo build --workspace --features python-extension`

## [0.8.1] - 2026-06-24

### Changed

- Reset the public repository around the core product definition:
  **local-first, auditable, pluggable Agent memory backend**.
- Kept the runtime source code public under `harness_mem/`.
- Kept the Agent integration layer public under `plugins/harness-mem/`.
- Kept the session distillation reference skill public under
  `tools/session-distill/`.
- Reduced public documentation to the README, Chinese README, quickstart, MCP
  setup notes, changelog, license, security policy, and public README assets.
- Pruned non-product repository materials from the public baseline.
- Removed maintainer-only evaluation reporting from the public runtime surface.

### Validation

- `python -m compileall harness_mem`
- `python -m harness_mem.cli --help`
- `python -m ruff check harness_mem plugins tools`
- `cargo test --workspace`
