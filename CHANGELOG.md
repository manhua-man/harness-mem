# Changelog

## Unreleased

## [0.8.23.1] - 2026-07-13

### Added

- A compact integration health summary in project status covering workspace,
  configured host, hook installation, transcript observations, and queued or
  processing distill work.
- Release gates that install the built wheels on clean Windows, macOS, and
  Linux runners and verify first-run MCP project adoption plus automatic hooks.

### Changed

- Version tags now attach six native wheels and an sdist to the GitHub Release,
  then publish the verified distributions to PyPI through GitHub OIDC Trusted
  Publishing. No long-lived PyPI password is stored in the repository.

## [0.8.23] - 2026-07-13

### Added

- Native OpenCode transcript ingest from the verified SQLite
  `session`/`message`/`part` database layout, scoped by `session.directory`.
- Native Antigravity transcript ingest from verified brain `transcript.jsonl`
  files, with workspace-path matching and truthful `client="antigravity"`
  observations.
- Transcript evidence now validates OpenCode databases and Antigravity JSONL
  samples instead of treating configuration directories as transcript data.
- Native Antigravity lifecycle hooks through merged `.agents/hooks.json`
  `PreInvocation` and `Stop` entries with JSON stdin/stdout bridge scripts.

- Native Hermes transcript sync for `~/.hermes/sessions/session_*.json`,
  including schema-backed parsing, project-root content matching, duplicate
  skips, and MCP `client="hermes"` support through the distill sync path.
- Wake auto-sync now uses the project-scoped Grok and Hermes adapters when
  those hosts invoke the CLI wake path.
- Session-start wake now leads with a project-scoped recent-context index and
  keeps stable truth and active handoffs as secondary sections.
- `get_observations` now accepts observation IDs from recent-context output for
  direct drilldown while preserving the existing session-based lookup.

### Changed

- Agent-facing guidance now treats `/hm:distill` / `prepare_session_distill`
  as the product entrypoint. Low-level transcript sync remains internal, and
  automatic hook maintenance stays quiet unless the user requests audit detail.
- Project-scoped MCP initialization now creates the workspace profile and
  installs matching host hooks automatically. Manual project switching,
  transcript ingest, and generic hook installation are no longer public tools.
- Distill guidance now returns a concise default outcome; candidate counts,
  evidence IDs, and auto-review decisions remain available through review and
  diagnostic surfaces.
- Automatic maintenance now stages evidence as a durable pending distill task.
  An Agent consumes the task, creates warranted candidates, applies auto-review,
  and only then runs Dream. Evidence packet preparation is no longer described
  as completed conversation summarization.
- `transcript-evidence` now reports OpenCode and Antigravity as adapter-backed
  when their verified transcript stores are readable.

## [0.8.22] - 2026-07-10

### Added

- Native Grok transcript ingest for
  `~/.grok/sessions/<url-encoded-project-root>/<session>/chat_history.jsonl`,
  including project-root scoped listing, transcript parsing, duplicate-skip
  behavior, and MCP `ingest_sessions(client="grok", project_root=...)`.

### Changed

- Grok now resolves as an adapter-backed transcript source; Hermes and OpenCode
  remain unavailable until their transcript paths and schemas are proven with
  local fixtures.

## [0.8.21.1] - 2026-07-10

### Added

- `harness-mem integration transcript-evidence` reports local transcript
  evidence separately from adapter availability for Grok, Hermes, and
  OpenCode.
- Grok evidence discovery verifies the concrete
  `~/.grok/sessions/<url-encoded-project-root>/<session>/chat_history.jsonl`
  layout before marking a host as `verified_transcript_path`.

### Changed

- Hermes and OpenCode remain explicitly unavailable for transcript ingest when
  only host roots or no local files are found; the report no longer lets hook
  install support be mistaken for transcript adapter support.

## [0.8.21] - 2026-07-10

### Added

- `doctor` now reports hook runtime diagnostics: installed hook artifacts,
  current-shell Python import status, the resolved executable/version, and
  whether generated hooks still point at the inspected project root.
- Cursor and Claude Code shell hooks now support `HARNESS_MEM_HOOK_DEBUG=1` so
  import/runtime failures can surface during IDE startup or post-turn execution
  while normal hook runs remain fail-open.

### Fixed

- Unimplemented-host ingest guidance now uses the runtime version instead of a
  hardcoded release number.

## [0.8.20] - 2026-07-09

### Added

- Directory-first project resolution across CLI, MCP ingest/session-distill,
  wake, and host-entry flows; new workspaces can auto-create project profile
  metadata from the current root.
- Real Cursor transcript ingest for
  `~/.cursor/projects/*/agent-transcripts/**/*.jsonl` with project-root
  matching.
- Native Codex rollout ingest for current
  `~/.codex/sessions/**/rollout-*.jsonl` files, filtered by recorded session
  `cwd`.
- `display_name`, `project_root`, and `project_id` metadata on project
  profiles.

### Changed

- `active_project.txt` is now a fallback selector behind explicit
  `project_name`, `project_root`, workspace env, and workspace cwd.
- Host resolution is honest: Cursor and Codex use real adapters; Grok, Hermes,
  OpenCode, and similar host labels no longer silently alias to Claude ingest.
- Wake auto-sync can use project-scoped Cursor and Codex sessions; archived
  Codex imports remain explicit through `codex-archive`.
- Doctor, quickstart, status hints, and MCP responses now report resolved host
  source details and workspace-scoped session counts.

## [0.8.19] - 2026-07-07

### Fixed

- Public smoke CI now installs `PyYAML` before collecting the benchmark tests.
- Native wheel builds enable PyO3 import-library generation so the Windows
  ARM64 release target can cross-compile.

## [0.8.18] - 2026-07-02

### Added

- Regression tests: index-fabric single `_bulk_rows` call per generation, vec0 rebuild
  integration, hybrid KNN integration with `extra_where`, and `batch_cosine_topk`
  `HARNESS_MEM_RUST=required` guard.
- Roadmap scope-lock (`docs/roadmap/v0.8.15-0.8.18-scope-lock.md`), defer table, and PR template.

### Changed

- `maintenance rebuild-vector-index` reports vec0 rows indexed after rebuild.
- Plugin manifest version aligned with runtime `0.8.18`.

## [0.8.17] - 2026-07-02

### Added

- `SqliteVecIndex.rebuild_from_embeddings` and `SQLiteIndex.rebuild_vec0_index` for
  explicit vec0 backfill from `vec_embeddings`.

### Changed

- vec0 lifecycle: upgraded stores can clear HM-204 lag via rebuild or lazy backfill;
  vec0 DDL/KNN/backfill remain in `sqlite_vec_index.py` with `SQLiteIndex` delegating.

## [0.8.16] - 2026-07-02

### Added

- Integration test proving filtered hybrid vector search uses vec0 KNN (batch cosine
  is fallback only when sqlite-vec is unavailable).

### Note

- Product truth (path A): main hybrid search calls `knn_vec_embeddings` with
  `entry_ids` post-filter when vec0 is ready; batch cosine runs only on KNN failure
  or missing sqlite-vec.

## [0.8.15] - 2026-07-02

### Added

- `python -m harness_mem.mcp.tool_descriptor_export` CLI to regenerate
  `mcps/harness_mem/tools/*.json` from `tool_specs`.
- CI step gating MCP export consistency (`tests/test_mcp_exported_tools.py`).

### Changed

- README documents artifact-only `release-wheels` workflow and MCP export command.

## [0.8.14] - 2026-07-02

### Added

- Rust native `fuse_hybrid_rrf` and `batch_cosine_topk` (`harness_mem_core_rs` v4.0.3).
- sqlite-vec `vec0` KNN read path with `entry_ids` post-filter (works with
  `extra_where` on wake/search) and batch-cosine fallback in hybrid search.
- `harness_mem/storage/sqlite_vec_index.py` for vec0 DDL, upsert, KNN, lazy
  backfill, and coverage reporting; `doctor` HM-204 when vec0 lags
  `vec_embeddings`.
- `harness_mem/mcp/tool_descriptor_export.py` plus
  `tests/test_mcp_exported_tools.py` to keep `mcps/harness_mem/tools/*.json`
  aligned with `tool_specs` (seven governance statuses on `list_candidates`).
- `release-wheels.yml` maturin matrix for six platform targets on version tags
  (uploads CI artifacts only — does not publish to PyPI).
- `tests/test_sqlite_vec_index.py`, `tests/test_rust_core_hot_path.py`.

### Changed

- **Build:** single `harness-mem` wheel via maturin (no separate pure/native
  packages). Source installs now require Rust + maturin to compile
  `harness_mem_core_rs`.
- Session parsers and index-fabric postings route through `rust_core.scan_jsonl` /
  `build_bulk_index_rows` (index fabric computes `_bulk_rows` once per generation).
- CI installs the maturin-built wheel before the full pytest suite.
- Hybrid vector scoring splits KNN vs batch-cosine strategies; KNN failures log
  `sqlite3.Error` instead of swallowing all exceptions.
- Upgraded stores without `maintenance rebuild-vector-index` get lazy vec0
  backfill on first KNN query; doctor recommends rebuild for large gaps.

### Note

- Rust hot-path helpers still serialize JSON across the Python/Rust boundary;
  this release does not claim end-to-end zero-copy vector fusion.

## [0.8.13] - 2026-07-02

### Added

- `HARNESS_MEM_RUST` runtime policy (`prefer`, `required`, `force_python`).
- `rust_core.fuse_hybrid_rrf` and `rust_core.batch_cosine_topk` hot-path helpers.
- Maturin config plus CI `maturin develop` native parity smoke.

### Changed

- Hybrid search fusion and vector cosine scoring route through `rust_core`.
- `doctor` distribution block warns on `python_fallback` and errors on
  `HARNESS_MEM_RUST=required` without a native extension.
- Vector read path keeps numpy embeddings in-memory instead of `.tolist()` loops.

## [0.8.12] - 2026-07-02

### Added

- Extended `harness-mem integration install-hook-suite` to grok, codex, hermes,
  and opencode via checked-in templates under `harness_mem/integration/templates/`.
- Added [docs/ide-hook-adapter-matrix.md](docs/ide-hook-adapter-matrix.md)
  documenting per-host hook surfaces and install models.

### Changed

- CLI help and shell completion list all supported hook clients dynamically.

## [0.8.11] - 2026-07-02

### Added

- Doctor reports a count of legacy blobs still using literal `status=accepted`
  (invisible to `readable_truth`; not auto-migrated).
- Added `rank_candidates` native vs Python fallback parity tests.

### Changed

- **Breaking (0.8.x):** removed legacy `accepted` as a governance status and
  read-path alias. Seven layered statuses only; new rows default to `pending`;
  promotes write `auto_confirmed`; confirms write `user_confirmed`.
- Default list/search filter is `readable_truth`; maintenance review candidates
  use a separate status set.
- Updated `docs/auto-promoted-memory-governance.md` and roadmap version line to
  use release semver (`0.8.N`) without `.x` milestone aliases.
- `list_candidates` MCP schema documents layered status use for audit inbox.

## [0.8.10] - 2026-07-02

### Changed

- Synced `plugins/harness-mem` packaging: install scripts, daily command stubs,
  and `version_drift` / `plugin_assets` checks against the runtime package.

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
- `confirm_*` paths now set `user_confirmed` instead of the old `accepted` label.
- `wake` / `search_memory` / `list_memory_entries` use `readable_truth`
  (`auto_confirmed` + `user_confirmed`); `provisional` is opt-in via
  `include_provisional`.
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
