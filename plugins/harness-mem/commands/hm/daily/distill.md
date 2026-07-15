---
name: "HM: Distill"
description: 整理最近会话，生成候选记忆，并自动处理低风险项
category: Memory
tags: [harness-mem, distill, memory]
wireFormatVersion: hm-wire-v3.5
---

同步指定项目的 native transcript revision，从头到尾处理全部有序 chunk，完成会话末尾审查后生成候选，并通过 `finalize_session_distill` 对当前 job 运行限定范围的 auto-review 和 Dream。`/hm:review` 是事后审计、undo、确认和替换入口。

**MCP Tool Names**

优先使用无短横线 MCP server alias，避免 Claude Code tool-call parser 被 server 名里的 `-` 绊倒：

- `mcp__harness_mem__get_project_status`
- `mcp__harness_mem__prepare_session_distill`
- `mcp__harness_mem__submit_distill_chunk`
- `mcp__harness_mem__finalize_session_distill`
- `mcp__harness_mem__suggest_memory_entry`
- `mcp__harness_mem__suggest_rule`
- `mcp__harness_mem__suggest_relation_fact`
- `mcp__harness_mem__create_task_handoff`

不要选择旧别名 `mcp__harness-mem__...`。

**Input**: 用户可指定项目名和会话数量（例如 `/hm:distill bazi-apps 10`）。如果省略：
- 项目名：先调 MCP `get_project_status(project_root=<当前工作区>, host_client="claude-code")`，没有就问用户
- 会话数：默认 5

**Steps**

1. **确认项目**
   - 如果用户在 slash 后给了项目名，直接用
   - 否则调 MCP `get_project_status(project_root=<当前工作区>, host_client="claude-code")` 读取 active project，并幂等检查项目 Hook
   - 仍无法确定：问用户项目名，不要让用户手动跑 CLI

2. **领取并处理完整 transcript chunks**
   调 MCP `prepare_session_distill`：
   - `project_name=<project>`
   - `client="auto"`
   - `limit=<count>`
   - `scope="project"`
   - `project_root=<当前 agent 工作区项目根目录>`（必须传；不要让 MCP server 用自己的进程 cwd 猜）

   这个工具完成项目范围 transcript sync，并领取当前 lossless job 的完整
   chunk。对每个 chunk 从头到尾读取后，调用 `submit_distill_chunk`，把
   `distill_job_id` 作为 `job_id`，连同 `chunk_id`、`lease_owner` 和结构化
   结果提交。随后重复调用
   `prepare_session_distill`，直到 job 进入 `reviewing`。不要再手动调用
   `ingest_sessions`、`timeline`、`get_observations`、`Bash`、`cmem`、`ls`、
   `cat` 或 `find` 去摸索同一份 transcript；只有工具报错或明确返回
   `legacy_partial` 时才排障。

   默认只同步当前 agent 环境、当前项目路径匹配的会话。`client="auto"` 会自动识别 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 入口，并按当前项目根过滤证据。
   - 只有用户明确要求全局历史时，才允许 `scope="all"`

3. **做 final-session review、标准准入，再写候选**
   - 默认读取并遵循 `tools/session-distill/SKILL.md`（Step 3–4）
   - 按 `chunk_index` 汇总全部 checkpoint result，审查最终结果、矛盾、未完成工作、末轮是否回答以及证据强度
   - semantic review 必须填写 `final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、`promotion_decision`
   - 只有 job 进入 `reviewing` 后才能形成 candidate claim
   - 自动应用 `grill-before-distill` 准入（深度/轻量按风险）；仅 `admit` / `narrow` 继续
   - 按 `references/distillation-rules.md` 判断价值
   - 用 MCP `suggest_*` / `create_task_handoff` 写入 pending 候选，并把当前 `distill_job_id` 传给每个 suggest 调用
   - 每条候选必须带 source evidence，例如 source revision、session id、chunk id、命令或文件路径

   不要退回旧的 heuristic fallback。v2.0 已移除正则提取式 distill；
   如果 `prepare_session_distill` 或 Skill 无法提供 lossless chunks，应把它当作
   runtime / 配置问题排障，而不是退回低质量自动提取。

4. **收尾当前 job**
   调 MCP `finalize_session_distill`：
   - `project_name=<project>`
   - `job_id=<当前 distill job>`
   - `semantic_review=<Step 3 的完整会话末尾审查>`

   `finalize_session_distill` 会重新验证 source revision 与全部 checkpoint，
   只审核当前 job 产生的候选。`promotion_decision` 不是 `promote`、证据或末轮
   未回答、存在 contradictions 或 unfinished work 时，必须保留候选为 pending，
   且不运行 Dream。

   MCP 不可用时，直接说明 runtime 工具不可用；不要回退到独立 CLI、packet
   workspace 或本地 memory-drafts 流程。

   低风险候选的判断必须复用 shared auto-review policy，而不是在 slash 文档里手写另一套规则。高风险、冲突、证据不足或会改变长期行为的项应保留到 `/hm:review` audit inbox。

   内部审计结果必须以 `finalize_session_distill` 返回的 scoped auto-review 结果为准：
   - `auto_confirmed`
   - `auto_rejected`
   - `kept_pending`
   - `needs_user_confirmation`
   - `applied_decisions`

   `applied_decisions` 保留在审计结果中。如果用户追问某个候选为什么会被确认、拒绝或保留，解释 candidate id、evidence id 和 policy reason。

   `finalize_session_distill` 是同一管线的唯一提交点。不要再调用项目级
   `auto_review_candidates(apply=true)` 收尾，也不要额外调用一条平行 Dream。

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
- 用户主路径是 Slash + MCP + Skill；没有独立 session-distill CLI 兜底
- MCP server 的 cwd 不等于当前 agent 项目目录；调用 `prepare_session_distill` 时必须显式传 `project_root`。`ingest_sessions` 是低层诊断/同步工具，不是用户主路径
