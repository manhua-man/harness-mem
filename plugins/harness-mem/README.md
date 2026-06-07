# harness-mem Plugin

Repo-local plugin wrapper for the `harness-mem` local-first AI memory runtime.

当前发版状态、已完成切片和未做边界以 [docs/roadmap-status.md](../../docs/roadmap-status.md)（公开状态页）
与 [CHANGELOG.md](../../CHANGELOG.md) 为准；本文聚焦 plugin 安装、集成与日常 IDE 使用方式，不单独充当当前实现真值。

It packages four layers:

- **Skills**: tells an agent when to use memory commands, plus an optional conversation autopilot that can proactively wake/search/suggest at task boundaries.
- **MCP config**: exposes `python -m harness_mem.mcp.server` as hidden structured runtime tools for agents.
- **IDE commands**: Claude Code slash commands (`/hm:status`, `/hm:distill`, `/hm:wake`, `/hm:search`, `/hm:dream`, optional `/hm:review`, plus `/hm:mark` / `/hm:prune` / `/hm:review-kb` / `/hm:prune-kb` / `/hm:verify-entry` / `/hm:prd-sync`) and reusable command instructions that Cursor/Codex-style agents can follow, so end users do not need to memorize CLI flags or MCP tool names.
- **Scripts**: install and doctor helpers for local validation.

Install from the repository root:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid
```

This:

1. Installs `harness-mem` (with `[hybrid]` extras when requested).
2. Copies the slash commands from `plugins/harness-mem/commands/hm/` into
   `~/.claude/commands/hm/` so they show up in any Claude Code project.
3. Copies bundled skills from `plugins/harness-mem/skills/` into
   `~/.claude/skills/`, including `harness-mem` and `harness-mem-autopilot`.
4. Runs `harness-mem doctor` for a smoke check.

Skip slash command sync (e.g. for headless/CI machines):

```powershell
.\plugins\harness-mem\scripts\install.ps1 -NoSlashCommands
```

Run the repo-local maintenance smoke check:

```powershell
.\plugins\harness-mem\scripts\doctor.ps1 -Wake
```

`-Wake` is hint-only: it runs the normal doctor maintenance path, then prints
the IDE-native wake action (`/hm:wake` or the natural-language equivalent).

Register the MCP server with Claude Code when desired:

```powershell
.\plugins\harness-mem\scripts\install.ps1 -RegisterClaude
```

Claude Code tool names should use the no-hyphen alias, for example
`mcp__harness_mem__get_project_status`. Avoid registering the server as
`harness-mem`; some Claude Code tool-call paths misparse MCP server names that
contain `-`.

## Daily flow inside AI IDEs

Once installed, drive harness-mem through IDE commands and chat. MCP is the transport layer behind the agent.

### Autopilot skill

`harness-mem-autopilot` is a soft auto-start skill for conversation-level auto-learning. It lets the agent proactively decide when to wake, search, create evidence-backed candidates, or suggest a distill at clear task boundaries.

Default behavior is intentionally conservative:

| Config | Default | Behavior |
|--------|---------|----------|
| `autopilot.enabled` | `true` | Agent may run conversation-level auto-learning actions. |

Autopilot is enabled by default. It has only one user-facing switch:
`autopilot.enabled`. Set `harness-mem config set autopilot.enabled false` only
when a project should hard opt out of proactive conversation-level memory
actions; when false, the skill should stay idle unless the user explicitly asks
for a memory action in that turn.

Autopilot learns through the normal candidate/review loop: it may create
evidence-backed candidates, but it does not silently confirm durable truth.
It does not enable hooks, schedulers, daemon behavior, dream auto-maintenance,
or unconditional per-turn memory writes. Those remain explicit opt-in runtime
behaviors. When `dream.auto.enabled` is explicitly enabled, runtime dream
maintenance may process eligible candidates created through autopilot-controlled
flows.

### Claude Code

| Slash | What it does |
|-------|--------------|
| `/hm:status` | Read-only project triage via MCP `get_project_status`, with next-step hints for `/hm:distill`, `/hm:wake`, and optional repair-only `/hm:review`. |
| `/hm:distill <project> <n>` | Call MCP `prepare_session_distill` once, run `tools/session-distill`, then apply `auto_review_candidates` as the default low-risk review surface before showing the final review summary. This is the normal closed-loop path. |
| `/hm:review` | Optional repair/recheck command for pending candidates left over from old runs, high-risk suggestions, or user corrections. Not part of the daily happy path. |
| `/hm:wake` | Read-only wake-up via MCP `wake`, with optional compact renderer and opt-in skill hints. |
| `/hm:search "query"` | Hybrid memory search via MCP `search_memory`. |
| `/hm:dream` | v3.1 DreamRun ledger: read the latest opt-in auto-maintenance run, explain item evidence/policy reasons, and undo selected applied items through MCP. |
| `/hm:mark <session-id> distilled [--keep-raw]` | Mark a session distilled after session-note, raw-review, promotion, draft, and KB guardrails pass. |
| `/hm:prune --statuses distilled,skipped --source-missing` | Remove source-missing distilled/skipped placeholders from the session-distill manifest. |
| `/hm:review-kb --next 20` | Audit `knowledge-base.md` into stable / needs-review / stale / superseded. |
| `/hm:prune-kb --statuses stale,superseded` | Back up and clean stale/superseded knowledge-base entries. |
| `/hm:verify-entry <session-id|keyword>` | Targeted recheck of matching knowledge-base entries with grill-style questions. |
| `/hm:prd-sync [--apply]` | Scan bundled packets for PRD/roadmap topics and optionally write a candidate sync note under `prd-distilled/`. |

### Cursor / Antigravity / opencode / Hermes / Generic MCP IDE

These clients do not need separate repo-local command templates. Reuse the existing command instructions or use chat prompts that name the user-visible action; MCP `client="auto"` resolves the available session source behind the scenes:

```text
用 harness-mem 唤醒当前项目。
用 harness-mem 搜索 "auth logic"。
用 harness-mem 整理最近 10 个 session，自动审核低风险候选，最后只给我复核摘要。
```

Do not give users a CLI command list as the normal AI IDE path. CLI remains for install, diagnostics, automation scripts, and explicit cleanup.

Raw-file cleanup is only exposed through explicit `/hm:*` maintenance actions
and implementation-layer safety checks. `ingest` indexes local session data into
harness-mem, and `purge` only soft-deletes harness-mem indexed records unless a
separate raw-file cleanup is explicitly requested.
