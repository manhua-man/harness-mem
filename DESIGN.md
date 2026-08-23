# DESIGN.md (Design)

> Product and developer-experience direction for `harness-mem`. Repository facts belong in `AGENTS.md`; collaboration protocol belongs in `CLAUDE.md`.

## Design Intent

- **Audience:** developers and agent users who need trustworthy project memory without managing a second knowledge application.
- **Primary experience:** quiet infrastructure surfaced through compact MCP responses, host-native commands, actionable diagnostics, and auditable drill-downs.
- **Core promise:** make the current trustworthy result obvious while keeping evidence, uncertainty, correction, and undo close at hand.
- **Not this:** a dashboard-first product, a stream of internal IDs, or an opaque “AI remembered it” experience.

## Experience Principles

1. **Outcome before machinery** — lead with what is ready, missing, blocked, or changed.
2. **Progressive disclosure** — default views stay compact; evidence, receipts, IDs, and raw transcripts appear only in explicit audit flows.
3. **Trust is visible** — distinguish current truth, provisional evidence, stale material, and failed verification in language and structure.
4. **One daily model** — supported hosts expose the same daily actions even when their native command or hook formats differ.
5. **Safe by default** — preview destructive maintenance, retain uncertain sources, and make authorization boundaries explicit.
6. **Repairable, not magical** — errors name the failed boundary, preserved state, and next safe action.

## Information Architecture

Present daily actions around three user intents:

- Continue work with `wake` and task-aware `search`.
- Preserve a reusable result through `distill`, verification, and assimilation.
- Audit, correct, undo, or refresh knowledge through `review` and Dream.

`status` is the diagnostic overview. Raw evidence, candidate detail, storage repair, and cleanup are drill-down or operator surfaces rather than primary navigation.

## CLI and MCP Output

- Put the verdict or next action in the first readable block.
- Prefer stable labels and short lists over wide tables.
- Keep default summaries free of transcript, session, job, candidate, memory, evidence, and source IDs.
- Show exact commands in code formatting and keep them copyable.
- For long-running or asynchronous work, distinguish queued, running, persisted, verified, deferred, and failed states.
- Pair failures with a bounded recovery action; never imply that retrying will be harmless when it may mutate or delete data.
- Use machine-readable JSON for automation and concise prose for human-facing summaries.

## Host-Native Commands

- Preserve each host's native invocation style while keeping action names and semantics aligned.
- Do not make users learn internal MCP server aliases.
- Commands should resolve the active project from the workspace before asking for a project name.
- Keep setup and repair instructions out of the normal daily loop unless diagnosis proves they are needed.
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
- Keep dense audit text readable; do not shrink typography to fit a fixed card or table.

## Layout and Components

| Component | Use | Required behavior |
| --- | --- | --- |
| Outcome summary | Status, distill, review, verification | Verdict first; name remaining gaps |
| Next-action block | Setup and diagnosis | One safe primary action with a reason |
| Evidence badge | Truth and audit views | Text label for verified, provisional, stale, or contradicted |
| Progress state | Hooks and workers | Separate queued, running, persisted, and verified |
| Confirmation summary | Destructive or file-writing work | Exact targets and effects before confirmation |
| Drill-down hint | Compact MCP responses | Name the tool or action and why it is useful |

- Keep the main path linear and compact.
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
- Do not create a new host experience that changes the meaning of the shared daily actions.

## Change Log

| Date | Change | Evidence |
| --- | --- | --- |
| 2026-08-17 | Initial DX and visual design entry | `README.md`, `docs/assets/harness-mem-logo.svg`, `docs/ide-hook-adapter-matrix.md`, and host command surfaces |
| 2026-08-22 | Refreshed the 0.9.25 public diagram system for 900px readability, five-module semantics, queue boundaries, and storage authority | Four public README SVG diagrams and localized alt text |
