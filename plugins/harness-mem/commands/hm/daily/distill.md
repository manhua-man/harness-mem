---
name: "HM: Distill"
description: 整理最近会话，生成候选记忆，并以 preview-only 方式预审
category: Memory
tags: [harness-mem, distill, memory]
---

把指定项目最近的会话灌入 verbatim 层，使用仓库里的 `tools/session-distill` 主动提炼候选记忆，随后运行 auto-review preview。默认不确认 durable memory；确认、拒绝、替换必须通过 `/hm:review` 或用户显式要求的 apply 模式。

**MCP Tool Names**

优先使用无短横线 MCP server alias，避免 Claude Code tool-call parser 被 server 名里的 `-` 绊倒：

- `mcp__harness_mem__get_project_status`
- `mcp__harness_mem__prepare_session_distill`
- `mcp__harness_mem__suggest_memory_entry`
- `mcp__harness_mem__suggest_rule`
- `mcp__harness_mem__suggest_relation_fact`
- `mcp__harness_mem__create_task_handoff`
- `mcp__harness_mem__auto_review_candidates`

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
   - `project_root=<当前 agent 工作区项目根目录>`（必须传；不要让 MCP server 用自己的进程 cwd 猜）
   - `observation_limit=5`
   - `max_chars_per_observation=6000`

   这个工具会一次性完成项目范围 ingest，并返回最近 observations 的 evidence packet。不要再手动调用 `timeline`、`get_observations`、`Bash`、`cmem`、`ls`、`cat` 或 `find` 去摸索同一批内容；只有 packet 为空或工具明确报错时才排障。

   默认只 ingest 当前 agent 环境、当前项目路径匹配的会话。`client="auto"` 会自动识别 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 入口，并按当前项目根过滤证据。
   - 只有用户明确要求全局历史时，才允许 `scope="all"`

3. **启动仓库 Skill 做主动提炼**
   - 默认读取并遵循 `tools/session-distill/SKILL.md`
   - 按 `tools/session-distill/references/distillation-rules.md` 判断哪些结论值得进入候选层
   - 直接使用 `prepare_session_distill` 返回的 observations 作为 evidence packet
   - 用 MCP `suggest_memory_entry` / `suggest_rule` / `suggest_relation_fact` / `create_task_handoff` 写入 pending 候选
   - 每条候选必须带 source evidence，例如 observation id、session id、packet turn、命令或文件路径

   不要退回旧的 heuristic fallback。v2.0 已移除正则提取式 distill；
   如果 `prepare_session_distill` 或 Skill 无法提供 evidence packet，应把它当作
   runtime / 配置问题排障，而不是退回低质量自动提取。

4. **自动审核预览候选**
   调 MCP `auto_review_candidates`：
   - `project_name=<project>`
   - `apply=false`

   MCP 不可用时，直接说明 runtime 工具不可用；CLI 只是开发者本地排障层，不要求普通用户手动运行。

   默认不要确认、拒绝或替换候选。低风险候选的判断必须复用 shared auto-review policy，而不是在 slash 文档里手写另一套规则。用户明确要求“自动处理低风险候选”时，也不要调用 heuristic apply；转入 `/hm:review`，逐条使用显式 `confirm_*` / `reject_*`。

   摘要必须以 `auto_review_candidates` 返回的结果为准：
   - `auto_confirmed`
   - `auto_rejected`
   - `kept_pending`
   - `needs_user_confirmation`
   - `applied_decisions`

   默认 preview 下 `applied_decisions` 必须为空。如果用户追问某个候选为什么会被建议确认或拒绝，解释 candidate id、evidence id 和 policy reason。

5. **总结呈现**
   按"新灌入 N / 新候选 M / 建议确认 C / 建议拒绝 R / 保留待定 K / 需要你确认 H"格式给用户看结果。

   最终明确说明没有写入 confirmed memory，并把 durable gate 指向 `/hm:review`：

   ```text
   已完成整理和预审。
   auto-review mode: preview only
   no durable memory was confirmed
   建议确认：...
   建议拒绝：...
   保留待定：...
   需要你确认：...
   运行 /hm:review 处理这些候选。
   ```

**Notes**

- `/hm:distill` 是建议链路：整理、提炼、预审候选、给最终摘要
- `/hm:review` 是 durable memory gate：确认、拒绝、替换候选都在这里发生
- 不要把具体客户端写死为默认来源；默认入口必须是 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>)`
- agent 历史可能是用户全局数据源，默认必须按当前项目路径过滤；跨项目导入必须由用户显式要求 `scope="all"`
- 用户主路径是 Slash + MCP + Skill；CLI 只能作为开发者排障兜底
- MCP server 的 cwd 不等于当前 agent 项目目录；调用 `prepare_session_distill` / `ingest_sessions` 时必须显式传 `project_root`
