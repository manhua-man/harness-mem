# Reference projects catalog

Catalog baseline checked: 2026-08-02; individual pages may record newer checks.
This index is the entry point for the reference-source catalog. Each project has
a separate page with its upstream marker, local mirror, source evidence,
adoption decision, and review trigger.

The release-planning derivation is documented in
[evidence-to-roadmap.md](evidence-to-roadmap.md); it separates upstream facts
from harness-mem gaps and proposed work.

The [2026-10-20 write-path review](write-path-20261020.md) pins current
Hindsight, claude-mem and Mem0 implementations for admission, actual updates
and Dream transactions; deployment remains separate from natural acceptance.

## Current reference set

| Project | Role | Note |
|---|---|---|
| [claude-mem](claude-mem.md) | product/reliability | Durable outbox, queue recovery, health lifecycle |
| [Hindsight](hindsight.md) | product/reliability | Leases, worker recovery, timeout and migration safety |
| [Mem0](mem0.md) | product/lifecycle | Scoped deletion, history, compatibility boundaries |
| [Graphiti](graphiti.md) | retrieval/temporal | Validity intervals, relation search, invalidation |
| [sqlite-vec](sqlite-vec.md) | integration/index | Local vector index invariants and mutation behavior |
| [PrecisionMemBench](precisionmembench.md) | evaluation | Retrieval isolation, mutation, noise leakage, latency |
| [Letta](letta.md) | research/product | Context budgets, summary and archival boundaries |
| [MemoryData](memorydata.md) | evaluation | Replayable query records and explicit skipped/error states |
| [Tantivy](tantivy.md) | trigger-based integration | Staged index commit, rollback, fault injection |
| [LoCoMo](locomo.md) | trigger-based evaluation | Cross-session and temporal dialogue fixtures |
| [LongMemEval](longmemeval.md) | trigger-based evaluation | Retrieval, answer, and abstention score lines |
| [BEAM](beam.md) | trigger-based evaluation | Adapter contracts, capability gaps, failure artifacts |
| [smartsearch](smartsearch.md) | evidence retrieval | Source extraction and visible fallback/degraded paths |
| [mattpocock/skills](mattpocock-skills.md) | workflow/skills | Explicit grilling, domain modeling, composable skill boundaries |
| [Pi](pi.md) | host/session architecture | Append-aware context, tool-safe cut points, branch lineage |
| [vstash](vstash.md) | retrieval research | Public source checked at a fixed revision; Chinese and runtime fit remain unverified |

## Architecture reading order

For a fast but accurate review, read the reliability trio first, then the
retrieval/index trio, then the evaluation and host-compatibility pages:

1. [Hindsight](hindsight.md), [claude-mem](claude-mem.md), and [Mem0](mem0.md)
   explain task state, recovery, and deletion boundaries.
2. [Graphiti](graphiti.md), [sqlite-vec](sqlite-vec.md), and [Tantivy](tantivy.md)
   explain temporal retrieval and derived-index publication.
3. [PrecisionMemBench](precisionmembench.md), [MemoryData](memorydata.md),
   [LongMemEval](longmemeval.md), [LoCoMo](locomo.md), and [BEAM](beam.md)
   explain evaluation and behavior contracts.
4. [Letta](letta.md), [smartsearch](smartsearch.md), and [Pi](pi.md) cover
   budget, evidence UX, and session-context lineage;
   [mattpocock/skills](mattpocock-skills.md) covers optional workflow
   composition; [vstash](vstash.md) provides a source-level retrieval comparison.

## Evidence review refresh (2026-11-18)

- Session Distill remains at `42fb1c0`. Its question table and check-work provide a review pattern for HM's existing manual finalize path. The public anchor checker covers referenced files and line ranges. The separate batch verifier described in the operation retrospective is absent from that public tree. [Deep Distill workflow](https://github.com/manhua-man/session-distill-skills/blob/42fb1c0b26c2eeafe38104aae130c7e112f0d75d/shared/references/deep-distill-workflow.md) · [Anchor checker](https://github.com/manhua-man/session-distill-skills/blob/42fb1c0b26c2eeafe38104aae130c7e112f0d75d/scripts/kb-anchor-checker.py#L234)
- claude-mem `c1dc252` tests a Codex patch call with a paired result and verifies the recorded file edit in SQLite. Its failed-tool fixtures exercise failed reads and writes separately. Hindsight `082822a` binds exact quotes to source memory IDs and retains attachment context. Mem0 `fff8a64` distinguishes provider extraction failure from an empty extraction and only projects successful inserts. These are relevant to HM's literal evidence, actual write checks, and partial results. [claude-mem patch regression](https://github.com/thedotmack/claude-mem/blob/c1dc252bda98b1310ba3fa4b195efe49070d554b/tests/transcripts/processor-patch-result-evidence.test.ts) · [Hindsight evidence](https://github.com/vectorize-io/hindsight/blob/082822aa0bcfa069f3bffc8cef79480ce79e7c02/hindsight-api-slim/hindsight_api/engine/reflect/observations.py#L33) · [Mem0 write path](https://github.com/mem0ai/mem0/blob/fff8a6472512d1bc1a4bccab8c645b65a1df7fe5/mem0/memory/main.py#L966)
- BEAM `8f4e5ef` traces required evidence through storage, retrieval, presentation, and use. The matched HM run adopts those distinctions in independent scoring. LongMemEval `9e0b455` and MemoryData `bdbe698` remain at the checked catalog revisions. Their useful comparison points are all-required-evidence recall and replayable question metadata. [BEAM failure attribution](https://github.com/MasterSummer/BEAM-LongHorizonMemBench/blob/8f4e5ef25f9f43c567b4ebfd18570ea8467987c1/src/lhmsb/longhorizon/failure_attribution.py) · [LongMemEval scoring](https://github.com/xiaowu0162/LongMemEval/blob/9e0b455f4ef0e2ab8f2e582289761153549043fc/src/retrieval/eval_utils.py#L27) · [MemoryData loader](https://github.com/OpenDataBox/MemoryData/blob/bdbe698f776d921ac791d1b07c0a7fc65a8bb4bb/benchmark/memoryagentbench/loader.py#L173)
- vstash `c293cb2` now has claim validity and atomic replacement. Its tests cover superseded knowledge staying out of normal results after a text rewrite and rejection of invalid replacement targets before a write. These cases can inform regression tests for HM's existing current-knowledge boundary. Source references in vstash are supplied by the caller and the examples verify lifecycle behavior. [vstash change](https://github.com/stffns/vstash/commit/c293cb2aa89dd3a28491f87fae158098eab74890) · [Replacement tests](https://github.com/stffns/vstash/blob/c293cb2aa89dd3a28491f87fae158098eab74890/tests/test_claims_unified.py)

The default-branch check also found newer heads for Graphiti (`4ef979c`),
PrecisionMemBench (`61a712a`), Letta (`8816d3a`), Tantivy (`0aa896f`),
smartsearch (`1969e4f`), mattpocock/skills (`5863806`), and Pi (`ff8721f`).
These are remote reference observations. The sqlite-vec and LoCoMo heads still
match the catalog pins.

## Version and evidence rules

Performance claims have a separate [scope and denominator comparison](performance-comparison.md)
(checked 2026-10-15). Search-only/context-size numbers are not full Codex task
latency or billed-cost evidence; our matched experiment is recorded in
[the performance report](../performance-20261015.md).

- Stable core or SDK tags are implementation truth. Prereleases, integration
  tags, papers, and untagged commits are recorded separately.
- A page must include the local HEAD or paper revision and a source/test path.
  A version string without a revision is not sufficient evidence.
- Borrow interfaces, invariants, fixtures, and failure semantics only when they
  fit the existing `wake -> search -> distill -> review -> dream` boundary.
  Do not copy another project's server, graph database, cloud sync, or agent
  product surface by implication.
- A reference change becomes a harness-mem task only when it changes a product
  invariant, a reproducible regression case, an operator workflow, or a
  measured roadmap decision.

## Local source mirrors

The canonical local source root is:

`F:\\AIInfra\\upstreams\\harness-mem`

Every tracked source is a direct child Git repository. The directory is local
research material, not a runtime dependency. Never reset or overwrite a dirty
mirror. Fetch first, update a clean mirror with `git pull --ff-only`, and treat
a non-fast-forward update as an explicit review operation. Preserve an old HEAD
on an archive branch before an authorized reset.

| Local directory | Upstream ref | HEAD (2026-08-01) |
|---|---|---|
| `claude-mem` | `main` | `a90066f9cf82` |
| `hindsight` | `main` | `b5d8439c8f1b` |
| `mem0` | `main` | `38e47ac2619b` |
| `graphiti` | `main` | `4f62cfe7a2d5` |
| `sqlite-vec` | `main` | `04d28bd21773` |
| `precisionMemBench` | `main` | `b95d6abb471c` |
| `letta` | `main` | `5beb66e9981d` |
| `MemoryData` | `main` | `bdbe698f776d` |
| `tantivy` | `main` | `667132fa7ab4` |
| `locomo` | `main` | `3eb6f2c585f5` |
| `LongMemEval` | `main` | `9e0b455f4ef0` |
| `BEAM-LongHorizonMemBench` | `main` | `c3d608d5fc7c` |
| `smartsearch` | `main` | `667c465d0f6e` |
| `mattpocock-skills` | `main` | `2ab958093e83` |

Older local repositories in the same parent are a research pool, not active
baselines. They should not silently become release requirements; add a page
only when a review promotes one into the tracked set.

## Review cadence

Review the core product and integration references monthly and at each release.
Review research and trigger-based references when their stated trigger fires.
The next release plan is maintained in [roadmap.md](../roadmap.md), while this
catalog remains evidence and provenance rather than a second roadmap.
