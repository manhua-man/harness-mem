# Distillation Rules

> Stages 1--4 below are the released `0.9.20` knowledge-adoption contract.
> They run after Stage 0 (session intake and lifecycle). Extraction remains
> lossless; assimilation dispositions are runtime claims verified by their
> owning tests and outcome probes.

## Stage 0--4 Boundary

Treat the full product lifecycle as five responsibilities:

```text
0. session intake and lifecycle
-> 1. extraction -> 2. per-point verification
-> 3. assimilation -> 4. retrieval/use
```

- Stage 0 owns supported-host intake, project authorization, immutable source
  revisions, job/receipt lifecycle, and safe source retention/cleanup. It does
  not decide memory content.
- Keep the existing lossless extraction path. One session may yield zero to
  twelve independently addressable promotion points.
- Verify every point independently. `ANSWERED` means the evidence question is
  answered; it does not by itself authorize durable memory.
- Assimilate every verified point as one of `add`, `refine`, `confirm`,
  `supersede`, `no_write`, `handoff`, `defer`, `conflict`, or `reject`.
- Derive the session-level `promotion_decision` from point outcomes. Never let
  one unfinished or rejected point suppress unrelated ANSWERED durable points.
- Normal retrieval uses only current canonical prose. Audit identifiers and
  evidence metadata remain outside readable memory.

`review` and `dream` are governance feedback around stages 3--4: use feedback
can trigger re-verification and then refine, replace, merge, or retire current
memory. They are not a fifth linear stage.

## Classify Before Suggesting

Do not ask whether text should be promoted until its destination is clear.

- `govern_memory(action="handoff")`
  - current task state, blockers, unfinished work, and concrete next steps
  - temporary environment details needed to resume the task
- `govern_memory(action="suggest", arguments.kind="memory")`
  - durable architecture facts, decisions, file maps, workflows, and reusable
    debugging lessons
- `govern_memory(action="suggest", arguments.kind="rule")`
  - cross-cutting guidance that should change future Agent behavior in the repo
- `govern_memory(action="suggest", arguments.kind="relation")`
  - explicit ownership, dependency, replacement, conflict, or lineage relations
- repo docs, comments, or tests
  - system behavior and business constraints that belong with the implementation
- no durable write
  - one-off narration, transient output, unsupported guesses, and duplicated
    instructions

The hm-distill skill does not maintain a parallel knowledge base, promotion
workspace, or draft-file truth store. A session note is a readability artifact,
never a truth store.

## Suggest

- Suggest stable workflows that can be reused across future tasks.
- Suggest commands only when they solved a recurring problem or exposed the
  right files efficiently.
- Suggest file maps when the complete session established clear ownership.
- Suggest anti-patterns only when the failure mode is reusable and actionable.
- Suggest product decisions, requirements, and roadmap constraints when they
  are supported by the complete source revision.
- Use a handoff rather than durable memory for unfinished or short-lived work.

## Reject As Noise

- Base instructions, developer prompt boilerplate, token accounting, rate
  limits, and routine Agent orchestration.
- Duplicate user messages that only mirror IDE context blocks.
- Long tool output dumps that do not establish a reusable fact or failure mode.
- Temporary branch names, timestamps, ports, PIDs, and transient paths unless a
  durable rule genuinely depends on them.
- Claims inferred from only one chunk when later chunks could change the result.
- The current distillation workflow itself, unless harness-mem is the project
  being documented.

## Evidence Gate

- Read and checkpoint every expected chunk before creating final candidates.
- Cite source revision and content-addressed session evidence for each candidate.
- Reconcile contradictions across chunks instead of choosing the convenient
  version.
- Mark unfinished work explicitly in final-session review.
- External, date-sensitive, security-sensitive, or policy claims require
  traceable external evidence before confirmation.
- Use `promotion_decision=promote` only when evidence and the last turn are answered
  and contradictions/unfinished work are empty.
- Use `promotion_decision=partial` when Answered durable candidates coexist with
  unrelated unfinished work. Candidate auto-review may proceed, but Dream must not run;
  record the unfinished state as a scoped handoff.
- Missing current repository proof is an answer-evidence route, not a zero-candidate
  justification. A detected signal may be downgraded only with a signal-specific reason.
- Source authenticity and durability are separate. A matching user-role exchange
  proves that the user said something; assimilation must still decide whether it
  is an explicit future preference/decision or only a one-off request.
- Bind evidence and Answer Gate status to one promotion point, not just the
  enclosing session or job.
- Keep reference integrity, semantic support, and long-term utility separate.
  The first two belong to verification; the third belongs to assimilation.
- `NOT_APPLICABLE` never authorizes durable admission. A durable user
  preference must be supported as an `ANSWERED` user statement.

## Assimilation

- `add`: write a new canonical statement only when no equivalent current truth
  exists.
- `refine`: replace an overbroad or incomplete current statement and preserve
  supersede lineage.
- `confirm`: keep the existing truth and record confirmation without adding a
  duplicate row.
- `supersede`: end the old truth's current validity and link the verified
  replacement.
- `no_write`: keep one-off requests, task narration, explanations, counts, and
  audit navigation in the Note/audit only.
- `handoff`: persist concrete unfinished state outside long-term truth.
- `defer` or `conflict`: keep unresolved material outside normal retrieval;
  never downgrade it into a low-weight truth row merely to finish the job.
- `reject`: terminate unsupported, contradicted, unsafe, or malformed content
  without truth mutation.

Before any insert, compare the normalized point with current project truth.
The absence of an exact text match is not sufficient proof that the knowledge
is new.

Use this comparison order: explicit temporal replacement (`supersede`),
incompatible current claims without proven order (`conflict`), semantic
equivalence (`confirm`), compatible precision/completeness improvement
(`refine`), then no meaningful match (`add`). Assign a functional module/topic
to every canonical statement so human-readable views do not group by session or
platform.

## Candidate Quality

- Rewrite the claim as a concise normalized statement, not a session story.
- Keep one candidate to one durable claim.
- A single session may promote several candidates. Do not collapse unrelated
  facts into one omnibus memory and do not force a one-memory-per-session shape.
- Narrow environment-specific claims instead of pretending they are universal.
- Merge semantic duplicates through stable candidate identity.
- Use `arguments.kind="rule"` only when future default Agent behavior should change.
- A rule must state both when it applies and what behavior is required. Reject
  rows whose pattern and trigger both merely describe a situation.
- Do not treat "the user requested X in this turn" as a durable preference. An
  explicit future/default/remember instruction or equivalent repeated correction
  is required before normalizing it into future behavior.
- Use module docs/tests for code behavior rather than turning implementation
  facts into collaboration rules.
- Do not call confirm/reject/replace tools from the default distill path.
- In the default user-visible result and readable session note, render each
  promoted memory as `title + one verifiable fact + verification date/status`.
- Keep session, job, candidate, memory, evidence, and source IDs out of readable
  memory prose. Preserve them only in the audit record and explicit audit views.

## Review Outcomes

- Extraction review: `admit`, `narrow`, `defer`, or `reject` determines whether
  a signal becomes an independently verified candidate.
- Assimilation review: `add`, `refine`, `confirm`, `supersede`, `no_write`,
  `handoff`, `defer`, `conflict`, or `reject` determines its durable effect.
- A valid `confirm` and a valid `no_write` are successful terminal outcomes even
  though neither inserts a new truth row.

`finalize_session_distill` is the only lossless-session commit point for an
explicit active-host distill. It may run scoped low-risk auto-review only after
structural and semantic gates pass; it does not start Dream. A Hook instead
wakes Dream with its persisted session source. `/hm:review` remains the audit,
correction, undo, and trust-upgrade surface.
