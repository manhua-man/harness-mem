# Roadmap

`harness-mem` stays on the 0.8.x line for convergence, trust hardening,
retrieval-quality proof, and operator playbook layers. The stable product loop
is an automatic Agent/runtime loop, not a manual checklist:

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

## Version Line

| Version line | Goal | Ships when | Does not include |
|---|---|---|---|
| `0.8.3` | Retrieval Quality Foundation. | LLM-free golden suite covers stale truth exclusion, project leak, abstention, and vector-off fallback. | New MCP tools, wiki, search-engine swap, broad quality claims. |
| `0.8.4.x` | Trust hardening. | Superseded/current behavior is locked by contract tests; recall explain output is stable and backward compatible. | New MCP tools, wiki-as-truth, graph-native default. |
| `0.8.5.x` | Retrieval quality. | Filter-first hybrid ranking, adaptive RRF A/B, and low-confidence abstention improve the golden suite without breaking vector-off fallback. | ColBERT, graph DB, Tantivy/LanceDB default, benchmark leaderboard claims. |
| `0.8.6.x` | Maintenance closure. | Dream can produce supersede candidates through review; wake/action hints can use optional `why_it_matters` without schema pressure. | Silent truth mutation, standalone metabolism, wiki-as-truth. |
| `0.8.7.x` | Memory adoption playbook. | Risk-scaled grill admission, evidence/boundary answerers, and Trellis/smart-search operator maps ship as Skills/docs without new MCP tools. | Trellis embed, smart-search MCP, admission runtime enforcement, second truth store. |
| `0.8.8.x` | Auto-promoted governance. | Low-risk candidates auto-promote to trust-tiered memory and `/hm:review` becomes post-hoc audit/undo. | Manual-only review gate, hidden truth mutation, no audit metadata. |
| `0.8.9.x` | Runtime autopilot search. | `autopilot_search_tick` gives Agent clients a concrete task-aware search scheduler that only fires on bounded uncertainty. | Always-on broad search, client-specific hook lock-in, search without trigger discipline. |
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
`confirm_supersede` / `reject_supersede`; wake snapshots expose optional
structured action hints; and public MCP tools are exact-allowlisted to preserve
the single memory surface.

## 0.8.7.x — Memory Adoption Playbook

- Add `grill-before-distill` as the standard admission mode on distill: deep
  interrogation for high-impact items, light checklist for ordinary candidates,
  lookback for confirmed truth.
- Add non-writing answerers: `answer-memory-evidence` for proof gaps and
  `ask-memory-boundary` for architecture/product-scope questions.
- Document layered helpers in `docs/memory-adoption.md`: smart-search as a
  reference external-evidence pattern, Trellis as optional project-level
  orchestration with an executable pattern playbook (`check`, `update-spec`,
  `finish-work`, `journal` mapped to existing hm surfaces).
- Align `session-distill`, `/hm:distill`, and harness-mem skills to:
  `prepare` → draft claims → risk-scaled admission → `suggest_*` → evidence
  before `confirm_*`.

Status: complete for the Skill/doc layer. Admission runs automatically with
depth by risk; external evidence is required before confirmation but not before
candidate creation; Trellis and smart-search stay outside hm MCP/runtime. Next
hardening step (Later / Labs) is optional CLI preflight or tests — not a second
harness.

## 0.8.8.x — Auto-Promoted Governance

- Keep the public loop named `wake -> search -> distill -> review -> dream`,
  but define it as automatic runtime behavior.
- Use `/hm:review` as the audit inbox: user confirmation upgrades trust,
  rejection/undo removes bad auto-promotions, and supersede lineage stays
  visible.
- Keep `auto_review_candidates(apply=true)` as the low-risk promotion path with
  audit metadata.

## 0.8.9.x — Runtime Autopilot Search

- Install or generate client-specific integrations from a shared event model:
  session start, context transform, tool result, save point, and session end.
- Use `wake` once per session/project activation unless the project or branch
  changes.
- Use `autopilot_search_tick` at context/tool/save-point events; it calls
  `search_memory` only when a trigger fires: explicit user recall request,
  uncertain project convention, conflict with current context, tool failure
  that resembles a prior issue, file/module boundary question, or pre-write
  claim that must be grounded.
- Run `prepare_session_distill`, `auto_review_candidates(apply=true)`, and
  `dream_auto_tick` at save points or session end for eligible sessions; keep
  high-risk, conflicting, or weak-evidence items out of normal wake/search until
  audit.

See [autopilot-search-policy.md](autopilot-search-policy.md) for the runtime contract.

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
- **Admission/evidence enforcement**: optional CLI preflight or contract tests
  after the 0.8.7 playbook stabilizes; do not add a second runtime harness.
- **smart-search adoption**: install as user-level CLI Skill when a project
  wants fetched/source-backed external evidence; keep out of default hm MCP.

## Stable Boundaries

- No wiki bridge / knowledge-cache as truth.
- No multi-profile MCP public surface.
- No standalone metabolism/reflection product surface.
- No unaudited durable write; auto-promoted writes must carry evidence, status,
  policy reason, and undo metadata.
- No retrieval-quality claim without retrieval-isolated tests.
- No Trellis journal or parallel spec truth inside harness-mem.
- No smart-search or Trellis hard-coded into public MCP; workflow stays Skills.
