---
name: session-distill
version: 1.6.0
description: |
  Harness-mem 项目的主动会话蒸馏技能。用于把当前项目相关的 Codex / Claude Code / Cursor / Antigravity / opencode / Hermes / generic agent 会话整理成可审核的候选记忆。
  当用户主动要求蒸馏会话、整理记忆、提炼经验、固化项目规则或生成任务交接时使用（无论触发方式是 slash 命令、自然语言请求还是其他客户端入口）。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - mcp__harness_mem__get_project_status
  - mcp__harness_mem__prepare_session_distill
  - mcp__harness_mem__suggest_memory_entry
  - mcp__harness_mem__suggest_rule
  - mcp__harness_mem__suggest_relation_fact
  - mcp__harness_mem__create_task_handoff
  - mcp__harness_mem__auto_review_candidates
  - mcp__harness_mem__list_candidates
---

# Session Distiller (harness-mem 主链)

## 定位

`session-distill` 是用户主动蒸馏时的默认体验层。

默认目标是把当前项目相关会话转成候选，并在同一轮里运行 auto-review preview。默认不确认 durable memory；确认、拒绝、替换必须通过 `/hm:review` 或用户显式要求的 apply 模式。

## 主链

用户只有一条默认主链：`/hm:distill` / 自然语言等价入口。Agent 不要求用户区分 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 历史；入口统一调 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根>)`，由 runtime 自动识别可用来源并返回 evidence packet。

```text
Raw Sessions
  -> MCP prepare_session_distill(client="auto", project scoped)
  -> runtime auto-detects client/source
  -> Observation Store
  -> session-distill Skill reads evidence
  -> MCP suggest_memory_entry / suggest_rule / suggest_relation_fact / create_task_handoff
  -> Candidate Layer (pending)
  -> auto_review_candidates(apply=false)
  -> /hm:review durable gate
```

## 默认动作序列

### 0. MCP 工具命名

直接用工具的裸名（`prepare_session_distill`、`suggest_memory_entry`、`auto_review_candidates` 等）。客户端如何把它们映射成可调用 alias（带短横线 / 不带短横线 / 带 server 前缀）由客户端自己决定，本 skill 不假设。

如果你的客户端通过 MCP Router 接入，工具名通常就是裸名；如果直连 server，可能会带 server name 前缀。两种都能跑，prompt 里不要写死前缀。

默认 MCP profile 是 `core-read`，只暴露 read/prepare/list/detail。创建候选和运行 auto-review preview 必须显式使用 `distill-suggest` profile；确认、拒绝或 apply 必须走 `/hm:review` 或 `review-write` profile。

### 1. 确认项目和真实项目根

先通过 MCP `get_project_status` 读取 active project。调用方必须传入当前 agent 工作区对应的真实项目根目录，不能让 MCP server 用自己的进程 cwd 猜。

如果用户在请求里给了项目名（例如 `/hm:distill <project> <count>` 或自然语言中明确指定），使用用户给定项目名；否则使用 active project。仍无法确定时，只问项目名，不要求用户运行 CLI。

### 2. 灌入当前项目会话

调用 MCP `prepare_session_distill`：

- `project_name=<project>`
- `client="auto"`
- `limit=<count>`，默认 5
- `scope="project"`
- `project_root=<当前 agent 工作区项目根目录>`
- `observation_limit=5`
- `max_chars_per_observation=6000`

默认只摄取当前 agent 环境、当前项目路径匹配的 session。

- Claude Code: 读取与当前项目路径对应的 `~/.claude/projects/...` 会话目录。
- Codex: 读取 Codex rollout/archive，并按 session `cwd` 过滤到当前项目路径。
- 只有用户明确要求跨项目/全局历史时，才允许 `scope="all"`。

`prepare_session_distill` 会直接返回 evidence packet。不要再调用 `Bash`、`cmem`、`timeline`、`get_observations`、`ls`、`cat` 或 `find` 去摸索同一批 observations；只有 packet 为空或工具报错时才排障。

### 3. 用 Skill 做主动提炼

读取 `prepare_session_distill` 返回的 observations / packets / session evidence，按 `references/distillation-rules.md` 判断候选价值。

产出时优先拆成几类：

- `suggest_memory_entry`: 稳定项目知识、架构事实、可复用排障经验。
- `suggest_rule`: 会改变未来 AI 默认行为的项目规则。
- `suggest_relation_fact`: 明确的依赖、归属、替代、冲突等实体关系。
- `create_task_handoff`: 当前任务状态、阻塞点、下一步。

这些 suggest 工具属于 `distill-suggest` profile。默认 `core-read` 下如果不可见，不要退回 CLI 或直接写 truth；应明确提示需要启用 distill-suggest MCP profile。

每条候选都必须有来源证据：observation id、session id、packet turn、命令或文件路径。证据不足时不要硬写；先列为需要补证，并说明缺口。

不要生成这些候选：

- 当前 distill 调用过程本身（无论是 slash、MCP 还是其他触发方式）。
- `Bash`、`cmem`、`ToolSearch`、MCP 参数错误、agent idle、TeamCreate/SendMessage/TeamDelete 等工具编排故障，除非目标项目本身就是这些工具。
- `/plan-eng-review`、`/plan-ceo-review`、`/plan-design-review` 等 AI review workflow，除非用户明确要记录为全局工作流记忆。
- 对应用/游戏项目而言，把 AI 工作流、评审方式或工具名写成项目架构事实。

### 4. 自动审核预览

调用 MCP `auto_review_candidates(project_name=<project>, apply=false)`，复用 shared low-risk review policy。该工具属于 `distill-suggest` profile；默认 `core-read` 不暴露它。

默认 distill 路径必须直接消费 `auto_review_candidates` 返回的结果，但不能确认、拒绝或替换候选：

- `auto_confirmed`
- `auto_rejected`
- `kept_pending`
- `needs_user_confirmation`
- `applied_decisions`

默认 preview 下 `applied_decisions` 必须为空。若用户追问某个候选为什么被建议确认或拒绝，解释 candidate id、evidence id 和 policy reason。

`list_candidates` 可用于显式 review drilldown。`confirm_*`、`reject_*` 属于 `/hm:review` durable gate，不是默认 distill 主链。

最后给用户看预审摘要，明确写出 `auto-review mode: preview only` 和 `no durable memory was confirmed`，并提示运行 `/hm:review` 处理候选。

## `/hm:*` 管理入口

这些是用户可见的 Slash / command 入口，不是要求用户手敲 CLI。CLI 只作为 repo-local 实现层和测试入口存在。

| 入口 | 目的 |
|------|------|
| `/hm:mark <session-id> distilled [--keep-raw]` | 通过 guardrail 后把单个 session 落为 `distilled`。 |
| `/hm:prune --statuses distilled,skipped --source-missing` | 清理 raw 已不存在、只剩 manifest 占位的已处理记录。 |

`/hm:mark` 的 `distilled` 收口必须检查：

- `distilled/sessions/<session-id>.md` 存在。
- session note 至少包含 `Source`、`Raw Review`、`Summary`、`Verification From Session`、`Promotion Decision`。
- partial packet 的 `Raw Review` 明确写 `Raw transcript reviewed: yes`。
- `Promotion Decision` 明确写 `Promote:` 或 `No Promotion:`，不能还有 pending/TODO。
- `memory-drafts/<session-id>.json` 不能还有 pending 条目。

raw transcript 删除只由 `/hm:mark ... distilled` 的实现层在安全白名单内执行；`--keep-raw` 会保留 raw。raw 删除后 manifest 仍保留 `distilled/skipped` 状态和 `source_missing` / `raw_deleted_at`，避免重新进入待处理队列。

KB / PRD 语义不再作为 session-distill 的独立子系统存在。产品决策、架构事实、项目知识和规则都应抽成 harness-mem candidates，再通过 `/hm:review` 进入 confirmed memory。正式 PRD 或 roadmap 文档若存在，属于普通项目文档编辑，不由 session-distill 维护。

## Memory Metabolism preview (v2.3.0)

v2.3.0 给后续 metabolism 流程铺地基，但**不**改本 skill 的主链行为。你需要知道它的形态，避免把它当成 `/hm:distill` 的同类入口去触发。

- **只有 MCP 工具，没有 slash / 自然语言入口**。v2.3.0 仅新增一个工具：`metabolism_preview`。v2.3.1 新增写侧兄弟 `metabolism_run`（跑 suggestion pass 并持久化候选），但 `metabolism_preview` 仍保持只读——它只写审计记录，不产候选、不动 truth。没有 `/hm:metabolism`，没有触发短语；客户端走标准 MCP `tools/call` 调用，和其他 MCP 工具一致。
- **Signals 是后台写入，不进入用户视野**。`wake_surfaced` / `search_hit` / `confirmed` / `rejected` / `skill_result_*` / `supersede_completed` 都是已有用户可见动作上的 shadow write。用户和 agent 不会看到、不需要响应；唯一的"展面"是 `metabolism_preview` 输出的窗口摘要和 `list_metabolism_runs` 返回的运行记录审计。
- **不动 truth，没有 daemon**。Preview 全程只读：每次调用写一条 `MetabolismRun(kind="preview", status="preview")` 作为审计，不触碰 `usage_count` / `last_accessed_at`，不产 rule / candidate，不调度后台任务。工具只在被显式调用时跑。
- **返回结构**。`{success, run_id, project_name, time_range, dimensions, notes, signals_used}`。`dimensions` 五个固定维度：`observations`、`pending_candidates`、`historical_truths`、`low_success_skills`、`repeat_search_hits`，每条携带 `selected_ids` / `truncated` / `total_seen`。`notes` 列出命中的硬上限 `truncated_within_<dim>: X/Y`，并始终包含一行 `soft_token_budget: <est>/<max>` 审计；若软上限触发尾部裁剪，再追加 `trimmed_for_token_budget: <dims>`。

## 不做的事

- 不要求普通用户手动跑 `harness-mem ingest` 或 `harness-mem distill`。
- 不默认把用户级全局 agent 历史灌进当前项目。
- 不把 "no patterns found" 当成最终高质量蒸馏结论；那只说明 fallback 没抽到明显模式。
- 不把逐条分类工作交给用户；AI 必须自动预审 pending 候选，但默认不直接处理低风险项，durable write 通过 `/hm:review`。
- 不维护独立的 `knowledge-base.md`、KB review/prune 命令、PRD sync 文件或产品文档桥。
- 不把 `session-distill.py` 命令列表当成用户产品面；用户入口是 `/hm:*` 或自然语言等价命令。

## 兜底策略

MCP 不可用时，明确报告 runtime 工具不可用，并说明 CLI 只是开发者排障层。

Skill 无法读取足够 evidence 时，先报告缺口和下一步补证方式，不要把空结果包装成"蒸馏完成"。
