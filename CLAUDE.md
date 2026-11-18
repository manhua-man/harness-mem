# CLAUDE.md (Protocol)

> Project protocol: this file defines how agents and contributors work in this repository. Verifiable repository facts belong in `AGENTS.md`; product and developer-experience direction belongs in `DESIGN.md`.

## Language and Tone

- Keep root AI entry documents in English, matching the primary `README.md` body.
- Reply in the user's language unless they request another language.
- Be direct, evidence-based, and concise. Explain internal IDs only in explicit diagnostic views.
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
3. Supported-host and stored-data behavior within the agreed scope, including explicitly requested cleanup or compatibility removal.
4. Testability and deterministic replay.
5. Readability and bounded module ownership.
6. Simplicity and reversibility.

## Working Method

- Inspect the implementation and its tests before changing behavior.
- Prefer the smallest coherent change for the requested outcome. Preserve public and stored-data compatibility unless changing or removing it is part of the authorized task.
- Keep canonical behavior in runtime modules; generated command, skill, descriptor, and documentation mirrors must not become independent truth sources.
- Update existing modules and documents before creating a parallel product path.
- Do not introduce a second CLI, distillation path, review policy, hook lifecycle, or storage authority when an existing canonical path owns that behavior.
- Preserve unrelated working-tree changes. Never reset or overwrite user work to simplify a task.

## Architectural Boundaries

- Stage 0 owns session intake, immutable revisions, chunks, jobs, receipts, retries, and source lifecycle.
- Extraction, verification, assimilation, and retrieval operate on independent promotion points rather than treating a session as one indivisible fact.
- Review and Dream feed correction, conflict, staleness, and usage evidence back into verification and assimilation.
- Observations and transcripts remain source material. Only current `knowledge_entries` belong in normal wake and search results.
- Replacing knowledge deletes the old row and writes the new row; invalid knowledge is deleted. Do not add knowledge history, archived copies, mutation logs, or undo.
- MCP is the normal agent-facing memory surface. CLI commands remain setup, diagnosis, integration, and maintenance surfaces unless the repository explicitly documents otherwise.
- Host adapters may differ in installation and event schema, but they converge on shared runtime actions and evidence contracts.

## Write Convergence and Budget Evidence

- Current-Agent manual history/review submits one content judgment in each `memory_points[i].review` through the prepared finalization contract. It needs no background executor permission. The runtime binds final text, source identities and target versions; complete-source validation, shared transactions and readback remain mandatory.
- Review the whole fact, its future use and necessary conditions. Replacements explicitly preserve still-applicable meaning; report replacements also confirm the same topic. Do not ask the Agent to repeat output segments, hashes or predecessor statements as another proof. Advanced `final_scope_judgment` and existing governance calls remain compatible when needed, but must not be mixed with the normal `review` contract or replaced by legacy proof strings.
- Report source implementation, isolated fixture evidence, installed host behavior and natural semantic quality separately. An inventory or completed traversal is not cleanup acceptance.
- `task_model_budget.*` caps only background native requests dispatched by this runtime, cumulatively across its task's slices/retries. Report calls, native request seconds, input/output tokens, failures and unknown usage separately from returned context and full user wait. The current Agent's conversation is outside this ledger.
- Ordinary background budgets use cumulative actual native usage, checked before subsequent dispatch; the final invocation may cross a token threshold and contain multiple responses. Defaults: 64 invocations, 3,600 native seconds, 2,000,000 input tokens and 128,000 output tokens. Unknown usage blocks later invocations. Only explicit `task_model_budget.host_max_output_tokens` requests strict native bounds; unsupported or unproved bounds refuse that mode before transport. Do not fabricate capabilities or switch hosts/models.

## Evidence and Trust

- Treat generated summaries, previous agent statements, and transcript-only claims as provisional until their evidence is checked.
- Repository claims require current evidence from the project or from another local repository directory configured by the user. External evidence uses an absolute locator and the checked file digest. It retains the original knowledge owner. User preferences and decisions require an explicit user-authored statement.
- The operator-authorized `source_report` contract may retain a useful, source-checked account of what a native speaker reported, with period and source scope. A report without durable value need not become knowledge. Verifying a report does not verify its external assertion, current implementation, actual execution or user approval. Keep its attribution through assimilation, retrieval, review and Dream; never relabel it as `user_statement` or replace factual knowledge with it.
- Missing, changed, stale, or contradicted evidence must remain visible; do not upgrade it to truth through confident wording.
- Do not expose transcript content, private spans, internal IDs, or diagnostic metadata in default user summaries.
- Keep one verifiable fact per readable memory item and include its verification date or status where the product contract requires it.

## Implementation and Validation

- Choose the smallest verification that covers the actual change and requested user path. Add or update focused tests when behavior or a contract changes; documentation-only work can be checked by rereading the diff and its referenced implementation.
- Run broader suites when the affected scope or release task warrants them. Ordinary development and `hm` inspection/review do not require a separate F2 model preflight or a successful Hook run first.
- Use the current Agent and available tools for completed-history organization, review and correction. The 2026-11-04 user choice prioritizes this path and processed-history cleanup before optional real-time automation. Verify complete sources, point decisions, persisted results and ordinary-search readback; run a separate model CLI or Hook only when that execution path is authorized. Do not require background activation for work the current Agent can complete.
- After a failure or timeout, inspect the failed input and output, locate the cause, and recheck the affected path after correction. Continue independent diagnosis and checks; stop dependent writes when source integrity, ownership or transaction safety is uncertain. Existing task authorization covers relevant retries, not blind repetition or unrelated model runs.
- Old model and Hook reports prove only their recorded code and configuration. Reverify affected claims on current code; an unrelated change does not require repeating every runtime path. Do not assemble separate successes into a claim that an unexecuted complete run passed.
- Run `python code/scripts/ensure_mcps_canonical.py` when MCP tool specifications or generated descriptors change.
- Validate host-specific changes against their checked-in fixtures and negative project-isolation cases.
- Do not infer that a passing mock proves a native host, hook, provider, storage, or cleanup outcome.

## User-Outcome Claims

- Establish a user-visible runtime result through its actual consumer and persistence path. When a matching probe in `.codex/outcomes.json` helps verify the claim, select it with the verifier's `--claim`; the full contract is not a prerequisite for ordinary development or manual use.
- A file, configuration entry, passing unit test, queued job, or `completed` flag is supporting evidence unless it is itself the requested outcome.
- Hooks and asynchronous workers require a fresh receipt produced after the relevant trigger.
- Generated Notes and processed data must exist, contain meaningful content, and be readable through their intended path.
- Report verification honestly as `passed`, `partial`, `failed`, or `blocked`. Never rename a partial result as complete.

## Runtime and Data Safety

- Do not mutate live runtime data, local memory stores, transcript sources, Notes, receipts, or generated diagnostic reports during unrelated development work.
- For authorized maintenance or deletion, resolve the exact targets and use an existing preview when it helps check the scope. Explicit task authorization may include old-data cleanup or compatibility removal; do not require renewed permission for each step within that scope.
- Never delete a shared history container to remove one session.
- Preserve transaction safety and project isolation when correcting or deleting stored knowledge, but do not retain old knowledge as history.
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
