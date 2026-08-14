# Session Lifecycle and Four-Stage Memory Adoption

This document owns the conceptual contract for turning session evidence into
usable long-term memory. The full product path starts before extraction: it
must first safely receive, version, and finish a native session. The 0.9.12
runtime already implements much of that lifecycle, lossless extraction,
content-addressed evidence validation, governed truth, and normal retrieval.
The 0.9.13 contract and 0.9.14 runtime implement the assimilation boundary for
new autonomous distill jobs. The separately planned 0.9.15 work covers clean
default retrieval and governed convergence of historical provisional rows.

```text
0. session intake and lifecycle
-> 1. extraction -> 2. verification -> 3. assimilation -> 4. retrieval/use
```

Stages 1--4 are the knowledge-adoption stages. Stage 0 is the runtime
foundation that makes their inputs and receipts trustworthy. They are
deliberately different responsibilities:

- session intake/lifecycle owns the native session and its processing state;
- extraction finds possible promotion points;
- verification establishes what each point's evidence supports now;
- assimilation decides what the project should remember and reconciles it with
  current truth;
- retrieval/use exposes current canonical memory to future tasks and records
  bounded outcome feedback.

## 0. Session intake and lifecycle

This stage answers: which native session is this, who/which project may use it,
is its source complete, and has its processing reached a trustworthy terminal
state? Its unit is one **session plus immutable session revision**, not a memory
claim.

It owns:

- host intake from Codex, Claude, Cursor, and other supported adapters;
- project recognition and authorization boundaries;
- immutable revisions, lossless chunks, incremental versions, and integrity
  checks;
- queueing, leases, retries, concurrency control, and idempotency;
- distill-job creation, terminal receipts, and Hook/provider binding; and
- retained-source policy and fail-closed safe cleanup.

Stage 0 must not decide what the project should remember. It supplies complete,
authorized source revisions and durable receipts to later stages.

## 1. Extraction

Extraction remains the existing lossless session path:

```text
native session -> immutable revision -> ordered chunks -> coverage-first
manifest -> semantic/raw drilldown -> final-session review -> 0..12 candidates
```

One session may contain more than one promotion point. The candidates remain
independently addressable; the session summary is separate and never substitutes
for candidate content.

Extraction optimizes bounded recall. It may surface a one-off request or
temporary state as a signal, but that signal is not yet durable memory.

## 2. Per-point verification

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

## 3. Assimilation

Assimilation is the semantic and governance boundary between verified claims
and current project truth.

```text
ANSWERED candidate
  -> durability and destination decision
  -> canonical rewrite
  -> current-truth semantic match
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
5. Which mutation, if any, preserves one current canonical statement and full
   historical auditability?

Normal outcomes are:

| Outcome | Effect |
|---|---|
| `add` | Insert one new canonical memory |
| `refine` | Write a narrower or more complete replacement and supersede the old row |
| `confirm` | Keep the current row and attach confirmation evidence; create no duplicate |
| `supersede` | End the old row's current validity and link the replacement |
| `no_write` | Keep the information only in the Session Note/audit |
| `handoff` | Persist unfinished state outside long-term truth |
| `defer` | Keep a non-readable candidate until proof/scope is resolved |
| `conflict` | Block automatic truth mutation and preserve explicit conflict evidence |
| `reject` | Terminate an unsupported, contradicted, unsafe, or malformed candidate without truth mutation |

Candidate prose is rewritten into `title + one canonical statement`. Session
narration such as "the user asked to view all memories" is not stored. If the
source explicitly establishes a durable preference, the assimilated statement
describes the future behavior instead, for example:

```text
When presenting a memory audit, provide a complete itemized list rather than
only aggregate counts.
```

New autonomous distill must not use `provisional` as a generic destination for
uncertain content. Ambiguous or under-scoped items stay outside normal truth.
The detailed transition and legacy migration plan is in
[0.9.13-four-stage-memory-quality.md](roadmap/0.9.13-four-stage-memory-quality.md).

## 4. Retrieval and use

Normal wake/search reads only current canonical truth and returns a clean
memory projection:

```text
title + statement + necessary scope/freshness
```

Default results do not include session/job/candidate/memory/evidence/source
IDs, hashes, locators, reason codes, provider receipts, or storage-kind names.
Rejected, deferred, provisional, and superseded rows are not normal retrieval
truth. Equivalent current statements collapse to one result before the final
ranking.

This is also a candidate-source rule: normal memory search and wake select from
current canonical truth, while verbatim observations remain available through
explicit raw, timeline, observation, and audit paths. Raw evidence does not
compete with canonical memory in the same default top-k set.

Explicit audit requests may join the canonical result to provenance,
verification, lifecycle, and undo records. Audit detail is not another memory
product or truth store.

Retrieval feedback (`used`, `ignored`, `misleading`, stale/conflict signals)
feeds later maintenance and assimilation decisions. Missing feedback is never
interpreted as approval. `review` and `dream` are this governance feedback
loop around stages 3--4, not a fifth linear knowledge stage.

## Public and storage boundaries

- Users see one product concept: long-term memory.
- Internal memory/rule/relation kinds may remain for storage and behavior, but
  they do not justify separate user-facing products.
- The canonical SQLite store remains authoritative.
- Session Notes are readable processing records, not truth.
- Derived indexes and optional Markdown views are projections, not authorities.
- Human review remains an audit, correction, conflict-resolution, and undo
  surface, not the default write gate for ordinary verified memory.

This keeps the useful upstream separation of claim extraction, evidence
verification, stable knowledge editing, and final use without restoring packet
workspaces, a parallel promotion store, or mandatory helper loops.
