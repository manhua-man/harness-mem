# harness-mem Roadmap

This roadmap distinguishes the released runtime from the next construction
train. It does not authorize mutation of real user memory.

## Current release

The published package remains `0.9.12`. It provides session lifecycle,
lossless extraction, content-addressed evidence checks, governed retrieval,
Dream/Review feedback, and explicitly authorized detached semantic execution.
Its compatibility `MemoryEntry` path still mixes candidate, evidence, decision,
and truth concerns.

The dirty worktree contains the unshipped `0.9.16`--`0.9.19` convergence
implementation. It replaces the rejected Markdown-authority experiment with
SQLite current knowledge, job-scoped processing material, on-demand rendering,
and one Review/Dream mutation path. The repeatable `0.9.20` six-session runtime
acceptance, a fresh generation-bound Desktop Hook, and the complete 14-claim
outcome contract now pass. The worktree remains unshipped.

## Current worktree — SQLite current-knowledge convergence

```text
canonical.sqlite / knowledge_entries
  = single authority for current long-term knowledge

job workspace
  = temporary candidates, verification, and proposed decisions
  = retained only for retry, unresolved work, and bounded diagnosis

FTS/vector
  = rebuildable indexes derived from SQLite current knowledge

Markdown/JSON/text
  = on-demand user presentation, never an authority
```

| Version | Primary change | Main modules | Removal/convergence | Status |
|---|---|---|---|---|
| `0.9.16` | Make SQLite current knowledge authoritative and transactional | 0, 3 | Remove Markdown authority, fingerprint synchronization, whole-document mutation, and permanent audit-ledger construction | Implemented and test-verified in worktree; unshipped |
| `0.9.17` | Make candidate/evidence/decision material job-scoped and clean terminal detail | 2, 3 | Remove completed processing records as a permanent corpus; move handoff to its owner | Implemented and test-verified in worktree; unshipped |
| `0.9.18` | Read only clean SQLite knowledge and render Markdown on demand | 4 | Remove Markdown parser from normal reads and exclude audit/storage fields from indexes | Implemented and test-verified in worktree; unshipped |
| `0.9.19` | Route Dream/Review revalidation and undo through the same SQLite mutation path | 2, 3, 4 | Remove parallel mutation paths and unbounded decision history | Implemented and test-verified in worktree; unshipped |
| `0.9.20` | Run six retained sessions in an isolated `harness-mem` scope and show the actual clean library | 0--4 | Delete remaining duplicate/broad/internal-heading behavior found by acceptance | Runtime acceptance and 14-claim outcome contract passed; unshipped |
| `0.9.21` | Converge legacy real memory after separate explicit approval | 0, 3, 4 | Retire approved legacy rows only after preview, rollback rehearsal, and readback | Blocked on separate user authorization; no real-memory mutation performed |

These versions are implementation slices, not additional product modules. The
product architecture remains the five independently measurable modules:

```text
0. session intake/lifecycle
-> 1. extraction
-> 2. per-point verification
-> 3. assimilation
-> 4. retrieval/use
```

Review and Dream remain the governance feedback loop across modules 3--4. They
re-open real sources, return to per-point verification, and use the same
assimilation mutation path.

## Locked decisions

- Extraction keeps the existing lossless manifest, semantic/raw drilldown, and
  zero-to-twelve independent promotion points.
- One session may yield multiple independent durable items.
- Source authenticity and semantic support are verification concerns;
  `ANSWERED` does not mean “write this”.
- Assimilation owns durability, atomic splitting, wording, natural module
  grouping, deduplication, and the nine dispositions.
- There is no project allowlist and no fixed module taxonomy. An archive run is
  scoped by its explicit project argument and verified session ownership.
- Current knowledge keeps a stable internal ID, project identity, natural
  module path, specific title, one-statement body, and verification date.
- The stable ID is for mutation/feedback/source linkage and is never shown or
  embedded by default. The title is retained because it improves human scanning
  and targeted retrieval; it cannot be an internal type such as “candidate” or
  “stable operation rule”.
- Minimal source locators remain separate from current knowledge so Review and
  Dream can re-open the real repository, transcript, local file, web page, or
  API. Earlier database verdicts do not revalidate themselves.
- Candidate, verification, and proposed-decision detail is temporary. Terminal
  cleanup occurs only after SQLite commit, Note/Packet, and receipt are durable.
- Real memory is never migrated, deleted, or redistilled as a side effect of
  development, docs, startup, or tests.

## Delivery order and stop conditions

1. Completed in worktree: lock schema, transaction, cleanup, and clean-projection tests.
2. Completed in worktree: remove rejected Markdown authority and permanent audit-ledger code.
3. Completed in worktree: implement SQLite row mutations and minimal source/version relations on the existing database inode.
4. Completed in worktree: move processing detail into job lifecycle storage with retry-safe cleanup.
5. Completed in worktree: converge normal retrieval and on-demand rendering.
6. Completed in worktree: route Dream/Review through revalidation and the same mutation service.
7. Completed: six retained `harness-mem` sessions ran in an isolated data root;
   all six jobs, Notes, and Answer Packets reached terminal persistence, and all
   12 clean knowledge entries were read back without changing real runtime data.
8. Completed: a fresh Desktop Hook receipt bound dispatch generation, session,
   job, Provider, and Note; the full outcome contract passed 14/14.
9. Ask separately before any legacy real-memory convergence.

Any partial SQLite mutation, early workspace cleanup, stale/superseded retrieval
hit, cross-project write, unsupported source claim, duplicate current item,
audit field in normal output, or Markdown-to-truth write path stops the train.
Unit tests, provider JSON, queued jobs, and generic `completed` status are only
supporting evidence.

The detailed conceptual contract is
[memory-adoption.md](memory-adoption.md), the engineering plan is
[knowledge-truth-separation.md](roadmap/knowledge-truth-separation.md), and the
acceptance matrix is [distill-test-plan.md](distill-test-plan.md).

## Historical releases

Older 0.8--0.9 release notes remain historical evidence. The deleted
`0.9.13--0.9.15` proposal and the unshipped Markdown-authority experiment do not
define current implementation status or the next target architecture.
