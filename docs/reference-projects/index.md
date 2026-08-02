# Reference projects catalog

Checked: 2026-08-02. This index is the entry point for the reference-source
catalog. Each project has a separate page with its upstream marker, local
mirror, source evidence, adoption decision, and review trigger.

The release-planning derivation is documented in
[evidence-to-roadmap.md](evidence-to-roadmap.md); it separates upstream facts
from harness-mem gaps and proposed work.

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
| [vstash](vstash.md) | paper-only research | Revisit only when implementation evidence appears |

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
   composition; [vstash](vstash.md) remains paper-only.

## Version and evidence rules

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
