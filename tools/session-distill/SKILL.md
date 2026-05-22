---
name: session-distill
version: 1.6.0
description: |
  Harness-mem 项目的主动会话蒸馏技能。用于把当前项目相关的 Claude/Codex 会话整理成可审核的候选记忆。
  当用户运行 /hm:distill、要求整理会话、提炼经验、固化项目规则或生成任务交接时使用。
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
  - mcp__harness_mem__list_candidates
  - mcp__harness_mem__confirm_memory_entry
  - mcp__harness_mem__reject_memory_entry
  - mcp__harness_mem__confirm_rule
  - mcp__harness_mem__reject_rule
  - mcp__harness_mem__confirm_relation_fact
  - mcp__harness_mem__reject_relation_fact
---

# Session Distiller (harness-mem 主链)

## 定位

`session-distill` 是用户主动蒸馏时的默认体验层。

默认目标是把当前项目相关会话转成候选，并在 `/hm:distill` 同一轮里自动审核和处理低风险项。用户只看最终复核摘要；`/hm:review` 是复查/纠错/手动补救入口，不是日常必经步骤。

## 主链

```text
Raw Sessions
  -> MCP ingest_sessions(project scoped)
  -> Observation Store
  -> session-distill Skill reads evidence
  -> MCP suggest_memory_entry / suggest_rule / suggest_relation_fact / create_task_handoff
  -> Candidate Layer (pending)
  -> list_candidates
  -> AI auto-review and low-risk confirm/reject
  -> Human final result review
```

## 默认动作序列

### 0. 使用稳定 MCP 别名

在 Claude Code 中调用 MCP 工具时，优先选择无短横线 server alias：

- `mcp__harness_mem__get_project_status`
- `mcp__harness_mem__prepare_session_distill`
- `mcp__harness_mem__suggest_memory_entry`
- `mcp__harness_mem__suggest_rule`
- `mcp__harness_mem__suggest_relation_fact`
- `mcp__harness_mem__create_task_handoff`
- `mcp__harness_mem__list_candidates`
- `mcp__harness_mem__confirm_memory_entry`
- `mcp__harness_mem__reject_memory_entry`
- `mcp__harness_mem__confirm_rule`
- `mcp__harness_mem__reject_rule`
- `mcp__harness_mem__confirm_relation_fact`
- `mcp__harness_mem__reject_relation_fact`

不要选择旧别名 `mcp__harness-mem__...`，因为部分 Claude Code tool-call parser 会把带短横线的 MCP server 名解析坏。

### 1. 确认项目和真实项目根

先通过 MCP `get_project_status` 读取 active project。调用方必须传入当前 agent 工作区对应的真实项目根目录，不能让 MCP server 用自己的进程 cwd 猜。

如果用户在 `/hm:distill <project> <count>` 里给了项目名，使用用户给定项目名；否则使用 active project。仍无法确定时，只问项目名，不要求用户运行 CLI。

### 2. 灌入当前项目会话

调用 MCP `prepare_session_distill`：

- `project_name=<project>`
- `client="auto"`
- `limit=<count>`，默认 5
- `scope="project"`
- `project_root=<当前 Claude/Codex 工作区项目根目录>`
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

每条候选都必须有来源证据：observation id、session id、packet turn、命令或文件路径。证据不足时不要硬写；可以列为需要补证，并在必要时调用外置协作者。

不要生成这些候选：

- 当前 `/hm:distill` 或 MCP/slash 调用过程本身。
- `Bash`、`cmem`、`ToolSearch`、MCP 参数错误、agent idle、TeamCreate/SendMessage/TeamDelete 等工具编排故障，除非目标项目本身就是这些工具。
- `/plan-eng-review`、`/plan-ceo-review`、`/plan-design-review` 等 AI review workflow，除非用户明确要记录为全局工作流记忆。
- 对应用/游戏项目而言，把 AI 工作流、评审方式或工具名写成项目架构事实。

### 4. 自动审核并处理

调用 MCP `list_candidates(project_name=<project>, status="pending")`，读取当前 pending 候选。

不要停下来让用户逐条选择。AI 应直接判断并处理低风险项：

- **低风险 confirm**：明确项目长期事实、真实架构、稳定约定、source 可靠、不会改变未来行为边界。
- **低风险 reject**：工具故障、agent 编排故障、跨项目 workflow、泛泛原则、重复候选、证据不足、把本次 distill 过程误写成项目事实。
- **keep_pending**：可能有价值但证据不足，暂不打扰用户。
- **migrate**：有价值但属于全局工作流或别的项目；当前项目内默认 reject，并在摘要说明应该迁移。

只有高风险 confirm（会改变未来 AI 行为、影响范围大、置信不足但可能重要）才保留 pending，并放进最终摘要的"需要你确认"区。

最后给用户看处理结果摘要，让用户纠错，而不是让用户继续跑 `/hm:review`。

## 外置协作者

这些工具可以辅助 review，但不是主链硬依赖：

| 工具 | 使用时机 |
|------|----------|
| `grill-me` | 候选会改变项目规则、范围很大或风险高时，做压力测试。 |
| `answer-me` | 候选缺证据，需要补代码、配置或历史上下文。 |
| `mem-distill` | 用户要整理已有 memory / observations，而不是原始 session。 |

## 不做的事

- 不要求普通用户手动跑 `harness-mem ingest` 或 `harness-mem distill`。
- 不默认把用户级全局 Codex archive 灌进当前项目。
- 不把 "no patterns found" 当成最终高质量蒸馏结论；那只说明 fallback 没抽到明显模式。
- 不把逐条分类工作交给用户；AI 必须自动审核 pending 候选，低风险项直接处理，高风险项才留给用户最终确认。
- 不把 `grill-me` / `answer-me` / `mem-distill` 合并进主链，除非用户明确要求。

## 兜底策略

MCP 不可用时，明确报告 runtime 工具不可用，并说明 CLI 只是开发者排障层。

Skill 无法读取足够 evidence 时，先报告缺口和下一步补证方式，不要把空结果包装成"蒸馏完成"。
