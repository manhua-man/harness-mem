# SQLite Current-Knowledge Convergence

Status: released as `0.9.20`. The repeatable six-session isolated runtime
acceptance uses a pre-frozen, source-digest-bound oracle and verifies extraction,
per-point answers, assimilation, truth lineage, normal readback, Notes, and
Answer Packets. A fresh generation-bound Desktop Hook and the full 14-claim
outcome contract also pass.
This plan does not by itself authorize migration, deletion, or redistillation
of real user memory. Normal runtime paths never perform those actions.

## Decision

`canonical.sqlite` is the single persistence authority for current long-term
knowledge. Markdown is an on-demand human-readable rendering of SQLite data,
not another stored truth and not an input to normal retrieval.

Candidate claims, verification envelopes, and proposed assimilation decisions
are job-scoped working material. They may survive a worker restart while the
job is active, but successful terminal jobs do not keep them indefinitely.

```text
native session + immutable revision
  -> distill job workspace
       candidate -> verification -> proposed disposition
  -> one SQLite transaction
       knowledge_entries + minimal knowledge_sources + required version record
  -> terminal receipt / handoff
  -> clean job workspace by lifecycle policy
  -> wake/search reads SQLite
  -> Markdown/JSON/text rendered only when requested
```

## Why this is the selected design

Three implementation choices were considered:

| Option | Shape | Result |
|---|---|---|
| A. Read-path patch | Point wake/search at SQLite but leave Markdown authority and the permanent audit ledger dormant | Rejected: leaves dead code and two conflicting mental models |
| B. Converged SQLite authority | SQLite current knowledge, job-scoped processing workspace, minimal durable source/version data, renderers on demand | Selected: one authority and one normal retrieval source |
| C. Dual authority | Keep Markdown and SQLite synchronized in both directions | Rejected: conflict resolution, crash recovery, and user edits create unnecessary failure modes |

This is a scope-reduction train. It removes the unshipped Markdown authority,
fingerprint synchronization, whole-document replacement, permanent candidate
ledger, and cross-file staged-commit machinery before adding new behavior.

## Product boundary

### Durable data

Only information required after the distill job is finished remains durable:

1. current project knowledge;
2. the smallest source locator needed to re-open and revalidate that knowledge;
3. the previous knowledge version required for a bounded Review undo;
4. an unfinished task handoff; and
5. a finite-retention job receipt proving the terminal result.

There is no permanent generic `knowledge_audit/` product layer. A Session Note
and Answer Packet remain session-history products under their existing
retention policy; they are not current knowledge and are not searched by
normal wake/search.

### Job-scoped data

The following are processing inputs, not long-term memory:

- extracted candidates;
- evidence windows and verification reason codes;
- proposed `add/refine/confirm/supersede/no_write/handoff/defer/conflict/reject`
  decisions;
- model correction attempts; and
- transaction staging data.

They live in the existing job/session ledger or a dedicated job workspace,
keyed by `distill_job_id`. They are retained only as long as needed for retry,
conflict resolution, or operator diagnosis.

| Job state | Candidate/evidence/decision detail |
|---|---|
| `pending` / `running` / retryable failure | Persist until the job can resume or reaches retry TTL |
| terminal `add/refine/confirm/supersede/no_write/reject` | Delete after SQLite commit, terminal receipt, and Note/Packet persistence succeed |
| `defer` / `conflict` | Retain until resolved or TTL expires; never enter normal retrieval |
| `handoff` | Move the actionable remainder to the handoff store, then delete processing detail |
| abandoned/crashed job | Recover by lease/TTL; do not treat its proposal as knowledge |

Cleanup must occur after the durable outcome is proven. Cleaning first would
make a failed commit impossible to retry safely.

## Current-knowledge schema

The normal knowledge projection is intentionally small:

```json
{
  "id": "k-hook-receipt-binding",
  "project_name": "harness-mem",
  "module_path": ["会话生命周期与 Hook"],
  "title": "Hook 终态必须绑定实际作业",
  "statement": "Codex Stop Hook 的回执必须对应同一会话的 distill job、Provider 回执与 Session Note；仅有 queued 或 completed 状态不能证明用户结果已完成。",
  "verified_at": "2026-08-18"
}
```

Field decisions:

| Field | Keep | Retrieval/display behavior | Reason |
|---|---:|---|---|
| `id` | Yes | Never embedded or shown by default | Stable handle for refine, supersede, feedback, sources, and undo |
| `project_name` | Yes | Used as a mandatory filter | Prevents cross-project retrieval and mutation |
| `module_path` | Yes | Used for optional grouping/filtering | Natural project organization; no allowlist or fixed taxonomy |
| `title` | Yes | Indexed and shown | Compact scanning and targeted retrieval; must be specific and not an internal type label |
| `statement` | Yes | Indexed and shown | The actual long-term knowledge; one independently useful assertion |
| `verified_at` | Yes | Shown only in full/library views | Freshness and revalidation cue |

The normal user view is smaller than the persistence row:

```markdown
# harness-mem 知识库

## 会话生命周期与 Hook

- **Hook 终态必须绑定实际作业**：Codex Stop Hook 的回执必须对应同一会话的 distill job、Provider 回执与 Session Note；仅有 queued 或 completed 状态不能证明用户结果已完成。
```

`id` is necessary but hidden: refine, supersede, feedback, source linkage, and
undo need a stable handle even when title or wording changes. `title` is part of
the knowledge itself: it makes one atomic statement scannable and independently
retrievable. `project_name`, `revision`, timestamps, source locators, and
verification dates are filters or controls, not default reading content.

Physical storage may also keep `revision`, `created_at`, and `updated_at` for
compare-and-swap, ordering, and undo safety. These are storage controls, not
memory content, are not embedded for semantic retrieval, and are not exposed in
normal output.

`claim_kind`, confidence, tier, status, job/session/candidate IDs, reason codes,
provider receipts, and assimilation rationale do not belong to
`knowledge_entries`. Claim type may be used while verifying and rewriting a
candidate, but the final `statement` itself must unambiguously say whether it is
a requirement ("应当/必须"), a verified implementation fact ("当前/已"), a
durable preference, or a procedure.

### Minimal source relation

Revalidation cannot be performed by reading the database's old verdict. A
small `knowledge_sources` relation therefore links a current knowledge ID to a
real source:

```text
knowledge_id, source_kind, locator, content_sha256, verified_at
```

This is not the job's full evidence envelope. It exists only so Review or Dream
can re-open the repository file, immutable transcript statement, local
authoritative file, web page, or API that supports the current statement.
Missing adapters fail closed: a stored digest or an earlier `verified` value
does not prove a web/API claim is still true.

### On-demand rendering

The same rows can be rendered without creating a second authority:

```markdown
# harness-mem 会话蒸馏知识库

## 会话生命周期与 Hook

- **Hook 终态必须绑定实际作业**：Codex Stop Hook 的回执必须对应同一会话的 distill job、Provider 回执与 Session Note；仅有 queued 或 completed 状态不能证明用户结果已完成。
```

Verification date and source locators appear only when the caller explicitly
requests a detailed view.

Deleting, editing, or corrupting an exported Markdown file cannot change
knowledge. Re-running the renderer against the same SQLite snapshot must produce
the same semantic output.

## Five-module ownership

The five modules remain independently measurable product areas; the storage
tables do not define the architecture.

| Module | This train changes | This train preserves |
|---|---|---|
| 0. Session intake/lifecycle | Job workspace retention and cleanup become explicit; SQLite mutation stays on the existing database inode and transaction boundary | Native revision, chunks, Hook/provider/receipt binding, retry and safe source retention |
| 1. Extraction | No storage-authority change | Existing lossless manifest, semantic/raw drilldown, and 0--12 independent points |
| 2. Per-point verification | Verification detail becomes job-scoped; successful terminal detail is cleaned | Independent source integrity and semantic-support gates |
| 3. Assimilation | Writes current knowledge through one SQLite transaction; atomic split/dedupe/targeted replacement remain semantic responsibilities | `ANSWERED` does not imply write; all nine dispositions remain |
| 4. Retrieval/use | Reads only current SQLite knowledge; indexes only `module_path + title + statement`; Markdown becomes a renderer | Project isolation, clean projection, feedback, and explicit raw/audit paths |

Review and Dream remain the governance feedback loop across modules 3--4. They
must re-open the real source, revalidate the affected statement, and use the
same SQLite mutation service. They do not restore a permanent candidate ledger
or edit exported Markdown.

## Transaction and recovery contract

An `add`, `refine`, or `supersede` operation uses one transaction on the
existing `canonical.sqlite` file:

```text
BEGIN IMMEDIATE
  verify project + expected current revision
  insert required previous-version snapshot
  insert/update/delete current knowledge rows
  replace minimal source links
  append bounded durable mutation/version record when undo requires it
COMMIT
  update/rebuild FTS/vector projection
  persist terminal receipt and Note/Packet
  clean terminal job workspace
```

The database file must not be replaced during migration or recovery. Replacing
its inode can leave a running process writing to an unlinked old database.

FTS/vector data is derived from SQLite current rows. If index refresh fails,
the knowledge transaction remains valid, the index is marked stale, and normal
reads use the authoritative SQLite rows or fail closed according to the read
contract. Derived indexes can never write knowledge back.

`confirm` creates no duplicate current row. `no_write` and `reject` create no
knowledge mutation. `defer` and `conflict` remain job outcomes. `handoff` writes
only to the handoff owner.

## Implementation train

The versions are construction slices, not claims that those product versions
already exist.

### 0.9.16 — Remove the rejected authority model and establish SQLite truth

Status: released in `0.9.20`.

- rewrite `KnowledgeStore` so `knowledge_entries` is authoritative;
- simplify `KnowledgeEntry` to the approved semantic fields plus hidden storage
  controls;
- add minimal `knowledge_sources` and bounded version/undo storage;
- delete Markdown fingerprint validation, `known_project_roots`, complete
  `replace_entries`, and cross-file staged mutation recovery;
- delete `ProjectKnowledgeBaseRepository` or move only deterministic formatting
  into a renderer module;
- stop constructing a permanent `knowledge_audit/` hierarchy;
- use in-place SQLite transactions and optimistic revision checks.

Exit: a new isolated data root contains current knowledge in SQLite, no
Markdown authority and no permanent candidate/evidence/decision collections.

### 0.9.17 — Make processing material temporary

Status: released in `0.9.20`.

- bind candidate, evidence, and proposed decision data to one job workspace;
- implement terminal cleanup ordering and TTL recovery;
- retain unresolved `defer/conflict` only until resolution/expiry;
- move `handoff` to its existing task owner;
- keep one correction attempt for invalid confirm/refine/supersede targets,
  then fail closed;
- keep the existing per-point verification and broad-candidate atomic split.

Exit: completed jobs leave current knowledge, minimal source links, required
undo state, handoffs, Notes/Packets, and finite receipts—not a second memory
corpus.

### 0.9.18 — Converge retrieval and presentation

Status: released in `0.9.20`.

- make wake/search/search-all read SQLite current knowledge only;
- make FTS/vector index only `module_path + title + statement`;
- exclude IDs, source locators, job/audit data, confidence, tier, and internal
  types from embeddings and normal output;
- add deterministic Markdown/JSON/text renderers for explicit view/export;
- preserve explicit raw/timeline/session-history access outside normal top-k.

Exit: deleting every exported Markdown file does not change search results;
library view contains only module, title, statement, and optional verified date
or explicitly requested source.

### 0.9.19 — Converge Review and Dream

Status: released in `0.9.20`.

- route confirm/refine/supersede/undo through the same SQLite transaction;
- re-open the real current source before changing durable truth;
- retain only the newest 32 project mutations and their referenced previous
  versions for supported undo;
- feed useful/ignored/misleading/stale/conflict signals into revalidation;
- prune expired receipts and unresolved work by policy; prune older mutation
  and undo-version rows atomically whenever a new mutation commits.

Exit: Dream/Review cannot mutate truth from an old verdict, exported Markdown,
or an invalid target ID.

### 0.9.20 — Isolated six-session product acceptance

Status: released in `0.9.20` after passing on 2026-08-19. The isolated
run did not touch the real runtime data root, and the later real Hook did not
authorize or perform legacy-memory migration.

- run exactly six retained sessions explicitly scoped to `harness-mem` in an
  isolated data root;
- compare expected promotion points with extracted/verified/assimilated results;
- show the user the rendered clean knowledge library and a separate bounded
  processing report;
- require no cross-project item, no internal heading, no broad duplicate, no
  audit-field leakage, and no forbidden write;
- run the project outcome contract after the runtime is frozen.

Evidence: six explicitly scoped `harness-mem` archives produced six completed
jobs, six persisted Notes, six Answer Packets, and 12 current SQLite knowledge
entries. Every entry was retrieved through the normal current-project knowledge
path; the rendered library contained only modules, titles, and statements, and
real SQLite/archive-state/Note fingerprints were unchanged. The repeatable
artifacts are `.tmp/0.9.20-six-session-20260819T120000Z-v2/report.json` and
`knowledge.md`.

Exit: the actual knowledge content is presented for user review and the frozen
runtime passes a fresh Desktop Hook plus the full outcome contract; passing
tests or a provider response alone is insufficient.

### 0.9.21 — Explicitly authorized legacy convergence

Status: completed for one separately authorized `harness-mem` scope. The
isolated `0.9.20` result did not grant that authorization, and this completion
does not authorize migration for any other project or later cohort.

- begin only after separate user approval;
- freeze legacy row IDs and content hashes, with later writes in a separate
  delta cohort;
- preview keep/rewrite/merge/reject results and rehearse rollback in isolation;
- update the existing database in place under an exclusive maintenance lock;
- read every accepted result through normal search and prove legacy noise is
  absent;
- never infer authorization to clear or redistill the real archive.

## Removal ledger

This train is complete only when the rejected implementation is actually gone:

| Remove or reduce | Replacement |
|---|---|
| Markdown as knowledge authority | SQLite `knowledge_entries` |
| Markdown/SQLite source fingerprint protocol | Ordinary derived-index generation from SQLite |
| `known_project_roots` discovery from Markdown files | Explicit project identity on knowledge rows and query scope |
| Whole-document `replace_entries` mutation | Row-level transactional mutation |
| Permanent candidate/evidence/decision JSON ledger | Job workspace with terminal cleanup/TTL |
| Cross-file staging and recovery | One SQLite transaction on the existing inode |
| `claim_kind`, source refs, confidence/tier in current rows | Canonical wording plus separate minimal source relation |
| Markdown parser as read path | SQLite query plus renderer |

No project allowlist or fixed module taxonomy is introduced. Archive runs use
the explicit project argument and detected session ownership; cross-project
search remains an explicit user action.

## Not in scope

- changing lossless transcript capture, chunking, manifest, semantic/raw
  drilldown, or the 0--12 extraction limit;
- inventing a fixed `harness-mem` module catalog or another project whitelist;
- making Markdown editable knowledge storage;
- retaining full evidence/decision history forever;
- exposing internal IDs or source metadata in normal wake/search;
- treating Session Notes, Answer Packets, receipts, or handoffs as current
  knowledge;
- implementing external web/API revalidation by pretending an old hash is a
  live adapter; or
- touching real user memory without a separately authorized, project-scoped
  maintenance slice.

## Failure modes and required behavior

| Failure | Required behavior |
|---|---|
| SQLite lock timeout or transaction conflict | Retry within a bound; otherwise leave job retryable and write no partial truth |
| Worker crashes before commit | Resume from job workspace; current knowledge is unchanged |
| Worker crashes after commit but before cleanup | Reconcile via idempotency key/receipt, then finish Note and cleanup without duplicate truth |
| Cleanup runs too early | Contract failure; retry evidence must remain until durable outcome is proven |
| Source locator is gone or digest changed | Mark revalidation stale/unavailable; do not self-verify from the old database verdict |
| Web/API adapter is missing or offline | Defer/fail closed for claims whose current validity depends on it |
| Refine/supersede target changed concurrently | Compare-and-swap fails; re-read and recompute, never overwrite silently |
| FTS/vector refresh lags | Mark/rebuild projection; do not serve stale superseded rows |
| Renderer sees empty data, Unicode, or duplicate labels | Produce deterministic valid output; duplicate module/title never merges distinct IDs silently |
| Legacy `MemoryEntry` rows exist | Keep behind compatibility reads until authorized migration; never silently treat them as new current knowledge |

## Acceptance redlines

The implementation is not complete unless all are directly demonstrated:

- removing all Markdown exports leaves normal wake/search unchanged;
- hand-editing a Markdown export cannot mutate SQLite truth;
- a SQLite transaction failure produces neither half an entry nor half a
  supersede;
- terminal job processing detail is cleaned according to policy;
- deferred/conflicted/rejected/provisional/raw/session-history material has zero
  normal retrieval hits;
- FTS/vector contains only current `module_path + title + statement` semantics;
- IDs remain usable for target mutation and feedback but never appear in normal
  output;
- explicit cross-project search keeps project identity without a whitelist;
- six-session acceptance produces only `harness-mem` knowledge and no internal
  headings such as candidate stages or storage kinds;
- renderer output is deterministic and contains no job, receipt, reason code,
  confidence, tier, or candidate metadata;
- `.codex/outcomes.json` passes against the frozen runtime; and
- no real-memory migration occurs without a new explicit authorization.

## Execution strategy

The storage, assimilation, and read-path changes overlap heavily and should be
implemented serially on the main line in the version order above. Once each
contract is locked, non-overlapping tests and documentation mirrors may be
updated in parallel. Each slice begins with removal/contract tests, then runtime
implementation, targeted tests, full tests, and finally user-outcome probes
when the slice changes a user-visible or asynchronous result.

The `0.9.20` evidence is complete and released: the isolated six-session SQLite
knowledge matches the frozen expected-point oracle, the fresh Desktop Hook is
dispatch-generation bound, and the full outcome contract passes. This document
never authorizes real-memory migration by itself; any such operation must be
separately approved, project scoped, source revalidated, and reversible.
