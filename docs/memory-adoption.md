# Session Lifecycle and Five-Module Memory Adoption

This document owns the conceptual contract for turning session evidence into
usable long-term memory. The full product path starts before extraction: it
must first safely receive, version, and finish a native session. The `0.9.20`
runtime implements that lifecycle, lossless extraction, content-addressed
evidence validation, governed truth, and normal retrieval. It isolates raw
Observation content and internal audit metadata behind explicit deep recall or
diagnostic views. Legacy `MemoryEntry` remains a compatibility/manual Review
path, while SQLite `knowledge_entries` is the authority for new current
long-term knowledge.
Candidate, evidence, and proposed-decision records are job-scoped processing
material retained only for retry, unresolved work, and bounded diagnosis.
Current search reads SQLite deterministically; optional FTS/vector data remains
a rebuildable optimization. Markdown is rendered on demand for reading or
export and never becomes a write path. The frozen six-session oracle, real Hook,
and runtime outcome acceptance passed for `0.9.20`.
[SQLite Current-Knowledge Convergence](roadmap/knowledge-truth-separation.md)
owns the construction and qualification plan and does not authorize a
live-memory migration.

```text
0. session intake and lifecycle
-> 1. extraction -> 2. verification -> 3. assimilation -> 4. retrieval/use
```

Stages 1--4 are the knowledge-adoption stages. Stage 0 is the runtime
foundation that makes their inputs and receipts trustworthy. Together, stages
0--4 are the product's internal functional modules: they are not a user-facing
daily checklist, and each can be iterated and measured independently. They are
deliberately different responsibilities:

- session intake/lifecycle owns the native session and its processing state;
- extraction finds possible promotion points;
- verification establishes what each point's evidence supports now;
- assimilation decides what the project should remember and reconciles it with
  current truth;
- retrieval/use exposes current project knowledge from SQLite to future tasks
  and records bounded outcome feedback.

## Module operating contract

The five sections below are the single authoritative contract. Each names its
unit, responsibility boundary, non-responsibility, and quality signals so a
failure is attributed to a module rather than vaguely called a distill failure.

## 0. Session intake and lifecycle

**Unit:** one native session plus one immutable session revision, not a memory
claim.

This stage answers which native session this is, who or which project may use
it, whether its source is complete, and whether processing reached a trustworthy
terminal state.

It owns:

- host intake from Codex, Claude, Cursor, and other supported adapters;
- project recognition and authorization boundaries;
- immutable revisions, lossless chunks, incremental versions, and integrity
  checks;
- queueing, leases, retries, concurrency control, and idempotency;
- distill-job creation, terminal receipts, and Hook/provider binding; and
- retained-source policy and fail-closed safe cleanup.

**Does not own:** deciding what the project should remember. It supplies
complete, authorized source revisions and durable receipts to later stages.

**Quality signals:** no missing session, missing content, or duplicate work;
reconstructable source and revisions; reliable terminal state across retries;
no source deletion outside policy; and receipts demonstrably bound to their
session and job.

## 1. Extraction

**Unit:** zero to twelve independently addressable candidate promotion points
from one session.

**Owns:** high-recall discovery from the complete source and a source location
for every candidate. Its output is a claim to verify plus evidence locators.
**Does not own:** evidence validation, assimilation disposition, final title,
project module organization, or writes to long-term knowledge.

The existing lossless session path remains:

```text
native session -> immutable revision -> ordered chunks -> coverage-first
manifest -> semantic/raw drilldown -> final-session review -> 0..12 candidates
```

One session may contain more than one promotion point. The candidates remain
independently addressable; the session summary is separate and never substitutes
for candidate content.

Extraction optimizes bounded recall. It may surface a one-off request or
temporary state as a signal, but that signal is not yet durable memory.

**Quality signals:** important promotion points are not missed; a whole session
is not collapsed into one conclusion; each candidate is narrow enough for an
independent decision; and source coverage stays lossless.

## 2. Per-point verification

**Unit:** one candidate promotion point, never a whole session.

**Owns:** reference integrity and current semantic support for that exact
statement. **Does not own:** deciding durable value or mutating long-term
knowledge.

The Answer Gate is runtime-derived from each candidate's evidence envelope. An
Agent supplies `evidence_basis`, its requested `verification_outcome`, and
content-free `verification_refs`; trusted runtime code re-reads the current
repository or immutable user-statement source before assigning the gate status.

```text
candidate claim
  -> evidence question
  -> current-source verification
  -> runtime Answer Gate
```

| Runtime status | Meaning | Next stage |
|---|---|---|
| `ANSWERED` | Current repository or explicit user-statement evidence validates the claim | Eligible for assimilation |
| `PARTIAL` | Some evidence exists, but the proof is incomplete | Defer or handoff |
| `UNANSWERED` | No qualifying proof | No durable write |
| `CONTRADICTED` | Evidence conflicts with the claim | Reject or route to conflict handling |
| `STALE` | A content-addressed source changed after the claim was formed | Reject or supersede |
| `NOT_APPLICABLE` | The question does not establish durable truth | No durable write |

`ANSWERED` means only that the evidence question is answered. It does not mean
that the statement is durable, atomic, useful, non-duplicative, or ready for
truth mutation.

The runtime keeps three judgments distinct:

1. reference integrity: the cited source, role, scope, and digest are current;
2. semantic support: that source supports the candidate wording;
3. long-term utility: assimilation decides whether the supported point belongs
   in future project memory.

`NOT_APPLICABLE` never acts as a hidden promotable state. A supported durable
user preference is `ANSWERED` on authentic user-statement evidence; otherwise
the point does not proceed to durable assimilation.

Verification is independent per promotion point. A session may therefore have
several ANSWERED points, one contradiction, and one unfinished handoff. The
session-level `promotion_decision` is derived from those outcomes; it is not a
single gate that erases the independent results.

`answer-memory-evidence` may gather missing evidence,
`grill-before-distill` may pressure-test a broad conclusion, and
`ask-memory-boundary` may resolve a true product boundary. None writes or
promotes memory.

**Quality signals:** a user mention is not confused with an established fact;
old implementation evidence is not reported as current implementation; one
point's failure does not contaminate siblings; and later corrections calibrate
false positives.

## 3. Assimilation

**Unit:** one verified promotion point reconciled against current project
knowledge.

Assimilation is the semantic and governance boundary between verified claims
and SQLite current knowledge. It owns durable-value judgment,
knowledge-language rewriting, atomic splitting, semantic deduplication, natural
project-module organization, transactional current-knowledge mutation, and the
bounded version state needed for replacement/undo. It does not acquire original
sources or expose processing provenance through normal retrieval.

```text
ANSWERED candidate
  -> durability and destination decision
  -> knowledge-language rewrite
  -> project knowledge-base semantic match
  -> add | refine | confirm | supersede | no_write | handoff | defer | conflict
```

It must answer all of these questions:

1. Will this help a future task, or is it only a record of the current task?
2. Is it a project fact, reusable workflow, durable user preference, project
   decision, behavior-changing rule, explicit relation, handoff, or no-write
   item?
3. Can it be stated as one complete, independently useful fact or rule?
4. Does an equivalent, broader, narrower, older, or conflicting current truth
   already exist?
5. Which mutation, if any, preserves one current knowledge statement and full
   historical auditability?

Normal outcomes are:

| Outcome | Effect |
|---|---|
| `add` | Add one atomic item to SQLite current knowledge |
| `refine` | Replace one named item with a narrower or more complete statement |
| `confirm` | Keep the named current item; create no duplicate |
| `supersede` | Replace one named current item and keep only the bounded predecessor state required for undo |
| `no_write` | Keep no long-term knowledge; the session may still have a Note/Packet |
| `handoff` | Persist unfinished state outside long-term truth |
| `defer` | Keep the job-scoped candidate until proof/scope is resolved or TTL expires |
| `conflict` | Block truth mutation and retain the job-scoped conflict until resolution/TTL |
| `reject` | Terminate an unsupported, contradicted, unsafe, or malformed candidate without truth mutation |

Candidate prose is rewritten into a natural functional module, a title, one
specific knowledge statement, and `verified YYYY-MM-DD`. A separate minimal
source relation retains only enough information to re-open the real source for
future revalidation; the full evidence envelope is not copied into current
knowledge.
The model organizes modules from the whole project's verified knowledge; there
is no hard-coded module allowlist. Internal storage kinds and claim types may
guide reasoning and evidence requirements, but they never become headings such
as “stable operation rules” or other generated taxonomy. Session
narration such as "the user asked to view all memories" is not stored. If the
source explicitly establishes a durable preference, the assimilated statement
describes the future behavior instead, for example:

```text
When presenting a memory audit, provide a complete itemized list rather than
only aggregate counts.
```

New autonomous distill must not use `provisional` as a generic destination for
uncertain content. Ambiguous or under-scoped items stay in the job lifecycle,
outside normal truth, until they resolve or expire.
The detailed transition and legacy migration plan is in
[knowledge-truth-separation.md](roadmap/knowledge-truth-separation.md).

**Quality signals:** garbage writes approach zero; current knowledge is neither
broad, duplicated, nor mixed; design requirements do not masquerade as current
implementation; terminal processing detail is cleaned safely; and candidates,
session history, and handoffs remain separate from long-term knowledge.

## 4. Retrieval and use

**Unit:** one task or query together with the long-term knowledge returned for
it.

**Owns:** project isolation, relevance ranking, current-validity preference,
duplicate collapse, a clean default projection, and bounded outcome feedback.
**Does not own:** displaying transcripts, candidates, Notes, Answer Packets,
audit reasons, identifiers, hashes, or historical versions in normal results.

Normal wake/search reads current rows from SQLite, directly or through a
derived index whose generation matches the current database state, and returns
a clean memory projection:

```text
title + knowledge body
```

Default results do not include session/job/candidate/knowledge/evidence/source
IDs, hashes, locators, reason codes, provider receipts, or storage-kind names.
Rejected, deferred, provisional, and superseded rows are not normal retrieval
truth. Equivalent current statements collapse to one result before the final
ranking.

This is also a candidate-source rule: normal memory search and wake select from
SQLite current knowledge or its validated derived index,
while verbatim observations remain available through explicit raw, timeline,
observation, and audit paths. Raw evidence does not compete with long-term
knowledge in the same default top-k set.

Explicit source or session-history requests may join a knowledge result to its
minimal source locator, retained job receipt, Session Note/Packet, or bounded
undo version when those records still exist. Processing detail is not another
memory product and is not retained forever merely because a job once ran.

Retrieval feedback (`used`, `ignored`, `misleading`, stale/conflict signals)
feeds later maintenance and assimilation decisions. Missing feedback is never
interpreted as approval.

**Quality signals:** recall, precision, deduplication, minimum sufficient
context cost, and zero audit-noise or obsolete-knowledge leakage by default.

### Quality attribution

| Observed problem | First module to improve |
|---|---|
| A durable point was missed | 1. Extraction |
| Stored knowledge is unsupported or stale | 2. Verification |
| Stored knowledge is garbage, duplicated, broad, or mixed | 3. Assimilation |
| Existing knowledge is missing or normal results are dirty | 4. Retrieval and use |
| A session/revision is missing, a receipt is unreliable, or a source is removed unsafely | 0. Session intake and lifecycle |

## Core governance feedback: Review and Dream

`review` and `dream` are core cross-module capabilities around stages 3--4,
not a fifth linear knowledge stage and not operator-only maintenance.

```text
4. retrieval/use
-> useful / ignored / misleading / stale feedback
-> review / Dream
-> re-verify
-> refine, merge, supersede, or retire
-> 3. assimilation
```

- **Review** is the human correction and adjudication path: confirm, reject,
  undo, correct, or supersede a memory when the evidence or product boundary
  requires a person to decide.
- **Dream** is the automated governance path: discover stale, duplicate,
  conflicting, mergeable, or replaceable knowledge, then route a proposal back
  through verification and assimilation. Dream does not turn a discovery into
  unverified current truth.

Audit receipts cross all five modules rather than forming a sixth stage:

```text
0 intake receipt -> 1 extraction coverage -> 2 verification evidence
-> 3 assimilation decision and lineage -> 4 retrieval/use feedback
```

The public actions map to the modules as follows:

| Action or entry point | Architecture position |
|---|---|
| Hooks, detached worker, archive maintenance | Stage 0: session intake and lifecycle |
| `distill` | Orchestrates stages 1--3 |
| `wake`, `search`, `search-all` | Stage 4: retrieval/use |
| `review`, `dream` | Core governance-feedback loop across stages 3--4 |
| `status` | Summarizes actual state across stages 0--4 |

Raw/timeline/audit reads, runtime reset, and storage repair remain explicit
operator or audit actions. They do not redefine the long-term knowledge model.

## Public and storage boundaries

- Users see one product concept: long-term memory.
- Internal memory/rule/relation kinds may remain for storage and behavior, but
  they do not justify separate user-facing products.
- SQLite `knowledge_entries` is the only authority for current project
  long-term knowledge.
- A current row has a stable hidden ID, project, natural module path, specific
  title, one-statement body, and verification date. Only module/title/body and,
  in full views, the date are user-visible.
- Candidate, verification, proposed-decision, and recovery records are
  job-scoped processing material. Active/retryable/unresolved jobs may retain
  them; successful terminal jobs clean them only after durable outcome proof.
- A minimal source relation is durable only so Review/Dream can re-open the
  actual source. It is not a copy of the full job evidence envelope.
- Revalidation reopens the current underlying source. An old audit result or
  hash explains how to find that source; it cannot prove the source still says
  the same thing.
- Review undo retains at most the newest 32 project mutations and the version
  snapshots they still reference. Older mutation/version rows are removed in
  the same SQLite transaction as the new mutation; they are not an unlimited
  audit history.
- Session Notes are readable processing records, not truth.
- FTS, vector data, compact views, Markdown, JSON, and text summaries are
  rebuildable projections of SQLite current knowledge. They cannot overwrite
  SQLite truth.
- Human review remains an audit, correction, conflict-resolution, and undo
  surface, not the default write gate for ordinary verified memory.

This keeps the useful upstream separation of claim extraction, evidence
verification, stable knowledge editing, and final use without restoring packet
workspaces, a parallel promotion store, or mandatory helper loops.
