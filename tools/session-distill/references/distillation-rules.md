# Distillation Rules

## Promote

- Promote stable workflows that can be reused across future tasks.
- Promote commands that solved a real problem or exposed the right files quickly.
- Promote file maps when a session clearly revealed where a concern lives in the codebase.
- Promote anti-patterns only when the failure mode is reusable and actionable.
- Promote automation ideas when the same manual pattern appears more than once.
- After promoting to the distillation `knowledge-base.md`, check whether the lesson is broad enough to become a repo-local rule in the active project.

## Classify Before Promoting

Do not ask "should this be promoted?" until you know what kind of thing it is.
Classify the lesson first:

- `distilled/sessions/<session-id>.md`
  - one-off task context
  - temporary parameters, paths, hosts, or values
  - exploratory dead ends and temporary workarounds
- `knowledge-base.md`
  - reusable workflows
  - command patterns
  - file maps
  - debugging patterns
  - automation ideas
- repo-local project rules
  - lessons that should change the AI's default future behavior in the repo
  - collaboration defaults, review heuristics, safety defaults, engineering discipline
- module docs / comments / tests
  - facts about how the system works
  - endpoint semantics, business constraints, field truth tables, state-machine behavior
  - non-obvious code logic that still belongs to the product/system layer rather than collaboration policy

Useful shortcut:

- If the lesson can be phrased as "in this repo, AI should default to ...", consider project rules.
- If the lesson can be phrased as "this system/module behaves like ...", prefer docs/comments/tests.

## Keep Session-Only

- Keep one-off task context in `distilled/sessions/<session-id>.md`.
- Keep environment-specific notes there when they are useful but not stable enough for the shared knowledge base.
- Keep exploratory dead ends there if they explain why the chosen approach is safer.

## Reject As Noise

- Reject base instructions, developer prompt boilerplate, token accounting, rate limits, and repeated commentary updates.
- Reject duplicated user messages that only mirror IDE context blocks.
- Reject long tool output dumps unless they reveal a reusable command, file map, or failure pattern.
- Reject temporary branch names, timestamps, and "what tab was open" details unless a later rule depends on them.

## Promotion Checklist

- Confirm the item is reusable beyond the original session.
- Confirm it is important enough to deserve a higher layer, not just an archival note.
- Rewrite the item as a short normalized rule, not a long story.
- Cite at least one supporting session id.
- If the rule is date-sensitive or environment-sensitive, place it in the volatile watchlist instead of the stable sections.
- Merge duplicate lessons instead of adding a new entry for every session.
- Ask whether the lesson should change default AI behavior for the repo, not just live as archival memory.
- If yes, inspect `AGENTS.md`, `CLAUDE.md`, and `.kiro/steering/*.md` for the right destination file.
- If the rule already exists in project guidance, do not duplicate it; optionally note that the archival lesson reinforced an existing project rule.
- If the destination is clear and the rule is missing, update the repo guidance in the same pass instead of leaving a follow-up note.

## Promote To Project Rules

- Promote to project guidance only when the lesson is cross-cutting, likely to recur, and useful as a future default for coding/review behavior.
- Strong project-rule candidates usually satisfy most of these:
  - recurrence: this is not a one-off
  - leverage: future AI behavior should change because of it
  - hiddenness: the code alone does not make it obvious
  - novelty: the repo does not already document it clearly
- Good candidates:
  - rollout and feature-flag discipline
  - DTO / validation / transform contract rules
  - testing and review execution rules
  - repo-wide safety defaults
- Usually not good candidates:
  - one module's request-shape exclusivity
  - endpoint-specific payload semantics
  - narrow business rules that already belong in module docs/tests
  - code-logic descriptions that explain system behavior but do not define collaboration or review defaults

## Decision Policy

- If the destination is clear, promote directly in the same pass.
- If the lesson is clearly module knowledge rather than collaboration policy, document it there instead of escalating to project rules.
- If the boundary is unclear, record it as a promotion candidate with a short rationale and ask for user confirmation before changing repo-wide guidance.

## Destination Hints

- `.kiro/steering/generalbeliefs.md`: engineering discipline, rollout policy, review heuristics, cross-cutting defaults.
- `.kiro/steering/typeserver.md`: TypeScript, NestJS, Jest, DTO, transformer, validation, and test-shape rules.
- Module docs/tests: module-local contracts that should not become repo-wide defaults.

## Suggested Knowledge Sections

- Stable workflows
- Useful commands
- Repo facts and file maps
- Anti-patterns and failure modes
- Skill or automation ideas
- Volatile watchlist
