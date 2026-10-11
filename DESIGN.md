# DESIGN.md (Design)

> Product and developer-experience direction for `harness-mem`. Repository facts belong in `AGENTS.md`; collaboration protocol belongs in `CLAUDE.md`.

## Design Intent

- **Audience:** developers and agent users who need trustworthy project memory without managing a second knowledge application.
- **Primary experience:** quiet infrastructure surfaced through short MCP responses, host-native commands, and useful diagnostics.
- **Core promise:** keep one clear set of current project memories that users can find, correct, replace, or delete.
- **Not this:** a dashboard-first product, a stream of internal IDs, or an opaque “AI remembered it” experience.

## Experience Principles

1. **Result before machinery** — lead with what is ready, missing, blocked, or changed.
2. **Progressive disclosure** — default replies stay short; evidence, receipts, IDs, and raw transcripts appear only when users ask for details.
3. **Trust is visible** — distinguish current memory, temporary material, and failed verification in language and structure.
4. **One daily entry** — supported hosts expose one native entry for ordinary recall, remembering, and correction even when their command or hook formats differ.
5. **Safe by default** — preview destructive maintenance, retain uncertain sources, and make authorization boundaries explicit.
6. **Repairable, not magical** — errors name the failed boundary, preserved state, and next safe action.

## Information Architecture

The default path is: install, run `harness-mem quickstart` once for the Agent
app, then use one global native entry in any project. Codex exposes `$hm`;
other supported hosts expose `/hm`. The first use prepares local memory and
Hooks for the current project. The entry accepts ordinary language for three intents:

- Remember this session.
- How did we solve this before?
- This memory is wrong.

Users describe corrections or deletions by title or content in ordinary language.
They do not need to understand internal components, or supply, copy, or manage memory
IDs. The Agent resolves and verifies tool-returned references within the current
project; it must never guess an ID. If the description does not identify one
target uniquely, preserve the existing memory and explain what cannot be
determined using readable titles or content.

Wake happens with session entry and authorized background organization happens
without becoming a daily checklist. Before each requested action, `hm` performs
only a short project and Hook check. Doctor, raw evidence, candidate detail,
storage repair, and cleanup are diagnostic or operator drill-downs, not primary
navigation. Do not create a parallel “simple mode”; the default path is the
product and uses the same runtime contracts.
Readiness reports memory storage and prepared Hook files, not proof that Hooks
have run. Codex replies include a conditional trust action because file existence
cannot establish whether the user accepted the host's trust prompt; already-trusted
users need not repeat it. Setup failures name the known cause and one safe next step.

## CLI and MCP Output

- Put the verdict or next action in the first readable block.
- Prefer stable labels and short lists over wide tables.
- Keep default summaries free of transcript, session, job, candidate, memory, evidence, and source IDs.
- Describe failures in ordinary language, without internal component names or
  requests for IDs.
- If required instructions cannot be read before work starts, state that no
  memory changed and stop without automatic retries. Do not expose paths/tool
  names or turn unexecuted processing steps into task handoffs. After partial
  saving, show verified saved content separately; do not claim nothing changed.
- Show exact commands in code formatting and keep them copyable.
- For long-running or asynchronous work, distinguish queued, running, persisted, verified, deferred, and failed states.
- Pair failures with a bounded recovery action; never imply that retrying will be harmless when it may mutate or delete data.
- Use machine-readable JSON for automation and concise prose for human-facing summaries.
- For multi-session distillation, report knowledge changes and ordinary no-write reasons by default. Only an explicit full audit expands session/topic-to-knowledge and evidence mapping. A semantic report does not claim physical cleanup, host restart, or full code-path verification.
- In the unreleased session inspection flow, inventory, complete source paging
  and theme coverage are read-only. Label themes as Agent-proposed and incomplete
  source coverage as partial; unknown, malformed and empty sources stay distinct.
- Manual batches freeze the selected project and revisions. Show progress and
  unresolved failures within that scope, and exclude previously completed work
  from this run's knowledge changes. Explicit retry applies only to active
  batches; stopped batches do not silently resume. Completion retains sources.
- The current Agent owns manual work independently of the background CLI.
  Keep fixture evidence, the `manual_session_batch` outcome probe and
  live background acceptance separate; none implies that the others passed.
- An explicit organization request shows the actual saved knowledge in the
  completion reply, in the user's language. Include titles and statements,
  natural module grouping where useful, ordinary no-write reasons and unfinished
  work; a count, test verdict or report link alone does not satisfy this result.
- A failed or ambiguous point must not block other independent, verified points
  from being saved through the existing commit and readback checks. Report what
  was actually saved separately from what remains unfinished; partial saving
  must never be described as all work completed. Shared safety failures such as
  project binding conflicts or failed write readback still stop affected work.
- Users may ask `hm` to show all current project knowledge. Reuse SQLite-backed
  rendering; any Markdown view is an on-demand projection, not a second store
  or a new daily entry. Long views may be paged with their scope made clear.
- Keep the original conversation outcome separate from the result of organizing
  it. A conversation that did not demonstrate persistence can later be saved;
  the completion reply must accurately describe the current write/readback.
- Automatic background success does not generate a new notification stream.
  When the user asks what happened, show the same readable knowledge rather
  than requiring them to locate receipts or understand internal stages.

## Host-Native Commands

- Preserve each host's native invocation style while keeping the `hm` meaning and behavior aligned.
- Make the single normal entry discoverable before any individual action name:
  `$hm` for Codex and `/hm` for other supported hosts.
- Do not make users learn internal MCP server aliases.
- Quickstart installs only the global native entry for the current Agent app.
  It is independent of the current project and does not inspect, add, remove,
  or replace MCP connections.
- The first `hm` use in a project resolves that workspace and prepares its
  project Hooks without reinstalling the global entry.
- Commands should resolve the active project from the workspace before asking for a project name.
- Keep setup and repair instructions out of the normal daily loop unless diagnosis proves they are needed.
- Keep automatic wake and authorized background organization out of the user's
  required daily steps. State their result in ordinary language, and surface
  diagnostic detail only when work needs attention.
- Treat Hook trust or authorization gates as explicit user actions, not generic errors.

## Visual System

The checked-in logo at `docs/assets/harness-mem-logo.svg` is the visual source of truth.

- **Primary text:** slate `#0F172A`.
- **Secondary text:** slate `#475569`.
- **Primary accent:** teal `#0F766E`.
- **Bright accent:** teal `#2DD4BF`.
- **Soft accent:** pale teal `#CCFBF1`.
- **Harness accent:** gold `#C99532`.
- **Surface:** white `#FFFFFF` and cool gray `#F8FAFC`.
- **Border:** `#CBD5E1`.

Use teal for identity and positive forward motion. Use gold sparingly for lineage, connection, or harness motifs. Status colors must still carry text labels; color alone never communicates evidence state.

## Typography

- Product and documentation UI: Inter when available, then the system sans-serif stack used by the logo.
- Commands, paths, IDs, hashes, and structured payloads: a platform monospace font.
- Use sentence case for headings and labels.
- Keep dense diagnostic text readable; do not shrink typography to fit a fixed card or table.

## Layout and Components

| Component | Use | Required behavior |
| --- | --- | --- |
| Result summary | Daily reply, distill, review, verification | Verdict first; name remaining gaps |
| Next-action block | Setup and diagnosis | One safe primary action with a reason |
| Evidence badge | Verification details | Text label for verified, provisional, stale, or contradicted |
| Progress state | Background organization | Use ordinary language to distinguish waiting, processing, saved, and checked |
| Confirmation summary | Destructive or file-writing work | Exact targets and effects before confirmation |
| Diagnostic detail | Doctor and requested details | Keep it out of the daily reply and explain why it is useful |

- Keep the main path linear and short.
- Use tables only for short, repeated-field comparisons.
- Use diagrams for lifecycle, authority, or cross-host relationships that are harder to understand as prose.
- Design public README diagrams for their actual 900px display width: use a
  16px minimum source font, keep labels selectable as native SVG text, and
  prefer several focused lanes over one dense system map.
- Public diagrams use English so the same checked-in asset remains legible in
  both README languages; localized `alt` text explains the relationship.
- Do not use sequential arrows between independent daily intents. Arrows must
  represent a real dependency, queue handoff, or feedback path.
- Keep terminal output narrow enough for ordinary split-pane use.

## Voice

- Calm, precise, and operational.
- Say what evidence established and what remains unknown.
- Prefer “not verified” over speculative reassurance.
- Prefer “retained because…” over silent fail-safe behavior.
- Avoid anthropomorphizing storage or claiming the system “knows” unsupported facts.
- Default summaries should be understandable without knowledge of the internal storage schema.

## Accessibility

- Every status color has a text equivalent.
- Diagrams and visual assets require meaningful alternative text.
- Commands and identifiers remain selectable text rather than image-only content.
- Keep keyboard and terminal workflows complete; visual dashboards must not become the only control surface.
- Maintain readable contrast against white and cool-gray surfaces.
- Avoid motion that is not tied to progress or a state transition.

## Anti-patterns

- Do not expose internal IDs in the default success path.
- Do not present configuration presence as operational success.
- Do not collapse evidence, candidates, and governed truth into one visual state.
- Do not add decorative gradients, glass effects, or dashboard chrome without a product function.
- Do not turn every diagnostic into a persistent warning banner.
- Do not compress long explanations into fixed cards, buttons, or table cells.
- Do not create a new host experience that changes the meaning of the shared `hm` entry.

## Change Log

| Date | Change | Evidence |
| --- | --- | --- |
| 2026-08-17 | Initial DX and visual design entry | `README.md`, `docs/assets/harness-mem-logo.svg`, `docs/ide-hook-adapter-matrix.md`, and host command surfaces |
| 2026-08-22 | Refreshed the 0.9.25 public diagram system for 900px readability, five-module semantics, queue boundaries, and storage authority | Four public README SVG diagrams and localized alt text |
| 2026-09-02 | Updated the current 0.9.26 source diagrams to distinguish source from public release and show project-selected CLI behavior | Four public README SVG diagrams, localized alt text, and current canvas panels |
| 2026-09-03 | Made the one-time Quickstart and the single `$hm`/`/hm` daily entry the default documentation and DX path | `README.md`, `README.zh-CN.md`, and `docs/quickstart.md` |
| 2026-09-03 | Made Quickstart global, moved project Hook preparation to first use, and removed the old action-specific entries | onboarding, command sync, host mirrors, and current docs |
| 2026-09-05 | Reduced the automatic project check to a short usable/failure reply and kept full diagnosis in Doctor | `hm` host mirrors, MCP status response, and current docs |
| 2026-10-07 | Made visible saved knowledge and on-demand current-project reading explicit next-iteration acceptance criteria | User could not see the isolated test result until asking again; `docs/roadmap.md` and `docs/distill-test-plan.md` define verification, not an implementation-complete claim |
