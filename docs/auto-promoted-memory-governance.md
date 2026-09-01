# Auto-Promoted Memory Governance

This document defines governance around the five-module architecture and
records the `0.9.x` compatibility statuses. In the current `0.9.26` source,
SQLite `knowledge_entries` is the sole authority for current long-term
knowledge. Candidate claims,
verification detail, and proposed decisions are job processing material, not a
second memory product.

The five modules are session intake and lifecycle, extraction, verification,
assimilation, and retrieval/use. Review and Dream connect the last three as a
governance feedback loop rather than adding a sixth stage.

## Governing path

```text
immutable session revision
  -> extract claims and source locators
  -> verify each claim against its real source
  -> assimilate against SQLite current project knowledge
  -> one SQLite transaction | no-write | handoff | defer/conflict/reject
  -> refresh derived FTS/vector indexes
  -> Answer Packet + Note + terminal receipt
  -> clean terminal job material by lifecycle policy
```

The boundaries are deliberate:

- extraction discovers up to 12 independent claims; it does not decide final
  disposition, title, wording, or module placement;
- `ANSWERED` proves only that a point's evidence question was answered;
- assimilation decides durable value, atomic splitting, semantic deduplication,
  replacement, title, and natural project-module organization;
- current knowledge rows contain only a stable hidden ID, project, natural
  module path, title, one-statement body, and verification date;
- a separate minimal source relation exists only to re-open the real source;
- full candidate/evidence/proposed-decision detail stays with the job and is
  removed after a proven terminal outcome, except unresolved work within TTL;
  and
- FTS/vector/compact views and Markdown exports are rebuildable projections of
  SQLite current knowledge, not truth authorities.

There is no hard-coded project module allowlist. The assimilation model uses the
whole current project knowledge view and verified new knowledge to preserve or
form natural functional modules. Internal claim/storage kinds may control
evidence requirements but never become visible headings.

## Write boundary

Local **harness-mem code** (Dream/worker/storage, not the external model API)
is the only component allowed to publish an assimilation result. The model API
returns a bounded schema-checked proposal; harness-mem revalidates references
and named targets and performs the knowledge/source/required-version mutation in
one transaction on the existing `canonical.sqlite` file.

| Decision | Durable effect |
|---|---|
| `add` | Add source-backed atomic current knowledge |
| `refine` | Replace one named current item with a more precise item |
| `confirm` | Keep one named current item; add no duplicate |
| `supersede` | Replace one named current item with a newer conclusion |
| `no_write` | Add no long-term knowledge |
| `handoff` | Preserve unfinished work in the handoff owner |
| `defer` | Keep unresolved work with the job until resolution/TTL |
| `conflict` | Block publication and retain the job conflict until resolution/TTL |
| `reject` | Terminate unsupported, malformed, unsafe, or irrelevant content |

`confirm`, `refine`, and `supersede` require exactly one current SQLite target.
An invalid target receives one bounded correction attempt, then fails closed.
No new autonomous path may use `provisional` as a catch-all truth state.

## Review and Dream feedback

Review and Dream are core governance capabilities across modules 3--4, not a
sixth linear stage and not operator-only maintenance.

- **Review** handles human correction, rejection, undo, and replacement.
- **Dream** discovers stale, duplicate, misleading, conflicting, mergeable, or
  replaceable knowledge from current knowledge and bounded use feedback.

Both return the affected statement to its real source, per-point verification,
and the same SQLite assimilation mutation. Neither treats an old database
verdict as fresh proof, edits a Markdown export, or maintains a parallel truth
store.

```text
retrieval/use feedback
  -> Review or Dream finding
  -> reopen real source
  -> verify
  -> assimilate
  -> SQLite transaction + derived-index refresh
```

## Normal retrieval and explicit history

Normal `wake` and `search` use SQLite current knowledge or a same-generation
derived index. They return the relevant title and knowledge body and do not
expose transcript, candidate, Answer Packet, Note, decision reasons, provider
receipts, hashes, internal IDs, or historical rows.

An explicit source/history request may join a knowledge item to its minimal
source locator, finite receipt, Session Note/Packet, or supported undo version.
An old result explains what happened then; it cannot prove the underlying
repository, configuration, web page, or API still supports the claim now.
Revalidation reopens the real source.

## Job-material retention

| State | Retention |
|---|---|
| pending/running/retryable | Keep processing detail so the job can resume |
| terminal add/refine/confirm/supersede/no_write/reject | Clean detail after knowledge/no-write, Note/Packet, and receipt are durable |
| defer/conflict | Keep until resolved or TTL expires; exclude from normal retrieval |
| handoff | Move actionable state to the handoff store, then clean processing detail |
| receipt | Keep for a bounded policy window, then compact/remove |

Cleanup before durable outcome proof is a contract violation. Job detail is not
retained forever merely to offer a generic audit surface.

## `0.9.x` compatibility statuses

The compatibility model introduced in `0.9.20` and carried through `0.9.26`
still exposes historical
`MemoryEntry` status vocabulary. These statuses describe legacy/manual records;
they are not the target current-knowledge schema.

| Status | Compatibility layer | Target-path treatment |
|---|---|---|
| `pending` | Candidate | Job-scoped work only |
| `deferred` | Candidate | Job-scoped unresolved work only |
| `rejected` | Candidate | Terminal non-write; clean by policy |
| `auto_confirmed` | Legacy truth | Input to separately authorized convergence |
| `provisional` | Legacy risky truth | Excluded by default; input to separately authorized convergence |
| `user_confirmed` | Legacy audited truth | Input to separately authorized convergence |
| `superseded` | Legacy history | Compatibility/authorized migration input only |

Legacy status transitions remain readable throughout the documented `0.9.x`
support window. New session distill must not create provisional long-term truth.
The public MCP write surface remains `govern_memory`; it routes correction and
review intent into the local harness-mem verification/assimilation boundary.

## Source and lifecycle safeguards

- The immutable session revision is the authoritative session record;
  Observations are derived evidence, not proof that distillation completed.
- Candidate creation and finalization are idempotent for one source revision.
- A Hook can claim only capture/queue until the bound job, SQLite knowledge or
  explicit no-write, Note, and terminal receipt are read back.
- Source cleanup remains receipt-first, policy-authorized, session-scoped, and
  fail closed.
- The database inode is not replaced during migration or recovery.
- Real legacy convergence requires explicit authorization after isolated
  six-session acceptance.

## Related documents

- [Five-module memory adoption](memory-adoption.md)
- [SQLite current-knowledge convergence](roadmap/knowledge-truth-separation.md)
- [Distill acceptance plan](distill-test-plan.md)
- [Recall audit](recall-audit.md)
- [Autopilot search policy](autopilot-search-policy.md)
