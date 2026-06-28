# Changelog

## Unreleased

### Changed

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

### Added

- Added CLI, MCP single-surface, plugin command sync, and storage/search invariant tests
  for the V4.2 boundary hardening pass.
- Added an env-gated MCP maintenance read/debug profile for operators to inspect
  reflection jobs, persisted metabolism audit runs, runtime health, and MCP cost
  reports without exposing mutating metabolism tools.

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
