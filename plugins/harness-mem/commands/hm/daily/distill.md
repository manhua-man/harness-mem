---
name: "HM: Distill"
description: 整理最近会话，生成候选记忆，并自动处理低风险项
category: Memory
tags: [harness-mem, distill, memory]
wireFormatVersion: hm-wire-v3.5
---

同步指定项目最近的 transcript evidence，使用仓库里的 `tools/session-distill` 主动提炼候选记忆，随后运行 auto-review apply-low-risk。低风险项可自动进入 `auto_confirmed` 或 `provisional`；`/hm:review` 是事后审计、undo、确认和替换入口。

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

   这个工具会一次性完成项目范围 transcript sync，并返回最近 observations 的 evidence packet。不要再手动调用 `ingest_sessions`、`timeline`、`get_observations`、`Bash`、`cmem`、`ls`、`cat` 或 `find` 去摸索同一批内容；只有 packet 为空或工具明确报错时才排障。

   默认只同步当前 agent 环境、当前项目路径匹配的会话。`client="auto"` 会自动识别 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 入口，并按当前项目根过滤证据。
   - 只有用户明确要求全局历史时，才允许 `scope="all"`

3. **读 packet、draft claims、标准准入，再写候选**
   - 默认读取并遵循 `tools/session-distill/SKILL.md`（Step 3–4）
   - 用 `prepare_session_distill` 返回的 packet 形成 candidate claim
   - 自动应用 `grill-before-distill` 准入（深度/轻量按风险）；仅 `admit` / `narrow` 继续
   - 按 `references/distillation-rules.md` 判断价值
   - 用 MCP `suggest_*` / `create_task_handoff` 写入 pending 候选
   - 每条候选必须带 source evidence，例如 observation id、session id、packet turn、命令或文件路径

   不要退回旧的 heuristic fallback。v2.0 已移除正则提取式 distill；
   如果 `prepare_session_distill` 或 Skill 无法提供 evidence packet，应把它当作
   runtime / 配置问题排障，而不是退回低质量自动提取。

4. **自动审核并处理低风险候选**
   调 MCP `auto_review_candidates`：
   - `project_name=<project>`
   - `apply=true`

   MCP 不可用时，直接说明 runtime 工具不可用；CLI 只是开发者本地排障层，不要求普通用户手动运行。

   低风险候选的判断必须复用 shared auto-review policy，而不是在 slash 文档里手写另一套规则。高风险、冲突、证据不足或会改变长期行为的项应保留到 `/hm:review` audit inbox。

   内部审计结果必须以 `auto_review_candidates` 返回的结果为准：
   - `auto_confirmed`
   - `auto_rejected`
   - `kept_pending`
   - `needs_user_confirmation`
   - `applied_decisions`

   `applied_decisions` 保留在审计结果中。如果用户追问某个候选为什么会被确认、拒绝或保留，解释 candidate id、evidence id 和 policy reason。

   `apply=true` 也是同一管线的提交点：它完成待蒸馏任务并触发 Dream。不要再额外调用一条平行的 dream 流程。

5. **总结呈现**
   默认只给简短结果，不展示 transcript、候选、自动确认或拒绝的计数：

   ```text
   已完成整理和自动处理。
   新的长期记忆已按证据和风险策略处理；近期工作仍可在 wake 中查看。
   ```

   只有用户要求审计详情时，才展示计数、candidate/evidence ID 和 `/hm:review` 入口。

**Notes**

- `/hm:distill` 是同一自动管线的立即执行入口：读取证据、提炼候选、自动处理低风险项、触发 Dream；默认摘要保持简短
- `/hm:review` 是 audit inbox：确认、拒绝、undo、替换候选都在这里发生
- 不要把具体客户端写死为默认来源；默认入口必须是 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>)`
- agent 历史可能是用户全局数据源，默认必须按当前项目路径过滤；跨项目导入必须由用户显式要求 `scope="all"`
- 用户主路径是 Slash + MCP + Skill；CLI 只能作为开发者排障兜底
- MCP server 的 cwd 不等于当前 agent 项目目录；调用 `prepare_session_distill` 时必须显式传 `project_root`。`ingest_sessions` 是低层诊断/同步工具，不是用户主路径
