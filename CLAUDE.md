# CLAUDE.md (Protocol)

> Project protocol: this file defines how agents and contributors work in this repository. Verifiable repository facts belong in `AGENTS.md`; product and developer-experience direction belongs in `DESIGN.md`.

## Language and Tone

- Keep root AI entry documents in English, matching the primary `README.md` body.
- Reply in the user's language unless they request another language.
- Be direct, evidence-based, and concise. Explain internal IDs only in explicit audit views.
- When a user says a term is too complex, remove it and use ordinary language. Do not coin a replacement label unless the user explicitly asks for one.
- Use “Agent” consistently with the public documentation where it names supported agent clients.

## Conflict Resolution

Apply instructions in this order:

1. Explicit user instruction in the current turn.
2. Root `AGENTS.md` for repository facts and executable commands.
3. Root `CLAUDE.md` for collaboration protocol.
4. Root `DESIGN.md` for product, documentation, and DX decisions.
5. A matching `steering/*.md` rule when such a scoped rule exists.
6. Host-specific adapter or command files.
7. Background material under `docs/`.

When sources disagree, inspect current code, manifests, tests, and runtime evidence. Do not silently choose a stale document.

## Decision Priorities

1. Directly verifiable user outcomes.
2. Evidence integrity and data safety.
3. Compatibility across supported hosts and existing stores.
4. Testability and deterministic replay.
5. Readability and bounded module ownership.
6. Simplicity and reversibility.

## Working Method

- Inspect the implementation and its tests before changing behavior.
- Prefer the smallest coherent change that preserves public and stored-data compatibility.
- Keep canonical behavior in runtime modules; generated command, skill, descriptor, and documentation mirrors must not become independent truth sources.
- Update existing modules and documents before creating a parallel product path.
- Do not introduce a second CLI, distillation path, review policy, hook lifecycle, or storage authority when an existing canonical path owns that behavior.
- Preserve unrelated working-tree changes. Never reset or overwrite user work to simplify a task.

## Architectural Boundaries

- Stage 0 owns session intake, immutable revisions, chunks, jobs, receipts, retries, and source lifecycle.
- Extraction, verification, assimilation, and retrieval operate on independent promotion points rather than treating a session as one indivisible fact.
- Review and Dream feed correction, conflict, staleness, and usage evidence back into verification and assimilation.
- Observations and transcripts remain evidence. Only governed, current truth belongs in normal wake and search results.
- MCP is the normal agent-facing memory surface. CLI commands remain setup, diagnosis, integration, and maintenance surfaces unless the repository explicitly documents otherwise.
- Host adapters may differ in installation and event schema, but they converge on shared runtime actions and evidence contracts.

## Evidence and Trust

- Treat generated summaries, previous agent statements, and transcript-only claims as provisional until their evidence is checked.
- Repository claims require current project-relative evidence. User preferences and decisions require an explicit user-authored statement.
- Missing, changed, stale, or contradicted evidence must remain visible; do not upgrade it to truth through confident wording.
- Do not expose transcript content, private spans, internal IDs, or audit metadata in default user summaries.
- Keep one verifiable fact per readable memory item and include its verification date or status where the product contract requires it.

## Implementation and Validation

- Add or update focused tests for every changed contract or boundary.
- Run the narrowest relevant tests first, then the appropriate repository lane from `AGENTS.md`.
- Before a check that calls a real model CLI, run one smallest representative
  model check for the current code and configuration. Do not retry it
  automatically or continue with other model samples after a failure or timeout.
- Run one full Hook chain only after that model check passes. Run broad test and
  release gates only after the full Hook chain passes.
- A code or relevant configuration change invalidates earlier model and Hook
  evidence. Do not combine successful pieces from different runs into one claim.
- Run `python code/scripts/ensure_mcps_canonical.py` when MCP tool specifications or generated descriptors change.
- Validate host-specific changes against their checked-in fixtures and negative project-isolation cases.
- Do not infer that a passing mock proves a native host, hook, provider, storage, or cleanup outcome.

## User-Outcome Claims

- Before saying a user-visible runtime result is complete, use `.codex/outcomes.json` through the repository's outcome verifier.
- A file, configuration entry, passing unit test, queued job, or `completed` flag is supporting evidence unless it is itself the requested outcome.
- Hooks and asynchronous workers require a fresh receipt produced after the relevant trigger.
- Generated Notes and processed data must exist, contain meaningful content, and be readable through their intended path.
- Report verification honestly as `passed`, `partial`, `failed`, or `blocked`. Never rename a partial result as complete.

## Runtime and Data Safety

- Do not mutate live runtime data, local memory stores, transcript sources, Notes, receipts, or generated audit reports during unrelated development work.
- Use documented dry-run or preview modes before maintenance or deletion operations.
- Never delete a shared history container to remove one session.
- Preserve auditability when correcting, superseding, migrating, or removing stored knowledge.
- Do not enable autonomous model processing or source deletion without the explicit authorization required by the public configuration contract.

## Documentation Responsibilities

- Keep `README.md` and `README.zh-CN.md` aligned when public behavior changes.
- Update the specific lifecycle, compatibility, or roadmap document that owns a changed contract.
- Keep commands, skills, and host mirrors synchronized with their canonical source.
- Use `AGENTS.md` for facts, `CLAUDE.md` for collaboration policy, and `DESIGN.md` for product/DX direction; do not duplicate long background explanations across all three.

## Harness Collaboration

- `/harness-init` is an agent-native Ground → Read → Draft → Confirm → Apply workflow.
- It never requires Node, npm, npx, tsx, a package manager, or `.harness/runs/` artifacts.
- Nothing is written before the user confirms the per-file summary with `yes`.
- Apply only the confirmed draft bytes and re-read each written file afterward.
- Use incremental section patches for existing user-owned root truth files; never overwrite an unmanaged file wholesale.
