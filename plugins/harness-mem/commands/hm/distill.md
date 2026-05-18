---
name: "HM: Distill"
description: 一键整理最近会话，自动审核处理候选记忆，最后给用户复核摘要
category: Memory
tags: [harness-mem, distill, memory, skill]
---

把指定项目最近的会话灌入 verbatim 层，使用仓库里的 `tools/session-distill` 主动提炼候选记忆，随后 AI 自动审核并处理低风险候选，最后只给用户复核摘要。

**MCP Tool Names**

优先使用无短横线 MCP server alias，避免 Claude Code tool-call parser 被 server 名里的 `-` 绊倒：

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

不要选择旧别名 `mcp__harness-mem__...`。

**Input**: 用户可指定项目名和会话数量（例如 `/hm:distill bazi-apps 10`）。如果省略：
- 项目名：先调 MCP `get_project_status` 读取 active project，没有就问用户
- 会话数：默认 5

**Steps**

1. **确认项目**
   - 如果用户在 slash 后给了项目名，直接用
   - 否则调 MCP `get_project_status`（不传 project_name）读取 active project
   - 仍无法确定：问用户项目名，不要让用户手动跑 CLI

2. **准备蒸馏包**（调一个 MCP 工具）
   调 MCP `prepare_session_distill`：
   - `project_name=<project>`
   - `client="auto"`
   - `limit=<count>`
   - `scope="project"`
   - `project_root=<当前 Claude/Codex 工作区项目根目录>`（必须传；不要让 MCP server 用自己的进程 cwd 猜）
   - `observation_limit=5`
   - `max_chars_per_observation=6000`

   这个工具会一次性完成项目范围 ingest，并返回最近 observations 的 evidence packet。不要再手动调用 `timeline`、`get_observations`、`Bash`、`cmem`、`ls`、`cat` 或 `find` 去摸索同一批内容；只有 packet 为空或工具明确报错时才排障。

   默认只 ingest 当前 agent 环境、当前项目路径匹配的会话：
   - 在 Codex 环境下，使用 Codex rollout/archive 解析，并按 session `cwd` 过滤到当前项目路径
   - 在 Claude Code 环境下，使用 Claude Code 项目会话目录
   - 只有用户明确要求全局历史时，才允许 `scope="all"`

3. **启动仓库 Skill 做主动提炼**
   - 默认读取并遵循 `tools/session-distill/SKILL.md`
   - 按 `tools/session-distill/references/distillation-rules.md` 判断哪些结论值得进入候选层
   - 直接使用 `prepare_session_distill` 返回的 observations 作为 evidence packet
   - 用 MCP `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` / `create_task_handoff` 写入 pending 候选
   - 每条候选必须带 source evidence，例如 observation id、session id、packet turn、命令或文件路径

   `distill_sessions(project_name=<project>, project_root=<当前项目根目录>)` 只允许作为 smoke/fallback：
   - MCP 可用性验证
   - 用户明确要求快速低成本提取
   - Skill 无法读取 evidence 时的开发者排障

   不要把 `distill_sessions` 的 `No patterns found` 当成 `/hm:distill` 的最终高质量结论。

4. **自动审核并处理候选**
   调 MCP `list_candidates`，参数为 `project_name=<project>`、`status="pending"`、`limit=100`。
   MCP 不可用时，直接说明 runtime 工具不可用；CLI 只是开发者本地排障层，不要求普通用户手动运行。

   不要停下来让用户逐条选择，也不要提示用户去运行 `/hm:review`。AI 必须自动判断每条候选：

   - **confirm**：明确项目长期事实、真实架构、稳定约定、source 可靠、不会改变未来行为边界。
   - **reject**：工具故障、agent 编排故障、跨项目 workflow、泛泛原则、重复候选、证据不足、把本次 distill 过程误写成项目事实。
   - **keep_pending**：可能有价值但证据不足，暂不打扰用户。
   - **migrate**：有价值但属于全局工作流或别的项目；当前项目内默认 reject，并在摘要说明应该迁移。

   AI 可以直接调用对应 MCP 工具处理低风险项：
   - `confirm_rule` / `reject_rule`
   - `confirm_memory_entry` / `reject_memory_entry`
   - `confirm_relation_fact` / `reject_relation_fact`

   只有高风险 confirm（会改变未来 AI 行为、影响范围大、置信不足但可能重要）才保留 pending，并放进最终摘要的"需要你确认"区。

5. **总结呈现**
   按"新灌入 N / 新候选 M / 自动确认 C / 自动拒绝 R / 保留待定 K / 需要你确认 H"格式给用户看结果。

   最终只做复核摘要，不要让用户继续跑 `/hm:review`：

   ```text
   已完成整理和自动审核。
   自动确认：...
   自动拒绝：...
   保留待定：...
   需要你确认：...
   如果有处理不对，告诉我编号，我会改。
   ```

**Notes**

- `/hm:distill` 是默认闭环：整理、提炼、自动审核、处理低风险候选、给最终摘要
- `/hm:review` 只作为复查/纠错/手动补救入口，不是日常必经流程
- 不要把 `codex` / `codex-archive` 写死为默认来源；默认入口必须是 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>)`
- codex 历史是用户全局的，默认必须按当前项目路径过滤；跨项目导入必须由用户显式要求 `scope="all"`
- 用户主路径是 Slash + MCP + Skill；CLI 只能作为开发者排障兜底
- MCP server 的 cwd 不等于 Claude/Codex 当前项目目录；调用 `ingest_sessions` 和 fallback `distill_sessions` 时必须显式传 `project_root`
