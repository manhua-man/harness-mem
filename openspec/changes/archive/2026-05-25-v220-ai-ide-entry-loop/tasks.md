## 1. Golden path contract

- [x] 1.1 Align `/hm:distill`, `/hm:wake`, `/hm:search`, `/hm:review`, Skill docs, README, and AGENTS around the same user-visible entry contract.
- [x] 1.2 Define project resolution order: active project/profile -> current workspace root -> one short user question.
- [x] 1.3 Specify `/hm:distill` closed-loop flow: `prepare_session_distill -> session-distill -> suggest_* -> list_candidates -> auto-review/confirm/reject -> summary`.
- [x] 1.4 Define failure messages for MCP unavailable, no LLM agent, empty evidence packet, project mismatch, and permission errors.
- [x] 1.5 Define final summary format with ingested / candidates / auto-confirmed / auto-rejected / pending / high-risk counts.
- [x] 1.6 Confirm `/hm:review` is a repair/recheck entry, not a required post-distill step.

## 2. Cross-client test packet

- [x] 2.1 Upgrade `docs/v2-user-test-packet.md` into a v2.2 client test matrix.
- [x] 2.2 Cover Claude Code slash commands.
- [x] 2.3 Cover Codex natural-language agent prompts.
- [x] 2.4 Cover Cursor natural-language agent prompts.
- [x] 2.5 Cover generic MCP client setup notes for developers.
- [x] 2.6 Record client-specific failures as docs/prompt fixes, not as hidden tribal knowledge.

## 3. Stale surface protection

- [x] 3.1 Add a focused stale-doc scan for removed daily CLI instructions in README / AGENTS / plugin command docs.
- [x] 3.2 Ensure the scan allows maintenance CLI commands (`quickstart`, `doctor`, `purge`, `maintenance`, `import`) while rejecting daily `wake/search/timeline/candidates/distill` CLI instructions.
- [x] 3.3 Add or update loop harness coverage for agent-driven setup without touching removed CLI subcommands.

## 4. Auto-review UX

- [x] 4.1 Create one shared low-risk auto-review policy used by `/hm:distill` and Skill flows.
- [x] 4.2 Require evidence ids for auto-confirmed candidates.
- [x] 4.3 Add noise fixtures: tool failure, cross-project workflow leakage, generic advice, duplicate candidate, and distill-process self-reference.
- [x] 4.4 Final summary separates "kept pending silently" from "needs your confirmation".
- [x] 4.5 Agent can answer "why was this confirmed/rejected?" with candidate id, evidence id, and policy reason.

## 5. Validation

- [x] 5.1 `python -m pytest -q` — 358 passed, 1 skipped
- [x] 5.2 `python -m ruff check .` — All checks passed
- [x] 5.3 `python -m mypy harness_mem` — Success: no issues found in 73 source files
- [x] 5.4 `openspec validate --all --strict` — 20 passed, 0 failed
- [x] 5.5 Manual v2.2 client test packet run with Claude Code plus at least one non-Claude client (manual gate; satisfied by the `2026-05-25` Claude Code run log entry plus the `2026-06-03` Codex CLI / generic MCP non-Claude entries in `docs/v2-user-test-packet.md`).
