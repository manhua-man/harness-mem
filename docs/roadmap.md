# Roadmap

`harness-mem` 0.9.x is the convergence line for one automatic, auditable
Agent-memory loop. 0.9.0 shipped the automation, storage-safety, and
cross-host runtime baseline; 0.9.1 removed stale product vocabulary and locked
the public governance contract. Version 0.9.3 shipped the complete 0.9.2 handler
and deterministic-distill work together with explainable recovery and quality
operations. Version 0.9.5 shipped the completed-session/source-cleanup work
originally planned for 0.9.4 together with evidence-grounded Dream admission,
without adding another public tool, store, or scheduler. Version 0.9.6 removes
duplicate compatibility surfaces while keeping stored data readable and the
27-tool contract unchanged. Version 0.9.9 ships the retrieval/lifecycle,
derived-index, and seven-host qualification work developed as 0.9.7-0.9.9.
The incremental context-lineage work planned as 0.9.10 ships in 0.9.11 together
with honest complete-response budgets, bounded Agent batches, a content-free
captured-to-feedback funnel, and fail-closed distill admission.
Version 0.9.12 adds opt-in detached semantic execution with outcome-bound
runtime receipts, current-Stop priority, immutable revision Notes, and a
deterministic 24-path distill acceptance suite.
No separate 0.9.2, 0.9.4, 0.9.7, 0.9.8, or 0.9.10 package or tag was published. The
stable loop is
not a manual checklist:

```text
wake -> search -> distill -> review -> dream
```

`wake`, task-aware `search`, `distill`, `review`, and `dream` are the software
loop: hooks and Agent policy decide when to call them. Users can still invoke
`/hm:*` commands, but the commands are control and fallback surfaces.
`review` is the audit inbox for auto-promoted, provisional, deferred,
rejected, and supersede items; it is not the everyday write gate. `dream` is
the default audited maintenance side path and must keep undoable audit records
when durable truth changes.

See [maturity-model.md](maturity-model.md) for the release/readiness evidence
model. The current Canvas separates release maturity from live operations:
`canvases/harness-mem-readiness-0-9-10.canvas.tsx`.

## Current Version Line

Roadmap versions are release semver. The current package truth comes from
`pyproject.toml`; historical 0.8.x sections below remain shipped design records,
not pending work.

| Version | Goal | Ships when | Does not include |
|---|---|---|---|
| `0.9.0` | Automatic, safe, cross-host runtime baseline. | Compact MCP responses, two-stage distill, bounded Agent-active draining, Storage v2 recovery, privacy lifecycle, batch vectors, and seven-host commands are verified end to end. | A second truth store, background semantic claims without an Agent, or a broader public MCP surface. |
| `0.9.1` | Public-contract and narrative convergence. | Every active Skill/command uses `govern_memory`; generated host copies agree; 0.9.x docs and release history are canonical; guardrail tests reject removed governance vocabulary. | Broad handler refactors, new tools, or new configuration profiles. |
| `0.9.2` | Folded into 0.9.3; not published separately. | Exact offered-job claiming and the bounded handler split ship in the 0.9.3 package and tag. | A separate 0.9.2 release artifact. |
| `0.9.3` | Explainable recovery and memory-quality operations, including all 0.9.2 work. | Doctor emits a risk-classified recovery plan, Storage v2 drift is explained with replay-tested recovery, privacy deletion has verifiable receipts, and status reports outcome-based retrieval quality rather than latency alone. | A second store, automatic destructive repair, new persistence roots, or autonomous semantic claims without an Agent. |
| `0.9.4` | Folded into 0.9.5; not published separately. | Terminal distill outcomes and processed-source cleanup ship in the 0.9.5 package and tag. | A separate 0.9.4 release artifact. |
| `0.9.5` | Terminal completion, opt-in processed-source cleanup, and evidence-grounded Dream admission. | Completed jobs are terminal and auditable; authorized cleanup is verified and truth-preserving; new candidates carry an evidence basis/outcome; repository claims need current repository proof; explicit user decisions can promote; contradicted claims route through historical governance. | A new MCP tool, manual daily promotion, generic web fact-checking, a second truth store/scheduler, silent deletion, whole shared-container deletion, or retroactive reclassification of legacy truth. |
| `0.9.6` | Runtime, operator-surface, and compatibility-lifecycle convergence. | MCP registries contain exactly the same 27 public tools; hook/config each have one path; stale Router snapshots are removed; legacy storage stays readable behind an explicit support cutoff and receipt-first migration; privacy erase covers safe native sources. | A new public tool/scheduler, silent data authority change, immediate removal of legacy readers, or unsafe deletion of shared native containers. |
| `0.9.7` | Folded into 0.9.9; not published separately. | Deterministic long-session fixtures, explicit skipped/error outcomes, bounded job recovery, and no false healthy state after lease or restart failures ship in 0.9.9. | A separate 0.9.7 release artifact. |
| `0.9.8` | Folded into 0.9.9; not published separately. | Staged batch-index generations, transactional incremental indexes, Doctor source/index verification, and compact budget/compaction telemetry ship in 0.9.9. | A separate 0.9.8 release artifact. |
| `0.9.9` | Retrieval, index, seven-host, and compatibility qualification. | Native adapter capture through Dream and wake is replay-tested on all supported hosts; recovery/index failures fail closed; fresh install, upgrade, legacy restore, and operator repair paths are qualified. | A new MCP profile, silent native-container deletion, removing legacy readers before the support cutoff, or adding an autonomous semantic worker. |
| `0.9.10` | Incremental context lineage and evidence-safe projection. | Hash-verified appended revisions reuse prior semantic work; tool/result boundaries remain intact; context receipts report real budget outcomes and token basis. | A Pi SessionManager, second truth store, Pi host adapter, fixed model budgets, or treating summaries as durable truth. |
| `0.9.11` | Effective memory closure. | Complete MCP responses report actual serialized cost; automatic wake can process two isolated jobs and explicit distill up to three; status exposes distinct-job and explicit-feedback funnels without storing content. | A fixed 3k cap, sequential first-N clipping, background semantic workers, another store/tool, or inferred positive feedback. |
| `0.9.12` | Outcome-verified autonomous distill. | An explicitly authorized isolated provider can turn the current native Stop into a completed job, immutable Note, and retrievable truth with bound receipts; F1-F7 fixtures exercise all 24 acceptance paths. | Enabling provider use without consent, trusting queued/completed flags without artifacts, or letting historical backlog displace the current Stop. |

## 0.9.12 - Outcome-Verified Autonomous Distill

This iteration makes the opt-in autonomous path a measurable user outcome. A
native Stop is bound to one ingested session and prioritized job; the isolated
provider returns strict review data while trusted runtime code owns governance,
finalization, immutable Notes, and health receipts. The release contract proves
Hook to Job to Note to Retrieval rather than treating configuration, queues, or
unit tests as completion.

## 0.9.11 - Effective Memory Closure

This iteration treats `3000` as a compatibility default, not a product
invariant. The compact manifest keeps every exchange indexed and measures the
complete JSON the Agent receives. Bounded batching improves freshness without
changing per-job leases/finalization, while status distinguishes explicit
`used` / `ignored` / `misleading` outcomes from `missing_feedback`.

The detailed design and acceptance gates are in
[0.9.11-effective-memory-closure.md](roadmap/0.9.11-effective-memory-closure.md).

## 0.9.10 - Incremental Context Lineage

This release reduces repeated work on growing transcripts while strengthening
semantic boundary and context-budget evidence. It adds no public command, MCP
tool, configuration key, persistence root, or autonomous semantic worker.

The detailed design, acceptance gates, and Pi adoption boundary are in
[0.9.10-context-lineage.md](roadmap/0.9.10-context-lineage.md).

## 0.9.6 — Runtime and Operator-Surface Convergence

Goal: make the installed product match its declared surface, with guardrails
that prevent compatibility helpers from leaking back into user workflows.

- Register schemas, clusters, handlers, descriptors, hints, and candidate
  actions against the same exact 27-tool allowlist.
- Route every candidate decision and handoff through `govern_memory`; keep the
  lower-level functions private to its implementation.
- Replace six host-specific hook installer commands with one operator repair
  path: `harness-mem integration hooks sync --client <host>`.
- Keep only ten public policy keys in `config list/set`; continue reading old
  tuning values through one JSON/TOML/project merge path.
- Remove obsolete Daily-work CLI modules and the Doctor weak-link experiment
  recommendation, while preserving the seven host-native Daily actions.
- Deprecate legacy entity JSON in 0.9.6, support it through 0.9.x, and forbid
  reader removal before both 1.0.0 and 2027-01-31. Existing legacy-only stores
  stay on fallback until an operator previews and explicitly applies the
  all-project, receipt-first migration.
- Remove the two stale Router aggregate snapshot directories while preserving
  live `mcp__mcp_router__*` discovery.
- Keep processed-source cleanup truth-preserving and privacy erase
  truth-removing; explicit erase additionally deletes safe native session files
  and reports partial failure for shared/unsafe containers.
- Lock the boundary with registry-driven contract, CLI, config, descriptor,
  and documentation tests before full package and fresh-install verification.

## 0.9.7-0.9.9 delivery

These three evidence-driven hardening waves ship together in 0.9.9 rather than
replaying features already delivered in 0.9.0-0.9.6. Each wave keeps its
separate execution record:

- [0.9.7 - retrieval quality and lifecycle](roadmap/0.9.7-retrieval-lifecycle.md)
- [0.9.8 - index integrity and context budgets](roadmap/0.9.8-index-context.md)
- [0.9.9 - host replay and compatibility](roadmap/0.9.9-host-compatibility.md)

The implementation order was strict: 0.9.7 establishes trustworthy fixtures and
recovery evidence; 0.9.8 consumes those fixtures to harden derived indexes and
budget telemetry; 0.9.9 uses both as the qualification matrix for real host
transcripts. The combined release does not expand the public MCP contract.

## 0.9.4 — Terminal Completion and Source Cleanup (shipped in 0.9.5)

Goal: make “this session is done” unambiguous while preserving the default
local audit trail.

- Store completion disposition and actual source-cleanup status on the existing
  distill job JSON; legacy jobs remain outcome-unknown.
- Automatically promote safe candidates and reject the rest, leaving review as
  a post-hoc correction and undo surface.
- Add the default-off `distill.delete_source_after_complete` user/project
  policy and use existing post-turn maintenance for bounded quiet-source retry.
- Delete supported per-session native sources and active harness raw evidence
  only after a content-free receipt, CAS/quiet/root checks, and full residual
  verification. Preserve sanitized long-term truth.
- Keep shared containers untouched when a safe transactional session delete is
  unavailable, and report `unsupported` instead of overstating deletion.
- Base compact/full status on the real distill queue, including parked jobs and
  seven-day promoted/no-candidate/legacy-unknown completion outcomes.

The work is folded into the 0.9.5 package and tag. CLI-surface parity is part
of that combined release: Bash, Zsh, and Fish completion all expose the
one-time `--confirm` option required to turn the persistent deletion policy on.

## 0.9.5 — Evidence-Grounded Dream Admission (shipped)

Goal: make automatic promotion depend on a verified evidence envelope rather
than confidence and a non-empty source id, while keeping review post-hoc and
preserving the existing 27-tool MCP contract.

The detailed architecture, policy matrix, migration rules, execution slices,
and acceptance gates are in
[v0.9.5-evidence-grounded-dream.md](roadmap/v0.9.5-evidence-grounded-dream.md).

## 0.9.2 — Deterministic Distill and MCP Implementation Convergence (shipped in 0.9.3)

Goal: make unattended distill execution deterministic while making the MCP
runtime maintainable.

Functional iteration:

- Add optional `distill_job_id` targeting to the existing
  `prepare_session_distill` tool so the bounded jobs offered by wake are the
  jobs actually processed.
- Render selected IDs in automatic maintenance instructions and require Agents
  to process them one at a time. A failed job can be deferred without changing
  the identity of the next selected job.
- Reject cross-project, parked, completed, stale, or retry-backoff targets with
  explicit status/retry metadata. Explicit targeting must not bypass fairness,
  daily budget, or backoff policy.
- Keep semantic compact mode, raw proof drilldown, candidate idempotency, final
  semantic review, auto-review, and Dream as one resumable per-job lifecycle.

Internal convergence:

- Keep `tool_handlers.py` as the dependency-binding and registry facade.
- Keep `read_handlers.py` as a compatibility facade; own query interpretation
  in `read_query_support.py`, retrieval calls in `read_search_handlers.py`,
  evidence reads in `read_evidence_handlers.py`, and wake orchestration in
  `read_wake_handlers.py`. Project/runtime status remains in
  `status_handlers.py`; audited maintenance in `dream_handlers.py`; lossless
  session processing in `distill_handlers.py`; durable governance writes in
  `governance_handlers.py`.
- Preserve compatibility re-exports used by tests and older internal imports,
  but do not add them to the public MCP allowlist.
- Lock the exact 27-tool public surface. The only additive 0.9.2 schema change
  is optional `prepare_session_distill.distill_job_id`; compact/full defaults,
  the review gate, Dream audit/undo behavior, and internal-only status of
  `set_active_project` and `ingest_sessions` remain unchanged.

Acceptance:

- `tool_handlers.py` stays below 900 lines and contains none of the five
  capability bodies.
- Handler-boundary and public-surface contract tests pass, followed by the
  complete Python, Ruff, Mypy, Rust, and package-build gates.
- Existing compact/full decision fingerprints and lossless distill lifecycle
  tests pass without fixture rewrites.
- A two-job test proves exact selection can process the older offered job even
  when queue policy would otherwise choose the newer one; deferred jobs expose
  `retry_after` and cannot be reclaimed early.

## 0.9.3 — Explainable Recovery and Memory-Quality Operations (shipped)

Goal: give users one trustworthy operational view for recovery, privacy, and
whether retrieved memory is actually helping.

Functional iteration:

- Add a structured Doctor recovery plan with `safe_rebuild`,
  `snapshot_required`, `manual_review`, and `destructive` risk classes.
  The plan names exact preview/apply commands; nothing destructive auto-runs.
- Add a privacy lifecycle report and durable deletion receipt containing the
  affected revision/chunk/Observation/candidate/index counts and post-delete
  verification result, without retaining deleted private content.
- Extend full project status with a seven-day memory-quality scorecard:
  surfaced, used, ignored, misleading, abstained, stale/conflict excluded, and
  insufficient-feedback counts. Ranking influence remains bounded and
  explainable.
- Surface stuck distill reasons, oldest parked age, effective throughput, and a
  coarse drain estimate so users can distinguish healthy parked history from a
  stalled queue.

Internal convergence:

- Split Doctor into bounded `doctor_probes.py`, `doctor_classification.py`,
  `doctor_rendering.py`, and the `doctor.py` command orchestrator. Explicit
  remediation remains in `doctor_recovery.py`; probes stay read-only unless
  the user selects a documented repair command.
- Classify canonical/legacy checksum differences as expected growth, actionable
  drift, or corruption using row counts, revision lineage, and migration state
  instead of presenting every mismatch as the same warning.
- Add migration failure-injection tests covering pre-migration snapshot,
  transaction rollback, restart recovery, and preservation of newer canonical
  rows.
- Inventory internal compatibility aliases and legacy readers, attach a
  keep/remove criterion to each, and remove only paths proven unused by host,
  CLI, MCP, migration, and rollback tests.

Acceptance:

- A healthy canonical store with newer rows produces an informational,
  explained result rather than a maintenance warning.
- Real divergent or corrupt fixtures still fail closed with a concrete recovery
  path; no Doctor action silently deletes or overwrites data.
- Doctor/storage boundary tests, migration replay tests, seven-host smoke tests,
  and the full release gate pass.
- Retrieval scorecard fixtures prove project isolation and distinguish no
  feedback from poor feedback; deletion receipts prove every planned local
  artifact was removed without copying raw private content into the receipt.

Explicit non-goals for both releases: no public MCP expansion, no new MCP
profile, no second truth store, no new configuration switch, no new persistence
path, no automatic destructive action, and no quality claim that bypasses
retrieval-isolated evaluation.

### Historical 0.8.x release line

| `0.8.3` | Retrieval Quality Foundation. | LLM-free golden suite covers stale truth exclusion, project leak, abstention, and vector-off fallback. | New MCP tools, wiki, search-engine swap, broad quality claims. |
| `0.8.4`–`0.8.7` | Trust, retrieval, maintenance, adoption (shipped patch range). | Contract tests, golden suite, dream/review closure, grill/adoption skills. | Second truth store, wiki-as-truth, graph DB default. |
| `0.8.8` | Auto-promoted governance. | Low-risk candidates auto-promote to trust-tiered memory; `/hm:review` is post-hoc audit. | Manual-only review gate, hidden truth mutation. |
| `0.8.9` | Runtime autopilot search. | `autopilot_search_tick` task-aware search scheduler; bounded triggers only. | Always-on broad search, hook lock-in without discipline. |
| `0.8.10` | Plugin packaging sync. | `plugins/harness-mem` install path, drift checks, and daily command metadata stay aligned with runtime version. | Memory semantics changes. |
| `0.8.11` | Governance compat removal. | Remove legacy `accepted` read alias; wire seven layered statuses end-to-end; doctor legacy scan; Rust/Python rank parity. | Completed in 0.9.0 with explicit dry-run governance migration. |
| `0.8.12` | IDE hook adapters. | Checked-in host templates installed by project-scoped MCP bootstrap for cursor, claude-code, grok, codex, hermes, opencode. | Per-host hook invention at runtime. |
| Later / Labs | Optional acceleration and experiments. | Benchmarks prove the Python/SQLite default has a real bottleneck or quality ceiling. | Default runtime narrative or public surface expansion. |

## 0.8.4.x — Trust Hardening

- Make `current` truth the default read path and keep historical truth visible
  only through `include_history` / `deep_recall`.
- Keep `recall.steps` stable:

```text
filter -> fts -> vector -> merge -> hydrate -> context
```

- Keep score explanation additive through existing metadata:
  `fts_score`, `vector_score`, `rrf_score`, `boosts`, `confidence_tier`.
- Add regression coverage for stale truth exclusion, history opt-in,
  cross-project leak rate, abstention, and vector-off fallback.

Status: complete for the 0.8.x convergence line. Current reads exclude
`valid_to` historical truth and non-empty `superseded_by` truth, while
`include_history` / `deep_recall` remain the explicit opt-ins. Contract tests
lock `recall.steps`, temporal query abstention/conflict, MCP `deep_recall`, and
supersede audit lineage.

## 0.8.5.x — Retrieval Quality

- Strengthen filter-first ranking: project, scope, status, temporal validity,
  and supersession are hard filters before ranking.
- Evaluate adaptive IDF/RRF only through golden-suite A/B.
- Add low-confidence abstention so weak retrieval returns `partial` or empty
  instead of fabricating confidence.
- Add a lightweight 1-hop relation/decision boost without introducing a graph
  database or new public surface.

Status: complete for the local SQLite default. Filter-first search keeps
project, status, temporal, and supersession predicates ahead of ranking;
weak multi-token partial matches are filtered with
`retrieval_quality.abstention`; decision entries can receive an explainable
1-hop relation boost; and adaptive IDF/RRF work is gated by the LLM-free golden
A/B report instead of changing defaults.

## 0.8.6.x — Maintenance Closure

- Let dream emit supersede candidates, never silent truth rewrites.
- Keep state audit ledger and undo metadata as the durable-change boundary.
- Add optional `why_it_matters` / action hints for wake summaries when they help
  the user act on confirmed truth.

Status: complete for the public surface. Dream records supersede candidates as
`pending_review` ledger items and leaves truth lineage unchanged until explicit
`govern_memory(action="supersede")`; wake snapshots expose optional
structured action hints; and public MCP tools are exact-allowlisted to preserve
the single memory surface.

## 0.8.7.x — Candidate Admission

- Keep candidate admission inside `hm-distill`: one inline pass for ordinary
  candidates and evidence-first review for high-impact rules or architecture.
- Ask the user only when preference, intent, or product direction cannot be
  resolved from the transcript, repository, tests, or current documentation.
- Use `admit`, `narrow`, `defer`, and `reject` as internal outcomes before
  `govern_memory(action="suggest")`.

Status: complete. The admission policy is part of the single distill flow and
does not add helper products, question routers, or a second runtime harness.

## 0.8.8 — Auto-Promoted Governance

- Keep the public loop named `wake -> search -> distill -> review -> dream`,
  but define it as automatic runtime behavior.
- Use `/hm:review` as the audit inbox: user confirmation upgrades trust,
  rejection/undo removes bad auto-promotions, and supersede lineage stays
  visible.
- Keep `auto_review_candidates(apply=true)` as the low-risk promotion path with
  audit metadata.

## 0.8.9 — Runtime Autopilot Search

- Install or generate client-specific integrations from a shared event model:
  session start, context transform, tool result, save point, and session end.
- Use `wake` once per session/project activation unless the project or branch
  changes.
- Use `autopilot_search_tick` at context/tool/save-point events; it calls
  `search_memory` only when a trigger fires: explicit user recall request,
  uncertain project convention, conflict with current context, tool failure
  that resembles a prior issue, file/module boundary question, or pre-write
  claim that must be grounded.
- At save points or session end, sync evidence and queue a durable distill task.
  An Agent-capable invocation consumes the complete evidence view, creates candidates, applies
  auto-review, then runs Dream. Keep high-risk, conflicting, or weak-evidence
  items out of normal wake/search until audit.

See [autopilot-search-policy.md](autopilot-search-policy.md) for the runtime contract.

## 0.8.10 — Plugin Packaging Sync

- Keep `plugins/harness-mem` version, wire, install scripts, and daily command
  stubs aligned with the runtime package.
- Surface install drift through `version_drift` / doctor-friendly checks.

## 0.8.11 — Governance Compat Removal

- Drop legacy `accepted` as a readable-truth alias; use `readable_truth`
  (`auto_confirmed` + `user_confirmed`) on read paths.
- Report legacy `status=accepted` counts in doctor; 0.9.0 adds an explicit dry-run migration that moves rows only to pending review or historical state, never truth.
- Lock native vs Python `rank_candidates` parity; clarify `list_candidates`
  layered status semantics in MCP schema.

## 0.8.12 — IDE Hook Adapters

- Ship checked-in templates under `harness_mem/integration/templates/`.
- Extend automatic project-scoped MCP bootstrap beyond cursor/claude-code.
- Document per-host adapter shape in [ide-hook-adapter-matrix.md](ide-hook-adapter-matrix.md).

## Later / Labs

These are not roadmap promises. They are gated experiments:

- **Optional Rust acceleration**: move hot loops such as RRF fusion, bulk index
  rebuilds, or benchmark runners into Rust only if Python becomes a measured
  bottleneck.
- **Embedding tuning**: tune or mine embeddings for harness-mem's own project
  memory distribution only if retrieval-isolated benchmarks show vector quality
  is the bottleneck.
- **Tantivy / LanceDB**: test specialized search/vector stores only if SQLite
  FTS / sqlite-vec cannot meet measured latency or quality targets.
- **Graph-native search**: keep as a lab path for richer temporal relation
  traversal. Do not make it the default truth or retrieval engine unless the
  simple 1-hop boost stops being enough under benchmarks.
- **Admission/evidence enforcement**: keep it in the existing Skill and
  `govern_memory` contract; do not add helper products or a second runtime harness.

## Stable Boundaries

- No wiki bridge / knowledge-cache as truth.
- No multi-profile MCP public surface.
- No standalone metabolism/reflection product surface.
- No unaudited durable write; auto-promoted writes must carry evidence, status,
  policy reason, and undo metadata.
- No retrieval-quality claim without retrieval-isolated tests.
- No parallel journal, spec, or external-evidence truth store inside harness-mem.
