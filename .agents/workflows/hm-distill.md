---
name: "HM: Distill"
description: 整理最近会话，生成候选记忆，并自动处理低风险项
category: Memory
tags: [harness-mem, distill, memory]
wireFormatVersion: hm-wire-v3.5
---

同步指定项目的 native transcript revision，从头到尾处理全部有序 chunk，完成会话末尾审查后生成候选，并通过 `finalize_session_distill` 对当前 job 运行限定范围的 auto-review 和 Dream。`/hm-review` 是事后审计、undo、确认和替换入口。

**MCP Tool Names**

先检查当前 task 的可调用工具，按逻辑工具名选择当前宿主实际暴露的 namespace，
不要把某个 server alias 当成所有宿主的固定真值：

- MCP Router 接入：`mcp__mcp_router__get_project_status`、
  `mcp__mcp_router__prepare_session_distill`、
  `mcp__mcp_router__submit_distill_chunk`、
  `mcp__mcp_router__finalize_session_distill` 及同 namespace 的
  `govern_memory`。
- 直连无短横线 server：`mcp__harness_mem__get_project_status`、
  `mcp__harness_mem__prepare_session_distill`、
  `mcp__harness_mem__submit_distill_chunk`、
  `mcp__harness_mem__finalize_session_distill` 及同 namespace 的
  `govern_memory`。
- 客户端直接暴露裸工具名时，使用 `get_project_status`、
  `prepare_session_distill`、`finalize_session_distill` 等逻辑名。

只有当前工具清单确实包含时才使用带短横线的旧直连别名
`mcp__harness-mem__...`。不能因为 `harness_mem` / `harness-mem` server 名查询
失败就断言 MCP 不可用；通过 Router 接入时，server alias 是 `mcp_router`。

**Input**: 用户可指定项目名和会话数量（例如 `/hm-distill bazi-apps 10`）。如果省略：
- 项目名：先调 MCP `get_project_status(project_root=<当前工作区>, host_client="antigravity")`，没有就问用户
- 会话数：默认 5

**Steps**

1. **确认项目**
   - 如果用户在 slash 后给了项目名，直接用
   - 否则调 MCP `get_project_status(project_root=<当前工作区>, host_client="antigravity")` 读取 active project，并幂等检查项目 Hook
   - 仍无法确定：问用户项目名，不要让用户手动跑 CLI

2. **领取并处理完整 transcript evidence**
   调 MCP `prepare_session_distill`：
   - `project_name=<project>`
   - `client="auto"`
   - `limit=<count>`
   - `scope="project"`
   - `project_root=<当前 agent 工作区项目根目录>`（必须传；不要让 MCP server 用自己的进程 cwd 猜）
   - `evidence_mode="semantic"`（日常默认快路径）
   - `detail_level="compact"`
   - `budget_tokens=3000`（整个 MCP 返回的日常预算；不是丢弃原文）

   semantic 快路径仍保存完整 native revision。runtime 会校验并 checkpoint
   每个原始 chunk 的 hash、顺序和覆盖率，再返回确定性的两阶段 exchange
   outline。Agent 先完整读取 compact manifest 的全部 exchange 索引、风险信号和
   短预览；返回时 job 已进入 `reviewing`，无需逐个调用 `submit_distill_chunk`。
   outline 只用于选择候选窗口，不是候选级原文证据。

   对可能产生候选的 exchange，先再次调用
   `prepare_session_distill(..., evidence_mode="semantic",
   drilldown_exchange_indexes=[...])` 读取最多 8 个完整 semantic window；再只对
   需要精确命令、版本、错误或主张证据的窗口调用
   `prepare_session_distill(..., evidence_mode="semantic",
   drilldown_query="<关键词>")`；已知位置时也可用
   `drilldown_chunk_indexes=[...]`。一次读取最多 8 个只读原始 chunk。drilldown chunk
   已有结构 checkpoint，不要重复提交。

   `detail_level="full"` 只用于用户明确要求的完整语义审计；不能把它作为日常
   fallback。compact 超出预算时必须读取 `budget_state` 并报告，不能声称已截断
   raw revision。

   如果 runtime 明确回退为 `evidence_mode="raw"`，则沿用兼容流程：逐个完整
   读取返回的 raw chunk，调用 `submit_distill_chunk`，并重复
   `prepare_session_distill` 直到 `reviewing`。用户明确要求逐字/合规审计时也可
   主动使用 raw 模式。不要再手动调用
   `ingest_sessions`、`timeline`、`get_observations`、`Bash`、`cmem`、`ls`、
   `cat` 或 `find` 去摸索同一份 transcript；只有工具报错或明确返回
   `legacy_partial` 时才排障。

   默认只同步当前 agent 环境、当前项目路径匹配的会话。`client="auto"` 会自动识别 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 入口，并按当前项目根过滤证据。
   - 只有用户明确要求全局历史时，才允许 `scope="all"`

3. **做 final-session review、标准准入，再写候选**
   - 默认读取并遵循 `tools/session-distill/SKILL.md`（Step 3–4）
   - semantic 模式按 `semantic_chunk_index` 汇总 evidence；raw 兼容模式按 `chunk_index` 汇总 checkpoint result
   - semantic review 必须填写 `final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、`promotion_decision`
   - 只有 job 进入 `reviewing` 后才能形成 candidate claim
   - 自动应用 `grill-before-distill` 准入（深度/轻量按风险）；仅 `admit` / `narrow` 继续
   - 按 `references/distillation-rules.md` 判断价值
   - 用 MCP `govern_memory(action="suggest")` / `govern_memory(action="handoff")` 写入 pending 候选，并把当前 `distill_job_id` 传入写入参数
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

   低风险候选的判断必须复用 shared auto-review policy，而不是在 slash 文档里手写另一套规则。高风险、冲突、证据不足或会改变长期行为的项应保留到 `/hm-review` audit inbox。

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

   只有用户要求审计详情时，才展示计数、candidate/evidence ID 和 `/hm-review` 入口。

**Notes**

- `/hm-distill` 是同一自动管线的立即执行入口：读取证据、提炼候选、自动处理低风险项、触发 Dream；默认摘要保持简短
- `/hm-review` 是 audit inbox：确认、拒绝、undo、替换候选都在这里发生
- 不要把具体客户端写死为默认来源；默认入口必须是 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>)`
- agent 历史可能是用户全局数据源，默认必须按当前项目路径过滤；跨项目导入必须由用户显式要求 `scope="all"`
- 用户主路径是 Slash + MCP + Skill；没有独立 session-distill CLI 兜底
- MCP server 的 cwd 不等于当前 agent 项目目录；调用 `prepare_session_distill` 时必须显式传 `project_root`。`ingest_sessions` 是低层诊断/同步工具，不是用户主路径
