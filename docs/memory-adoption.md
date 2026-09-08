# Session Lifecycle and Five-Module Memory Adoption

This document owns the conceptual contract for turning session evidence into
usable long-term memory. The full product path starts before extraction: it
must first safely receive, version, and finish a native session. The current
source is `0.9.28`; published artifacts are listed on the GitHub Releases page. SQLite truth
separation landed in `0.9.20` and was extended and hardened through `0.9.28`.
Since `0.9.26`, authorized background
work moved to `enabled=true` plus the selected host CLI; legacy HTTP provider
profiles no longer authorize the product path. See `docs/background-memory.md`.
The runtime implements lifecycle, lossless extraction, content-addressed evidence
validation, current knowledge, and normal retrieval. Raw Observation content
and internal processing details appear only in explicit diagnostic views.
Legacy `MemoryEntry` remains readable only for compatibility, while SQLite
`knowledge_entries` is the only authority for current long-term knowledge.
Candidate, evidence, and proposed-decision records are job-scoped processing
material retained only for retry, unresolved work, and bounded diagnosis.
Current search reads SQLite deterministically; optional FTS/vector data remains
a rebuildable optimization. Markdown is rendered on demand for reading or
export and never becomes a write path. The frozen six-session oracle, real Hook,
and runtime checks originally passed for `0.9.20`; the current
release boundary is tracked in `roadmap.md`.
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
- retained-source policy and cleanup that stops when safety cannot be proved.

Stage 0 diagnostics may provide a bounded, human-readable pending-session view
through operator surfaces: project, source host, capture time,
per-session lifecycle state, progress, and the responsible Agent class. The
daily project check does not carry that diagnostic object; it only reports
whether memory is ready or which short recovery action is needed. Neither
surface exposes lease tokens, transcript text, or filesystem paths by default.

**Does not own:** deciding what the project should remember. It supplies
complete, authorized source revisions and durable receipts to later stages.

**Codex host-event boundary:** a Codex rollout is not itself a transcript. For
new Codex revisions, the ledger persists only the normalized user/assistant
conversation; a Desktop delegation record contributes only its explicit user
input. Host rules, tool schemas, plugin lists, runtime state, and tool output
remain in the native host file and never become extraction evidence. The native
file's content hash is retained only for safe cleanup comparison. This keeps
the evidence source complete for the conversation without turning the host
envelope into project knowledge.

**Quality signals:** no missing session, missing content, or duplicate work;
reconstructable source and revisions; reliable terminal state across retries;
no source deletion outside policy; and receipts demonstrably bound to their
session and job.

## 1. Extraction

**Unit:** every independently addressable candidate promotion point found in the session
from one session.

**Owns:** high-recall discovery from the complete source and a source location
for every candidate. Its output is a claim to verify plus evidence locators.
**Does not own:** evidence validation, assimilation disposition, final title,
project module organization, or writes to long-term knowledge.

The existing lossless session path remains:

```text
native session -> immutable revision -> ordered chunks -> coverage-first
manifest -> semantic/raw drilldown -> final-session review -> every independently useful candidate
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
content-free `verification_refs`; local harness-mem code re-reads the current
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
| `STALE` | A content-addressed source changed after the claim was formed | Reject or replace |
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

An unfinished task envelope is not a project policy. When the only source is a
user request structured as fields such as `Goal`/`Read`/`Write`/`Acceptance`
(or their Chinese equivalents) and the exchange records no assistant outcome,
local harness-mem assigns `NOT_APPLICABLE` even if a model calls it durable.
This protects the knowledge layer from preflight, scope, and one-off execution
instructions; a separately stated continuing design requirement still follows
the ordinary per-point verification path.

A version number described as current inside a historical session proves only
what that session reported at the time. It becomes current project knowledge
only when a current repository file still proves the same version; otherwise
the runtime assigns `NOT_APPLICABLE`.

Verification is independent per promotion point. A session may therefore have
several ANSWERED points, one contradiction, and one unfinished handoff. The
session-level `promotion_decision` is derived from those outcomes; it is not a
single gate that erases the independent results.

Missing evidence, broad conclusions, and genuine product decisions are handled
inside the same admission pass. Only a product or intent decision that evidence
cannot resolve is returned to the user as a question.

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
project-module organization, and transactional current-knowledge changes. A
replacement deletes the old item and writes the new item; invalid knowledge is
deleted. It does not acquire original sources, keep knowledge history, or
expose processing details through normal retrieval.

```text
ANSWERED candidate
  -> durability and destination decision
  -> knowledge-language rewrite
  -> project knowledge-base semantic match
  -> add | refine | confirm | replace | no_write | handoff | defer | conflict
```

It must answer all of these questions:

1. Will this help a future task, or is it only a record of the current task?
2. Is it a project fact, reusable workflow, durable user preference, project
   decision, behavior-changing rule, explicit relation, handoff, or no-write
   item?
3. Can it be stated as one complete, independently useful fact or rule?
4. Does an equivalent, broader, narrower, older, or conflicting current truth
   already exist?
5. Which action, if any, leaves one clear current knowledge statement?

Normal outcomes are:

| Outcome | Effect |
|---|---|
| `add` | Add one atomic item to SQLite current knowledge |
| `refine` | Replace one or more named items with narrower or more complete statements |
| `confirm` | Keep the named current item; create no duplicate |
| `replace` | Delete one or more named current items and write their replacements |
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
When presenting the current memory list, provide every item rather than
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
internal reasons, identifiers, hashes, or old knowledge in normal results.

Normal wake/search reads current rows from SQLite, directly or through a
derived index whose generation matches the current database state, and returns
a clean memory projection:

```text
title + knowledge body
```

Default results do not include session/job/candidate/knowledge/evidence/source
IDs, hashes, locators, reason codes, provider receipts, or storage-kind names.
Rejected, deferred, and unfinished processing rows are not current memory and
are never read by current-memory surfaces. Equivalent current statements collapse to one result before the final
ranking.

This is also a candidate-source rule: normal memory search and wake select from
SQLite current knowledge or its validated derived index,
while verbatim observations remain available through explicit raw, timeline,
observation, and diagnostic paths. Raw evidence does not compete with long-term
knowledge in the same default top-k set.

Explicit source or session requests may join a knowledge result to its minimal
source locator, retained job receipt, or Session Note/Packet when those records
still exist. These are processing details, not another memory product. Old
knowledge versions and knowledge change records are not kept.

For multiple sessions, the normal user-facing result reports only actual
knowledge changes and ordinary reasons for content that was not written. When a
user explicitly requests a full audit, the result may expand to the in-scope
sessions, topics, formed knowledge, supporting session/code/document evidence,
and unfinished items. That report does not claim source cleanup, host-history
cleanup, host restart, or complete code-path verification unless those separate
operations were explicitly authorized and actually performed. Active user
processing may remove the selected session after a successful result; Dream
keeps its source as an archive.

Retrieval feedback (`used`, `ignored`, `misleading`, stale/conflict signals)
feeds later maintenance and assimilation decisions. Missing feedback is never
interpreted as approval.

**Quality signals:** recall, precision, deduplication, minimum sufficient
context cost, and zero internal-noise or obsolete-knowledge leakage by default.

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
not a sixth linear knowledge stage and not operator-only maintenance. There are
two session entry paths: a person can explicitly run `distill` in the active
host, while a Hook records the session and wakes Dream. Hook never performs
semantic work itself.

```text
explicit distill
-> active host reads one session
-> extract -> verify -> assimilate

Hook
-> persist session/revision and job -> source-bound Dream activity
-> Dream reads that session plus project knowledge, sources, and feedback
-> extract or compare -> verify -> assimilate
```

Unattended processing preserves two queues behind that compact flow. The
session processing queue owns one immutable session job; the project governance
queue owns project-wide duplicate, conflict, staleness, source, and retrieval-
feedback checks. One restricted Dream semantic executor may serve both queues,
but they are not the same processing chain. Manual explicit distill bypasses
both background queues and remains in the active host.

- **Review** is the human correction path: confirm, correct, replace, or delete
  a memory when the evidence or product boundary requires a person to decide.
- **Dream** is the only unattended semantic executor. A Hook-started Dream run
  may first process its triggering session, then compare its evidence with the
  whole project's current knowledge, sources, and feedback. It writes only the
  verified result of that extraction/verification/assimilation loop, never an
  unverified discovery. A source-backed recheck may refresh, replace, or
  delete current knowledge only after local harness-mem reopens every named
  complete supported source and explicit background authorization
  (`distill.autonomous.enabled=true`) under the host CLI executor contract
  (`provider.name=<host>_cli` plus a successful Hook re-entry challenge; see
  `docs/background-memory.md`).
  Unsupported, missing, or truncated sources close without changing current
  truth.
- **Session assimilation** evaluates each independently verified point, but a
  single refine or replace decision may remove several current entries and
  write several new entries together. The same current entry may not be reused
  by two separate mutating points in one plan. A provider or transaction
  failure remains a failed, retryable job rather than being relabelled as a
  harmless terminal result.

Runtime checks support all five modules without becoming memory:

```text
0 intake receipt -> 1 extraction coverage -> 2 verification evidence
-> 3 current-memory decision -> 4 retrieval/use feedback
```

Receipts, idempotency keys, retry state, and unfinished work exist only to run
the process safely. They are not knowledge history and do not restore replaced
or deleted memory.

The public actions map to the modules as follows:

| Action or entry point | Architecture position |
|---|---|
| Hooks, archive maintenance | Stage 0: Hooks persist and queue; they do not call a provider |
| `distill` | Explicit human path, orchestrated by the active host across stages 1--3 |
| `wake`, `search`, `search-all` | Stage 4: retrieval/use |
| `dream` | Unattended Hook path and project governance across stages 1--3 and 3--4 |
| `review` | Human correction, conflict resolution, replacement, and deletion across stages 3--4 |
| `get_project_status` | Automatic first-use project and Hook preparation, followed by a short ready/failure message; full diagnosis belongs to `harness-mem doctor` |

Raw/timeline reads, runtime reset, and storage repair remain explicit operator
actions. They do not redefine the long-term knowledge model.

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
- Revalidation reopens the current underlying source. An old check result or
  hash explains how to find that source; it cannot prove the source still says
  the same thing.
- Dream's unattended semantic work uses the **selected host CLI** when
  `distill.autonomous.enabled=true`. Transport and credentials live in that
  host's CLI configuration, not in harness-mem project config. A manually
  requested `distill` remains in its active host and is never silently
  rerouted through background execution.
- New databases do not create `knowledge_versions` or `knowledge_mutations`.
  Existing compatibility tables are not read or written as current memory.
- Session Notes are readable session summaries, not current knowledge or
  knowledge history. Successful user-requested processing removes the selected
  session's Note and source; Dream keeps both as an archive. No session backup
  is created, and the rest of the host history is never cleared.
- FTS, vector data, compact views, Markdown, JSON, and text summaries are
  rebuildable projections of SQLite current knowledge. They cannot overwrite
  SQLite truth.
- Human review remains a correction, conflict-resolution, replacement, and
  deletion surface, not the default write gate for ordinary verified memory.

This keeps the useful upstream separation of claim extraction, evidence
verification, stable knowledge editing, and final use without restoring packet
workspaces, a parallel promotion store, or mandatory helper loops.
