---
name: grill-with-docs
description: Explicit human-in-the-loop design interrogation for durable product, architecture, schema, policy, or terminology decisions. Use only when the user asks to grill, stress-test, or clarify a design while maintaining project glossary or ADR documentation; do not invoke for unattended distill or ordinary implementation.
---

# Grill With Docs

Clarify one decision at a time, verify facts from primary local evidence, and
record only confirmed terminology or hard-to-reverse decisions. Keep project
docs canonical; harness-mem stores evidence-backed pointers, not a second copy.

## Workflow

1. Read the relevant code, tests, existing glossary/context document, ADRs, and
   confirmed harness-mem context. Resolve factual questions yourself.
2. Map the unresolved decision tree. Start with the decision that blocks the
   most downstream branches.
3. Ask exactly one unresolved decision question. Include a recommended answer
   and the concrete trade-off behind it. Wait for the user's answer.
4. Challenge vague or conflicting terminology with concrete edge cases. If the
   user's language conflicts with code or existing docs, show the evidence and
   ask which source should change.
5. Continue until the user confirms shared understanding. Do not implement the
   design before that confirmation.
6. Update documentation incrementally after each confirmed decision:
   - add glossary terms to the project's existing domain/context document;
   - create a context document only when the project has no equivalent and a
     durable term has actually been agreed;
   - create an ADR only when the decision is hard to reverse, surprising
     without context, and the result of a real trade-off.
7. Run the project's normal documentation checks. Then apply the candidate
   admission check defined by `hm-distill` and call
   `govern_memory(action="suggest")` with a project-relative document path and
   current content hash.

## Boundaries

- Ask the user about preferences, intent, and irreversible choices. Look up
  repository facts, versions, test status, and existing decisions instead of
  asking the user.
- Do not run this interactive flow inside wake, automatic backlog draining, or
  ordinary zero-candidate review.
- Do not write tentative statements to context docs, ADRs, Memory, or Rule.
- Do not duplicate full ADR or glossary content in memory. Store the stable
  conclusion and provenance pointer needed for future retrieval.
- If the discussion produces no durable decision, finish without creating docs
  or memory.

## Completion

Finish with:

- decisions confirmed and remaining open questions;
- glossary/ADR files created or updated, if any;
- evidence checked and contradictions resolved;
- memory candidates suggested, narrowed, deferred, or intentionally omitted.

For provenance or upstream upgrade work, read
[references/upstream.md](references/upstream.md).
