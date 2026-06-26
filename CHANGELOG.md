# Changelog

## [0.8.2] - 2026-06-25

### Added

- Added an additive MCP `recall` contract for `search_memory` and
  `trace_relations`, carrying evidence, sources, retrieval steps, planning
  metadata, and status without removing legacy response arrays.
- Added typed relation scoring for bounded relation tracing so causal and truth
  revision edges can outrank generic associations.
- Added a local append-only state audit ledger for candidate/review/supersede
  governance events, plus `maintenance state-audit`.
- Added a deterministic causal benchmark smoke command:
  `maintenance causal-benchmark`.
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
- `python -m harness_mem.cli maintenance causal-benchmark`
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
