# Changelog

## Unreleased

## [0.9.9] - 2026-08-02

This release includes the reliability and index-integrity work developed as
0.9.7 and 0.9.8; no separate 0.9.7 or 0.9.8 package or tag is published.

### Added

- Added a 60-case, LLM-free retrieval replay suite across single-hop,
  cross-session, temporal, update, preference, no-evidence, and conflict tasks.
  Maintenance reports preserve scored, skipped, and error outcomes separately
  with replayable gold/retrieved IDs and retrieval traces.
- Added bounded distill-job reconciliation after restart or expired chunk
  leases, including last progress, recovery reason/count, retry backoff, and an
  explicit terminal outcome when the recovery budget is exhausted. Direct
  distill claims use the same recovery budget and cannot reclaim an expired
  lease in the same call that records recovery.
- Added generation manifests and failure-injected atomic publication for
  embedding, vec0, and trigram batch rebuilds. Each rebuild uses an isolated
  staging generation, compare-before-publish checks, and stable content hashes;
  FTS and relation postings retain their same-SQLite-transaction update/delete
  contract.
- Added internal context-budget and compaction telemetry without expanding the
  compact MCP response or the exact 27-tool public contract.
- Added native transcript-to-Dream-to-wake qualification for Claude Code,
  Codex, Cursor, Grok, Hermes, OpenCode, and Antigravity, with content-free
  per-stage failure artifacts and explicit host capability rows.
- Added one all-host operator repair path:
  `harness-mem integration hooks sync --client all`.

### Fixed

- Doctor now fails closed when vec0 or exact-index integrity cannot be proven,
  including a missing manifest or same-ID vector/posting corruption. Rebuild
  guidance uses a safe project placeholder rather than interpolating untrusted
  project names into commands.
- Historical `as_of` search now filters Memory, Relation, and Observation
  candidates before storage limits are applied, excludes unversioned Skills,
  and reports the channels actually executed after hybrid fallback.
- Global trigram rebuilds preserve other projects, reject source changes before
  publication, exclude compacted evidence, and restore the prior readable
  generation after injected activation failures or restart.
- OpenCode and Hermes read-only SQLite adapters explicitly close connections,
  preventing locked native databases during Windows cleanup and qualification.
- Retrieval benchmark fixtures reject duplicate YAML keys instead of silently
  accepting an overridden case definition.

### Tests

- Added release gates for seven-host installed-wheel replay on Windows, macOS,
  and Linux. Windows additionally qualifies a real v0.9.6 wheel upgrade,
  migration rollback/retry, legacy restore, Unicode/space paths, and processed
  source cleanup retry before release assets can be published.
- Added a real `sqlite-vec` and NumPy CI/release job so embedding batches,
  virtual-table publication, content fingerprints, and Doctor repair behavior
  cannot pass only through dependency-skipped tests.

## [0.9.6] - 2026-07-30

### Changed

- Converged the MCP runtime to one exact 27-tool contract: schema, cluster,
  handler, exported descriptor, guided-flow hint, and candidate action
  surfaces now agree. The former 17 low-level orchestration schemas are no
  longer registered or exported; `govern_memory` owns their public behavior.
- Replaced six host-specific hook installer commands with
  `harness-mem integration hooks sync --client <host>`, while retaining the
  automatic seven-host bootstrap and one-time user command sync.
- Reduced `harness-mem config list/set` to ten durable policy keys. Existing
  tuning values and legacy JSON remain readable through one merge order:
  legacy JSON, user TOML, then project TOML.
- Removed obsolete Daily-work CLI modules for candidates, handoff, profile,
  search, and status. Daily work continues through the seven host-native
  actions and the stable `wake -> search -> distill -> review -> dream` loop.
- Split the remaining oversized runtime modules without changing their public
  contracts: structured persistence now composes memory, candidate, truth,
  and ledger slices; read-side MCP handling separates query support, search,
  evidence, and wake; Doctor separates classification, read-only probes,
  rendering, and orchestration.
- Removed the retired weak-link experiment recommendation from Doctor and
  routed runtime repair guidance through current public tools only.
- Removed 340 byte-duplicate, stale Router aggregate descriptor files. Live
  `mcp__mcp_router__*` runtime aliases remain supported and canonical
  harness-mem descriptors remain under `mcps/harness_mem/tools/`.
- Deprecated legacy entity JSON readers in 0.9.6 while supporting them through
  0.9.x. Removal is forbidden before both 1.0.0 and 2027-01-31 and still
  requires a shipped converter, clean Doctor verification, and release notice.

### Fixed

- Candidate serializers and Dream review results no longer point Agents at
  hidden confirm/reject tools; they emit complete `govern_memory` actions.
- Claude Code command hints now use `/hm:*`, and all host documentation lists
  the `search-all` action consistently.
- Public schema descriptions no longer expose historical internal feature
  version labels as if they were API versions.
- Legacy-only startup no longer silently changes storage authority. Migration
  preview now covers the same all-project scope as apply; apply writes a
  content-free in-progress/succeeded/failed receipt and rolls back if receipt
  finalization fails.
- Existing canonical SQLite activation now commits into the live file under a
  write-locking transaction, so already-open runtimes cannot keep writing to a
  replaced database. New-database activation is create-if-absent and conflicts
  or concurrent writes fail closed without an apply recommendation.
- The compatibility rollback export now reads current canonical entity tables,
  including rows created after migration, instead of the stale payload table.
- Explicit privacy erase now attempts bounded CAS deletion of safe native host
  session files before removing the internal reference closure. Shared or
  unsafe containers remain untouched and produce an honest partial failure.
- Processed-source cleanup retries now require explicit authorization from the
  persistent delete-after-complete policy.
- Storage migration rollback now compares the activated canonical generation
  before restoring a snapshot, so post-activation concurrent writes are
  preserved and rollback fails closed instead of overwriting them.
- Bash, Zsh, and Fish completion now expose the same maintenance actions and
  privacy-erase selectors; rapid migration retries use collision-free run IDs.

### Tests

- Added registry-equality, public-description, generated-descriptor,
  candidate-action, config-surface, retired-CLI, completion, and documentation
  guardrails so duplicate compatibility surfaces fail before release.

## [0.9.5] - 2026-07-29

This release includes all work originally planned for 0.9.4; no separate
0.9.4 package or tag was published.

### Added

- Persistent `distill.delete_source_after_complete` policy at user or project
  scope. It defaults to `false`; `harness-mem config set ... true` is the
  explicit opt-in for automatic processed-source cleanup.
- One-time `--confirm` protection for the transition that enables automatic
  processed-source deletion. Disabling and per-session finalize need no
  additional confirmation, and IDE natural-language control maps to the same
  existing config surface.
- Per-job `completion_disposition` (`promoted` or `no_candidate`) and
  `source_cleanup_status` (`retained`, `deleted`, `partial_failure`, or
  `unsupported`) outcomes on the existing distill ledger, without a second
  queue or storage system.
- Content-free processed-source receipts written before native deletion, plus
  compare-and-swap, quiet-source, allowed-root, symlink/reparse, residual, and
  WAL/secure-delete checks.
- A shared evidence envelope for new MemoryEntry, RuleCandidate, and
  RelationFact candidates: `evidence_basis`, `verification_outcome`, stable
  reason codes, integrity-only references, and verification time.
- A deterministic evidence-admission golden matrix covering repository,
  explicit user-statement, transcript-only, contradicted, low-confidence,
  relation, and legacy candidate behavior.

### Changed

- `finalize_session_distill` now produces a stable completion, promotion,
  queue-effect, and source-cleanup summary. Automatic policy promotes safe
  durable candidates and terminally rejects the rest, so completed low-value
  sessions do not remain as recurring manual-review work.
- Compact/full project status uses actual distill jobs, including parked work,
  instead of Observation count as the work-queue truth. Seven-day completion
  outcomes distinguish promoted, no-candidate, and legacy-unknown jobs.
- Typed config handling is shared by autopilot, capture, distill, Dream, and
  cost-budget keys, so `config set/get/list` preserve TOML booleans, integers,
  enums, constants, and string lists consistently.
- Existing post-turn maintenance retries a bounded set of cleanup-eligible
  completed jobs after the native source becomes quiet; no second scheduler or
  background semantic worker was introduced.
- Bash, Zsh, and Fish completion now expose the one-time `config set --confirm`
  gate used to enable processed-source deletion.
- Finalize-time Dream admission now revalidates project-relative repository
  digests and exact user-authored semantic windows. Repository/user-statement
  evidence may promote under the existing risk policy; transcript-only,
  malformed, changed, or missing evidence is terminally rejected instead of
  becoming durable truth.
- RelationFact now participates in the same scoped automatic admission pass as
  MemoryEntry and RuleCandidate. Seven-day status and finalize summaries expose
  verified, user-stated, unverified-blocked, and contradicted counts without
  increasing the 27-tool public MCP surface.
- Contradicted candidates create audited stale-truth proposals for exact
  matching current truth; Dream never silently deletes or rewrites it.

### Security

- Processed-source cleanup preserves promoted Memory/Rule/Fact/Skill truth but
  removes native per-session sources, local raw revision bytes, chunks,
  checkpoint results, matching Observations, rejected/linked evidence rows,
  and derived indexes. Retained truth provenance is replaced by a
  content-free `source_pruned` receipt reference.
- Shared-container sources that cannot yet be removed transactionally are
  reported as `unsupported` and remain untouched; harness-mem never unlinks an
  entire shared SQLite or JSONL history file.
- Exact processed-source tombstones prevent an already deleted source revision
  from being silently recaptured while allowing genuinely newer revisions.
- Evidence references reject absolute or outside-project repository paths,
  changed file/source digests, mismatched user roles, and incomplete refs.
  Processed-source cleanup removes transient locators while retaining only
  one-way digests and content-free admission outcomes on durable truth.

## [0.9.3] - 2026-07-26

This release includes all work originally planned for 0.9.2; no separate
0.9.2 package or tag was published.

### Added

- Exact `distill_job_id` claiming for jobs offered by wake. Explicit claims
  remain project-scoped and cannot bypass the active lane, parked/terminal
  state, daily budget, or retry backoff.
- A read-only Doctor recovery planner that classifies findings as
  `safe_rebuild`, `snapshot_required`, `manual_review`, or `destructive`, with
  separate preview/apply commands and no automatic apply path.
- Content-free hard-delete receipts with `in_progress`, `succeeded`, `skipped`,
  and `partial_failure` states, planned/actual artifact counts, and post-delete
  verification across transcript revisions, chunks, jobs, Observations,
  candidates, truth, and derived indexes.
- A project-isolated seven-day retrieval-quality scorecard covering surfaced,
  used, ignored, misleading, abstained, historical/stale excluded, conflict
  excluded, and insufficient-feedback counts.
- Distill backlog diagnostics for budget exhaustion, retry backoff, active-lane
  waiting, zero Agent throughput, oldest parked work, and a conservative drain
  estimate that never claims background semantic processing.
- A documented compatibility inventory with explicit keep/remove criteria for
  internal aliases, legacy readers, migration paths, and frozen Router
  snapshots.

### Changed

- Split the former 3,330-line MCP handler module into bounded read, status,
  dream, distill, and governance capability modules while retaining the facade,
  dependency injection, compatibility re-exports, and exact 27-tool public
  surface.
- Compact project status now keeps decision-critical quality/backlog counters
  within its token budget; full status remains the drilldown surface for raw
  diagnostics.
- Retrieval abstention and temporal exclusion are recorded only as bounded
  `RetrievalSignal` shadow evidence. They never become durable truth, and
  missing outcome feedback is not scored as negative feedback.
- Current-only MCP search records bounded aggregate exclusion evidence when
  matching historical truth is intentionally withheld; temporal-query conflict
  and historical emitters are covered end to end.
- Healthy canonical stores with newer rows are classified as expected growth;
  actual content conflicts, invalid legacy data, and corruption still fail
  closed and require explicit recovery.

### Fixed

- Search-tool results again emit project-scoped `search_hit` evidence after the
  task-aware retrieval refactor, so quality reporting reflects the public MCP
  mainline rather than only compatibility reads.
- Storage v2 migration tests now verify snapshot contents, staging failure
  isolation, mid-transaction rollback, restart recovery, and preservation of
  newer canonical rows. Global canonical activation now imports every project,
  and a live-store fingerprint aborts activation if a concurrent canonical
  writer changes the active database after staging begins.
- Hard-delete apply refuses to start if its durable receipt cannot be written,
  reports partial failures without copying private content or raw identifiers,
  and verifies every planned local artifact after deletion. Lifecycle reads no
  longer omit compacted or high-volume Observations; erasure follows explicit
  candidate, truth, retrieval-signal, metabolism, and dream-run references to a
  fixed point, rechecks the original selector after deletion, and persists
  hashed session/source tombstones that prevent automatic recapture.
- Core hard-delete calls reject implicit project-wide erasure, and no-match
  receipt-finalization failures remain explicit instead of leaving an
  `in_progress` audit row while reporting success.
- Doctor now fails closed for corruption, invalid legacy payloads, and content
  conflicts even when index drift is also present; no apply command is exposed
  until authority is unambiguous.
- The split MCP capability modules can be imported independently without a
  facade cycle, and backlog drain estimates include the latest retry backoff
  instead of understating calendar time.

## [0.9.1] - 2026-07-18

### Added

- Public-contract guardrails reject retired per-kind governance tool names in
  active Skills, Daily commands, generated host copies, and current docs.

### Changed

- Every active memory-write instruction now uses the single public
  `govern_memory` boundary for suggestion, review decisions, handoff, correction,
  and supersede operations.
- The roadmap, maturity snapshot, install examples, and seven generated host
  command sets now describe the 0.9.x product line and 0.9.1 package truth.
- The deferred-work page is now the current scope ledger; historical 0.8.x
  planning documents remain explicitly historical instead of masquerading as
  current worktree state.

### Removed

- Unreferenced duplicate documents under `docs/internal/`; the canonical
  roadmap, memory-adoption, and retrieval-research pages remain under `docs/`.

### Fixed

- Restored separate 0.8.25 and 0.9.0 changelog histories after the 0.9.0 merge
  had accidentally placed 0.9.0 changes under the 0.8.25 heading.

## [0.9.0] - 2026-07-18

### Added

- Compact/full MCP response views with decision-fingerprint parity. Project
  status stays below the 1.2k-token budget and distill uses a ≤3k-token indexed
  manifest followed by semantic-window and raw-proof drilldown.
- Agent-active parked draining with a two-job active lane, 3:1 recent/oldest
  fairness, daily new-job budget, exponential failure backoff, and throughput
  metrics. Runtime reports `waiting_for_agent` when no model can perform review.
- Atomic Storage v2 migration with pre-migration backup, staging validation,
  integrity checks, atomic activation, runtime-state-last switching, and
  automatic restoration after activation failure.
- Project capture policy, private/capture-ignore handling, transcript retention,
  and preview-first hard deletion across raw revisions, chunks, Observations,
  candidates, truth, and derived indexes.
- User-global native Daily commands for Claude Code, Cursor, Grok, Codex,
  Hermes, OpenCode, and Antigravity, plus cross-host transcript-to-wake tests.
- Sixty retrieval-isolated benchmark cases and 1k/10k scale coverage.
- Explicit dry-run `maintenance migrate-legacy-accepted` governance migration.
  Rows move only to pending review or historical/superseded state and retain
  audit/undo metadata; the migration never confirms truth.

### Changed

- Vector maintenance now reuses one model instance, encodes batches of 32 by
  default, stages and validates rows before a transactional switch, reports once
  per batch, and rebuilds vec0 with a batch write. Default pytest runs block real
  model loading unless a test is marked `embedding_integration`.
- Doctor explains Storage v2 checksum relationships as `exact_match`,
  `canonical_superset_expected`, `legacy_missing_in_canonical`,
  `content_conflict`, or `invalid_legacy`; canonical-only current data is no
  longer presented as checksum corruption.
- MCP governance writes are consolidated behind `govern_memory`; the exported
  public descriptor surface contains 27 tools while full diagnostic drilldown
  remains available.

### Fixed

- Retention of an old transcript revision no longer deletes candidates that
  belong to a newer retained revision of the same session.
- Project-scoped vector rebuilds no longer clear embeddings owned by other
  projects in the shared derived index.
- Compact distill preserves evidence anchors consistently with or without the
  optional tokenizer, and host-command tests now follow platform-native Hermes
  paths.

## [0.8.25] - 2026-07-16

### Added

- Project-scoped MCP status bootstrap now adopts the workspace and installs the
  matching generated Hook suite for all seven recognized hosts without asking
  users to run a hook installer.

### Fixed

- Codex Hook health no longer treats a present `.codex/hooks.json` as proof
  that automatic wake works. Status reports `review_required` until Codex has
  trusted and successfully run the current `SessionStart` definition, using a
  configuration-bound execution receipt that becomes stale when hooks change.
- Hook doctor diagnostics now evaluate complete suites only for hosts that
  actually contain harness-mem Hook commands. Optional artifacts for other
  IDEs, and a Hermes config containing only MCP settings, no longer produce a
  false `repair needed` result.
- Hook startup no longer rewrites every existing observation trigram index on
  each process launch. Stop maintenance also defers transcript embedding model
  loading and limits each interactive pass to one changed session while the
  durable scan frontier continues historical backfill across later turns.
- IDE post-turn hooks now persist and coalesce maintenance requests behind one
  detached worker per project and host, so synchronous Hook surfaces return
  promptly without dropping a request that arrives during a running sync.
  Hermes and Antigravity pre-hooks also inject wake only once when their native
  payload supplies a stable session or conversation ID.

## [0.8.24] - 2026-07-15

### Added

- A lossless transcript ledger that preserves exact native bytes, immutable
  source revisions, normalized SHA-256 metadata, and complete ordered chunks.
- Resumable distill jobs with per-chunk leases and checkpoints, revision-aware
  stale-job handling, required final-session semantic review, and explicit
  `submit_distill_chunk` / `finalize_session_distill` MCP operations.
- Revision-aware transcript capture for Cursor, Claude Code, Codex, Grok,
  Hermes, OpenCode, and Antigravity. Current and archived Codex sessions remain
  distinct sources under the same host family.
- Upstream-aligned Hermes `state.db` and Antigravity CLI `history.jsonl` source
  variants, each exported per session with project-isolation and growth tests.
- Distill diagnostics for source coverage, revision state, expected/completed
  chunks, and queued or processing lossless jobs.

### Changed

- Long sessions are processed from beginning to end without transcript or
  chunk truncation. Bounded Agent calls claim complete chunks and resume from
  durable checkpoints instead of dropping the unread tail.
- Appended host sessions create new source revisions and new idempotent jobs;
  unchanged recent sessions no longer starve older historical backlog scans.
- Transcript Observations are explicitly derived search projections. Exact
  source revisions in the transcript ledger are the authoritative session
  evidence and remain reconstructable independently of search indexes.
- Candidate suggestions accept a distill job identity and derive stable IDs,
  so retries do not duplicate memory, rule, or relation candidates.
- `finalize_session_distill` verifies current revision and complete chunk
  coverage before applying auto-review and running Dream.
- Generated hooks bind the exact installed `harness-mem-hook` executable and
  automatically upgrade legacy managed hooks instead of relying on a bare
  `python` selected from an IDE's `PATH`.
- Transcript source persistence and distill job persistence now have separate
  storage components while sharing one transactional SQLite ledger.
- Removed the repo-local `tools/session-distill/lib` and
  `bin/session-distill.py` duplicate implementation after porting its useful
  lossless, isolation, review-gate, and idempotency coverage to `harness_mem`.
  `/hm:distill`, the instruction-only skill, and MCP
  `prepare` / `submit` / `finalize` operations are the only lifecycle.

### Fixed

- Growing sessions are no longer skipped merely because their `session_id` was
  seen before.
- Hook preparation is no longer described as completed summarization; hooks
  capture and queue evidence, while an Agent performs semantic distillation.
- Legacy completion no longer marks every processing job in a project complete;
  it targets one explicit job or the sole unambiguous processing job.
- `finalize_session_distill` now verifies revision currency and complete chunk
  coverage before auto-review can mutate candidate state.
- Final semantic review now blocks promotion and Dream for partial, blocked,
  contradicted, unfinished, or explicit no-promotion outcomes. Auto-review is
  restricted to candidates produced by the finalized job.
- The canonical transcript ledger retains raw revisions, uses SHA-256 identity,
  and processes every turn, assistant block, and tool call without head/tail or
  character cuts; no repo-local packet/manifest path remains.
- Distill candidate IDs now use source revision, pipeline version, project,
  candidate kind, and a normalized semantic claim, so whitespace and unordered
  collection differences do not create duplicate candidates.
- Seven host adapters now carry explicit project-isolation negative tests, and
  release smoke checks a fixed transcript hash vector on Windows, macOS, and
  Linux.

## [0.8.23.4] - 2026-07-14

### Added

- `harness-mem-mcp`, an installed MCP server command that always launches from
  the same Python environment as the installed package.

### Changed

- Cursor and generic MCP setup now use `harness-mem-mcp` instead of a bare
  `python -m ...` command. This prevents multi-Python installations from
  silently starting an environment without `harness-mem`.
- Minimal installations now emit one concise fallback warning when optional
  `tiktoken` is unavailable instead of printing an import traceback.

## [0.8.23.3] - 2026-07-13

### Changed

- GitHub Releases are now the canonical package channel. Release tags still
  build and smoke-test six native wheels plus the source distribution, but no
  longer require a PyPI account, Trusted Publisher, OIDC token, or publish job.
- Installation docs now use pip's `--find-links` support to select the matching
  native wheel directly from the versioned GitHub Release assets.
- PyPI-only Trusted Publishing configuration and the Twine development
  dependency have been removed.

## [0.8.23.2] - 2026-07-13

### Fixed

- GitHub Release attachment now receives an explicit repository identity in
  the checkout-free PyPI publish job.

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
