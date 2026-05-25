## Design

### Visible entry contract

The user-facing path is:

- Claude Code: `/hm:distill`, `/hm:wake`, `/hm:search`, `/hm:review`
- Codex / Cursor / generic AI IDE: natural-language equivalents such as
  "用 harness-mem 整理最近 10 个 session"
- MCP: hidden transport used by the agent, not the wording given to ordinary users
- CLI: maintenance/debug only

### Project resolution

Agent workflow resolves project context in this order:

1. active project / project profile from runtime
2. current workspace root
3. one short user question if ambiguous

The workflow must not tell the user to run `harness-mem use`.

### Distill closed loop

`/hm:distill` equivalent workflow:

1. `prepare_session_distill(project_name, client="auto", scope="project", project_root=<workspace>)`
2. session-distill Skill or agent reasoning reads the returned evidence packet
3. `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` /
   `create_task_handoff` writes pending candidates
4. `list_candidates` reads the pending set
5. agent confirms low-risk long-term facts, rejects noise/duplicates/cross-project
   leakage, and keeps uncertain items pending
6. final summary shows counts and only high-risk leftovers

### Failure contract

Failures must be user-readable and diagnostic:

- MCP unavailable: say runtime tools are unavailable and point to setup/doctor
- no LLM agent: distill unavailable, no heuristic fallback
- empty evidence packet: report no project-scoped sessions found
- project mismatch: state the detected project/root mismatch
- permission or filesystem error: include the safe next diagnostic step

### Auto-review boundary

Auto-review handles routine low-risk decisions, but it must be evidence-grounded.
Confirmed items need source observation/session ids. High-risk or weak-evidence
items remain pending and appear in the final summary.

### Non-goals

- no Memory Metabolism / Dream
- no cross-project Skill sharing
- no default procedural Skill injection into wake
- no background daemon or implicit turn-end writes
- no REST API restoration
- no daily CLI command restoration

