---
description: AI Agent 指南 - 记忆系统架构、职责与协作真值
alwaysApply: true
---

# AGENTS.md（事 · Facts）

> 本文件定义 **harness-mem** 记忆系统的核心运行逻辑。
> 不同于传统搜索工具，本项目是一个 **AI 主导的记忆运行时**。

## 核心架构：AI 为中心的工作流

| 角色 | 最佳做法 |
| :--- | :--- |
| **AI（操作者 / 提炼）** | 用 `tools/session-distill` 这类 **Skill** 批量读取旧 Session，做高质量提炼。 |
| **候选写入能力** | 在 `/hm:distill`、`session-distill` 或用户明确要求记录时，用 **MCP** `suggest_rule` / `suggest_memory_entry` / `suggest_relation_fact` 写候选。 |
| **人（复核者）** | 日常只看 `/hm:distill` 的最终处理摘要并纠错；需要维护时也通过 `/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 这类 Slash 入口触发。 |
| **AI（消费者）** | 用 **MCP** `search_memory` / `wake` 读取已确认记忆。 |

关键原则：**用户看到 Slash / command / Skill；Agent 背后调 MCP 或 repo-local 实现层；CLI 只做安装、自检、排障和维护实现，不作为产品入口叙事。** AI 提炼或显式记录的内容应先进入候选区；`/hm:distill` 同一轮应由 AI 自动确认低风险事实、拒绝噪声，把高风险或证据不足项留给人类最终复核。只有 confirmed 记忆会进入 `search_memory` / `wake` 可消费的稳定层。

当前实现已有受控自动化：conversation-level autopilot、opt-in host hook / scheduler trigger、默认关闭 Auto Dream。`triggers.*` 默认仍是 `off`。默认常驻后台不做；truth 不静默改。`suggest_*` 只是受控 agent/runtime 流程中的候选写入接口，不能绕过 candidate / review / supersede / ledger。

当前发版状态、已完成切片和未做边界以 `docs/roadmap-status.md` 与 `CHANGELOG.md` 为准；各版本 roadmap 主要保留切片设计、验收口径和历史决策链，不应单独当作当前实现真值。

---

## AI 协作协议

### 1. 记忆提炼（Distillation）
- **触发逻辑**：当一个开发阶段结束，或有大量原始 Session / Observations 累积时，应启动 `tools/session-distill` 这类专职 Skill，而不是让日常编码 Agent 临时兼职长程提炼。
- **AI 任务**：专职操作者应完整阅读原始日志，判断哪些是真正影响后续开发的技术决策、协作规则、任务状态和 rationale，而不是死板匹配关键词。
- **提炼边界**：用户日常只有一条主路径：`/hm:distill` / 自然语言等价入口背后的 MCP 闭环。Agent 调 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根>)`，由 runtime 自动识别 Codex / Claude Code / Cursor / Antigravity / opencode / Hermes / generic agent 来源并返回 evidence packet，然后走 `session-distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true) -> final summary`。任何来源最终都必须接到 candidate layer，而不是绕过候选审核。
- **落盘方式**：提炼结果应先进入候选区，例如 `RuleCandidate`、pending `MemoryEntry` 或 pending `RelationFact`。只有经过 `confirm` 后，才能成为稳定结构化记忆。

### 2. 运行时读写（Runtime Access）
- **主动搜索**：执行任务前，如果历史上下文可能影响当前判断，Agent 应使用 MCP `search_memory`。
- **候选写入**：当用户明确要求记录，或 `/hm:distill` / `session-distill` 从 evidence packet 中提炼出稳定事实时，Agent 应使用 MCP `suggest_rule` / `suggest_memory_entry` / `suggest_relation_fact` 写候选，而不是绕过候选层直接写 confirmed 记忆。
- **设置项目和 profile**：进入新项目时第一步是 `set_active_project`；要把稳定约定（栈、关键文件、conventions）写进 wake-up 时调 `update_project_profile`，不要让用户开终端维护 active project 或 profile。
- **生成唤醒上下文**：用 `wake` 让用户/agent 直接拿到 wake-up 文本，不要把终端 CLI 当作日常入口。
- **消费边界**：`search_memory` / `wake` 默认只消费已确认记忆；pending 候选用于审核，不应污染唤醒上下文。
- **后台 signal 层（v2.3.0）**：现有 `wake` / `search_memory` / `auto_review_candidates` apply 分支 / `record_skill_result` / `confirm_supersede` 调用会**额外**写入 `RetrievalSignal` 影子记录（`wake_surfaced` / `search_hit` / `confirmed` / `rejected` / `skill_result_success` / `skill_result_failure` / `supersede_completed`），描述记忆是怎么被消费的。Agent 不需要主动读这些信号，它们只是 metabolism 层的证据来源；写失败会日志告警但不影响主调用，也不改 truth。
- **代谢预览工具 `metabolism_preview`（v2.3.0）**：新增 MCP 工具，一次调用返回一份 replay 窗口（recent observations / stale pending / 最近变历史的 truth / 低成功率 skills / 重复 search hit），并写一条 `MetabolismRun(kind="preview", status="preview")` 作为审计；**不动 truth、不改 `usage_count` / `last_accessed_at`、不生成建议、不开 daemon**。仅在用户明确要求看下一次 metabolism 会盯哪些证据时调用，日常 wake / search / distill 主链路不变。
- **代谢执行工具 `metabolism_run`（v2.3.1）**：`metabolism_preview` 的写侧兄弟。跑 suggestion pass 并持久化三类候选：`MergeSuggestionCandidate`（高相似度 entry 合并建议）、`StaleTruthSuggestionCandidate`（长期未被 surface 的 truth 过期建议）、`SupersedeCandidate`（复用 v1.7.1 schema，v2.3.1 算法暂为 stub）。写 `MetabolismRun(kind="metabolism", status="completed")`。仍由 Agent 显式触发，无后台 daemon。
- **Weak-link signal 排序影响（v2.3.1）**：当 `ProjectProfile.weak_link_signals` 为 `True` 时，`wake` 将 confirmed rules 按近 30 天 signal 活跃度分为 `Recent active` / `Stable / quiet` 两组；`search_memory` 对近 7 天内重复命中 ≥2 次的 entry 加 0.1 boost。默认关闭（opt-in），可通过 `update_project_profile(weak_link_signals=True)` 开启。关闭时 wake / search 输出与 v2.2 完全一致。

### 3. 自动审核与人类复核（Auto-review + Human Final Review）
- 未确认记忆保持候选状态。Agent 创建候选后，应通过 MCP `auto_review_candidates(project_name=<project>, apply=true)` 直接复用 shared low-risk review policy 处理低风险项，并在最终摘要里保留高风险残留。若用户追问某个候选为什么被自动确认或自动拒绝，再查看 `applied_decisions` 解释 candidate id、evidence id 和 policy reason。
- Agent 不应把逐条分类工作交给用户，也不应把 `/hm:review` 作为日常必经下一步。用户看到的默认形态是 `/hm:distill` 的最终摘要：自动确认了什么、自动拒绝了什么、哪些保留待定、哪些确实需要用户确认。
- 只有 MCP 不可用、需要本地排障，或用户主动要求复查旧 pending 候选时，才退回 `/hm:review`；这类 repair/recheck 流里仍可显式使用 MCP `list_candidates` / `confirm_*` / `reject_*` 做逐项 drilldown。

### 4. Distill 的边界（v2.0）
- distill **只接受 LLM agent**。v2.0 删除了 `harness-mem distill` CLI 子命令、MCP `distill_sessions` 工具，以及 `adapters/parser.py` 里的 heuristic 正则提取。
- 任意 LLM agent（Codex、Claude Code、Cursor、Antigravity、opencode、Hermes、Gemini、自定义 agent）可以通过 MCP `prepare_session_distill(client="auto")` 拿 evidence packet，然后调 `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` 写候选。
- `tools/session-distill/SKILL.md` 是参考实现；其它 client 可以照样写自己的 prompt + MCP 调用。
- 没有 LLM agent 可用时，distill 路径就是 unavailable——这是有意设计，不是缺失。低质量正则伪装成 AI 提炼是 v2.0 砍掉它的原因。

---

## 仓库地图

| 路径 | 说明 | 优先级 |
|------|------|--------|
| `harness_mem/` | Python runtime：schemas、storage、search、MCP server、CLI commands。 | 核心实现 |
| `harness_mem/core/interfaces/` | **底座接口契约**（MemoryBackend / VerbatimStore / StructuredStore / ProjectProfileStore）。修改时遵守"接口纯净度"原则——见下文。 | 底座契约 |
| `tools/session-distill/` | 长程提炼 Skill：raw session -> packet -> memory drafts。 | 核心流程 |
| `tools/mem-distill/` | 既有 memory / observations 的清理、去重、归并。 | 整理 |
| `tools/grill-me/` / `tools/answer-me/` / `tools/ask-me/` | review 阶段可选协作者，不是主链硬依赖。 | 可选 |
| `plugins/harness-mem/` | repo-local 插件封装：安装、MCP 配置、技能入口。 | 集成 |
| `docs/` | 文档索引、设计说明、评审记录、最佳实践。 | 参考 |
| `openspec/specs/` | 当前主 spec 真值；稳定能力边界和已并入主线的行为定义。 | 设计真值 |
| `openspec/changes/` | 仍在进行中的 active changes；只有变更提案尚未归档时才会出现在这里。 | 进行中变更 |
| `openspec/changes/archive/` | 已完成 change 的归档记录；历史 proposal / tasks / writeback 留存在这里。 | 历史记录 |
| `tests/` | 产品测试：CLI、MCP、storage、search、integration。 | 验证 |
| `benchmarks/` | 产品 benchmark 脚本与结果。 | 性能验证 |

---

## 日常入口与兜底命令

用户日常入口优先 AI IDE 内的 Slash / command / Skill / 自然语言指令；MCP 是 Agent 背后的传输层，CLI 只作为本地排障兜底。不要把一串 `harness-mem ...` 命令当成普通用户工作流丢给 AI IDE 用户。

- Claude Code：使用 `/hm:status`、`/hm:distill <project> 10`、`/hm:wake`、`/hm:search "auth logic"`；维护入口使用 `/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry`。
- Cursor / Antigravity / opencode / Hermes / 其它 AI IDE：不要引导用户去终端敲 CLI，也不要把 MCP tool names 当成用户入口；直接让 Agent 复用现有 command 说明，例如“用 harness-mem 唤醒当前项目”“用 harness-mem 整理最近 10 个 session 并自动审核候选”“复查这个 knowledge 条目是否还成立”。
- 终端 CLI：只在安装、自检、MCP 不可用、显式 cleanup 或开发者排障时使用。

`/hm:distill` 的实质是让 Agent 走 MCP：`prepare_session_distill -> suggest_* -> auto_review_candidates(project_name=<project>, apply=true)`。`/hm:mark` / `/hm:prune` / `/hm:review-kb` / `/hm:prune-kb` / `/hm:verify-entry` 是同级 Slash 维护入口；它们可以调用 repo-local 脚本作为实现层，但不要把底层 CLI 菜单当成用户工作流。

## Key Technologies

- **Runtime**: Python 3.13+
- **Database**: SQLite FTS5 verbatim index + JSON blobs / JSONL-style structured memory
- **Embedding baseline**: LongMemEval / benchmark docs default to `all-MiniLM-L6-v2`; `bge-small-en-v1.5` and `nomic-embed-text-v1.5` stay as configurable shootout candidates unless a later shootout explicitly changes the default.
- **Integration**: MCP (Model Context Protocol) + GStack / Codex / Claude Skills
- **Primary workflow**: Skill-driven distillation, Slash/MCP AI auto-review with human final review, MCP runtime consumption
