# Distillation Rules

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
- `promotion_decision=promote` is valid only when evidence and the last turn are
  answered and contradictions/unfinished work are empty.

## Candidate Quality

- Rewrite the claim as a concise normalized statement, not a session story.
- Keep one candidate to one durable claim.
- Narrow environment-specific claims instead of pretending they are universal.
- Merge semantic duplicates through stable candidate identity.
- Use `arguments.kind="rule"` only when future default Agent behavior should change.
- Use module docs/tests for code behavior rather than turning implementation
  facts into collaboration rules.
- Do not call confirm/reject/replace tools from the default distill path.

## Review Outcomes

- `admit`: create the appropriately typed candidate.
- `narrow`: rewrite scope, then create the candidate.
- `defer`: leave the claim pending or record unfinished work in a handoff.
- `reject`: create no candidate.

`finalize_session_distill` is the only lossless-session commit point. It may run
scoped low-risk auto-review and Dream only after structural and semantic gates
pass. `/hm:review` remains the audit, correction, undo, and trust-upgrade surface.
