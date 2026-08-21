---
name: "HM: Distill"
description: 整理最近会话，生成候选记忆，并自动处理低风险项
category: Memory
tags: [harness-mem, distill, memory]
wireFormatVersion: hm-wire-v3.5
---

在当前宿主中同步指定项目的 native transcript revision，从头到尾处理全部有序 chunk，提取窄 promotion point、逐点验证，并通过 `finalize_session_distill` 只提交当前显式 job 的受信归纳吸收。Hook 发起的会话由 Dream 在后台处理，人工 `distill` 不会隐式启动 Dream。`/hm:review` 是事后审计、undo、纠错和替换入口。

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

**Input**: 用户可指定项目名和会话数量（例如 `/hm:distill bazi-apps 10`）。如果省略：
- 项目名：先调 MCP `get_project_status(project_root=<当前工作区>, host_client="claude-code")`，没有就问用户
- 会话数：默认 5

**明确 session id 的快速路径**

- 不要启动额外旁路或生成中间推广文件，也不要先用 shell 搜索 job id。完成后基于本次 `semantic_review` 生成一份可读 session note；不得为写 Note 重新读取或处理 transcript。
- 直接调用一次 `prepare_session_distill(session_id=<用户给出的 id>, project_root=<当前项目根>, client="auto", evidence_mode="semantic", detail_level="compact")`。
- runtime 会直接选择并激活该 session 的最新 job，同时在同一响应中返回 `semantic_decision_exchanges` 和 fail-closed 的 `zero_candidate_challenge_template`；检测到的价值信号默认是 `candidate_required`，不能原样当作零候选结论提交。
- 如果旧版已完成的 `no_candidate` 对检测信号没有逐项解释，显式再次传入同一 session id 时 runtime 会创建新的 policy-recheck job；旧 completion 保持不可变审计记录。
- 无候选时，下一次 MCP 调用必须是 `finalize_session_distill`。只有已确认的 durable candidate 需要精确 raw proof 时，才允许再次 prepare；不要调用 status、list、export 或本地诊断命令。
- 目标是常见零候选路径总计 2 次 MCP 调用。若 host 支持无历史隔离 worker，并且当前会话已很长，把这条有界主链交给 fresh/no-history worker；只回传最终摘要，不继承整段聊天历史。

**Steps**

1. **确认项目**
   - 用户给了明确 session id 时跳过 `get_project_status`；直接把当前工作区作为 `project_root` 交给 prepare，由 runtime 目录优先解析项目
   - 如果用户在 slash 后给了项目名，直接用
   - 否则调 MCP `get_project_status(project_root=<当前工作区>, host_client="claude-code")` 读取 active project，并幂等检查项目 Hook
   - 仍无法确定：问用户项目名，不要让用户手动跑 CLI

2. **领取并处理完整 transcript evidence**
   调 MCP `prepare_session_distill`：
   - `project_name=<project>`
   - `client="auto"`
   - `limit=<count>`
   - `scope="project"`
   - `project_root=<当前 agent 工作区项目根目录>`（必须传；不要让 MCP server 用自己的进程 cwd 猜）
   - `session_id=<用户明确给出的 session id>`（有则直接传；不要先查内部 job id）
   - `evidence_mode="semantic"`（日常默认快路径）
   - `detail_level="compact"`
   - `budget_tokens=<配置或用户目标>`（默认 3000，但只是 Agent 实收完整 MCP
     响应的软目标；用户可请求更大值）

   semantic 快路径仍保存完整 native revision。runtime 会校验并 checkpoint
   每个原始 chunk 的 hash、顺序和覆盖率，再返回确定性的两阶段 exchange
   outline。Agent 先完整读取 compact manifest 的全部 exchange 索引、风险信号和
   短预览；返回时 job 已进入 `reviewing`，无需逐个调用 `submit_distill_chunk`。
   outline 只用于选择候选窗口，不是候选级原文证据。

   默认先使用同一响应已附带的 `semantic_decision_exchanges`；它覆盖零候选挑战所需的有界完整窗口。对确实可能产生 durable candidate 且仍需精确原文举证的 exchange，才再次调用
   `prepare_session_distill(..., evidence_mode="semantic",
   drilldown_exchange_indexes=[...])` 读取最多 8 个完整 semantic window；再只对
   需要精确命令、版本、错误或主张证据的窗口调用
   `prepare_session_distill(..., evidence_mode="semantic",
   drilldown_query="<关键词>")`；已知位置时也可用
   `drilldown_chunk_indexes=[...]`。一次读取最多 8 个只读原始 chunk。drilldown chunk
   已有结构 checkpoint，不要重复提交。

   `detail_level="full"` 只用于用户明确要求的完整语义审计；不能把它作为日常
   fallback。compact 必须读取顶层 `response_budget`：它按 Agent 实际收到的完整
   序列化响应计量。超出软目标可以因完整 manifest 或显式 drilldown 扩张，但必须
   报告实际 tokens 与原因；不能裁 JSON、丢后半段 exchange，或声称已截断 raw revision。

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
   - 默认读取并遵循 `code/tools/hm-distill/SKILL.md`（Step 3–4）
   - semantic 模式按 `semantic_chunk_index` 汇总 evidence；raw 兼容模式按 `chunk_index` 汇总 checkpoint result
   - semantic review 必须填写 `session_summary`、`final_user_request`、`final_outcome`、`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、`promotion_decision`；`contradictions` 只记录当前候选证据仍未解决的冲突，旧方案被后续决定替代应写入 summary/outcome，不能误标为当前候选冲突
   - `session_summary` 用 1–3 句话说明会话主题、实际结果和关键未完成项；它是用户可读摘要，与是否产生长期记忆候选无关
   - v1 job 没有候选时，必须读取 manifest 的 `zero_candidate_required_exchange_indexes`，drilldown 全部完整窗口，并提交带 `content_sha256` 的 `zero_candidate_challenge`
   - challenge 分开记录 `evidence_fidelity` 与 `future_utility`，逐项检查 correction、decision、solution、repeated failure、rule/preference、reusable workflow/fact、version/migration 和 unfinished handoff；检测到的信号默认 `candidate_required`，只有读完完整窗口并在 rationale 点名该 signal key 与 session-only 原因后才可降级为 `not_durable`
   - 任一检查为 `candidate_required` 就返回候选/handoff 路径；只有完整证据且没有 durable utility 才能 `no_durable_candidate`
   - 无 exchange 边界的 raw fallback 以 Agent 完整读取的全部 raw checkpoints 为 challenge basis，不虚构 exchange hash
   - 只有 job 进入 `reviewing` 后才能形成 candidate claim
   - 内联执行候选准入检查：普通候选一次完成；高影响规则先验证证据，只有用户偏好、意图或产品决策无法确定时才询问用户；仅 `admit` / `narrow` 继续
   - 按 `references/distillation-rules.md` 判断价值
   - 用 MCP `govern_memory(action="suggest")` / `govern_memory(action="handoff")` 写入 pending 候选，并把当前 `distill_job_id` 传入写入参数
   - 每条候选必须带 evidence envelope：`evidence_basis`、`verification_outcome`、`verification_refs`
   - 把每条候选视为一个证据问题；runtime 重验 refs 后派生 `answer_gate`，只有 `ANSWERED` 能进入 truth layer。Agent 不能自行声明 `ANSWERED`，普通已闭合证据不增加额外 MCP 调用
   - 条件自动路由，不等用户点名，也不预先串行调用全部协作者：semantic exchange 一旦显示潜在 durable value 就视为存活 claim；缺少、冲突或过期证据时先调用 `answer-memory-evidence`，不能因缺仓库证据直接拒绝；高风险、全局或可能过度概括时调用 `grill-before-distill`；证据仍无法决定产品/架构边界时调用 `ask-memory-boundary`
   - 已完成的 durable claim 与未完成事项并存时，分别写候选与 scoped handoff，并使用 `promotion_decision="partial"`；finalize 仍可归纳吸收已回答 point，但不运行 Dream
   - 路由彼此独立，每个候选的每条路由默认最多一轮；宿主未暴露对应 Skill 时执行同一合同的内联检查。协作者本身不写记忆、不决定晋升，也不产生 MCP 调用
   - 实际运行过的路由分别在 `verification_reason_codes` 记录 `collaborator_answer`、`collaborator_grill`、`collaborator_boundary`
   - 代码、版本、发布、文件与测试状态只能使用 `repository + verified`，ref 使用项目相对路径与当前文件 SHA-256；绝不写绝对路径或证据正文
   - 用户明确偏好、纠正或决定使用 `user_statement + verified/not_applicable`，ref 指向 user role 的 exchange index 与完整窗口 SHA-256
   - 只有会话说法而无法由仓库或用户明确陈述验证时，必须写 `transcript + unverified`；runtime 会终结该 durable candidate，不能伪装为事实

   不要退回旧的 heuristic fallback。正则提取式 distill 已移除；
   如果 `prepare_session_distill` 或 Skill 无法提供 lossless chunks，应把它当作
   runtime / 配置问题排障，而不是退回低质量自动提取。

4. **收尾当前 job**
   调 MCP `finalize_session_distill`：
   - `project_name=<project>`
   - `job_id=<当前 distill job>`
   - `semantic_review=<Step 3 的完整会话末尾审查>`

   `finalize_session_distill` 会重新验证 source revision 与全部 checkpoint，
   并重算 zero-candidate exchange hash，只治理当前 job 产生的候选。缺少 challenge
   或 hash 不匹配时 job 保持 `reviewing`。`promotion_decision="partial"` 时仅对证据门
   已回答的候选进入 scoped verification + assimilation，未完成事项保留为 handoff，且不运行 Dream。
   `no_promotion` / `blocked`、contradicted evidence，或没有任何 surviving candidate
   时才终结为 `no_candidate`；不会让一个无关 handoff 否决其他已回答候选。

   MCP 不可用时，直接说明 runtime 工具不可用；不要回退到独立 CLI 或本地推广文件流程。

   候选判断必须复用 shared verification + assimilation contract，而不是在 slash 文档里手写另一套规则。只有已验证的窄 point 才能由受信 runtime 写入当前知识；其余候选终结在 job 范围。`/hm:review` 是事后 audit、纠错和 undo 入口，不是日常晋升闸门。

   内部审计结果必须以 `finalize_session_distill` 返回的 runtime 派生结果为准：
   - `assimilation_decisions`（`add` / `refine` / `confirm` / `supersede` / `no_write` 等）
   - `completion.disposition`
   - `source_cleanup.status` (`retained` / `deleted` / `partial_failure` / `unsupported`)
   - `applied_decisions`
   - `evidence_admission` (`repository_verified` / `user_stated` / `unverified_blocked` / `contradicted`)
   - `answer_gate` (`ANSWERED` / `PARTIAL` / `UNANSWERED` / `CONTRADICTED` / `STALE` / `NOT_APPLICABLE`)

   `applied_decisions` 保留在审计结果中。如果用户追问某个候选为什么会被确认、拒绝或保留，解释 candidate id、evidence id 和 policy reason。

   `finalize_session_distill` 是同一管线的唯一提交点。不要再调用项目级
   `auto_review_candidates(apply=true)` 收尾，也不要额外调用一条平行 Dream。

5. **总结呈现与 Note**
   明确 session id 时，finalize 为当前 job 创建不可变审计 Note：
   `~/.codex/hm-distill/sessions/revisions/<job_id>/<session_id>.md`，并仅把
   `~/.codex/hm-distill/sessions/<session_id>.md` 更新为该 session 最新完成版本的
   便利入口。返回的 `note.path` 是 receipt 绑定的不可变路径，`note.latest_path` 是
   用户快捷入口。Note 至少包含会话主题、
   最终结果、未完成工作和记忆治理结果，并明确它是历史审计/可读性产物，不是当前
   项目真相。只复用已经提交的 semantic review，不启动额外导出，不重新消耗模型
   阅读原文。

   默认给简短但可理解的结果，不展示 transcript、session/job/candidate/memory/evidence/source ID 或详细计数：

   ```text
   会话：<session_summary>
   已完成整理：<形成长期记忆 / 无需长期记忆>。
   未完成：<无 / unfinished_work 摘要>。
   原文：<已保留 / 已删除 / 部分失败 / 当前宿主不支持>。
   Note：<路径>。
   ```

   如果形成长期记忆，在摘要和 Note 中按“一条记忆一个可验证事实”列出：

   ```text
   - **<标题>**：<精确、可验证的单一事实>（<验证日期；仓库已验证 / 用户已确认>）。
   ```

   ID 只用于内部去重、审计、纠错和 undo，不附加在默认记忆正文中。只有用户要求审计详情时，才展示计数、session/job/candidate/memory/evidence/source ID、verification refs 和 `/hm:review` 入口。

   如果用户要求处理多个 session，逐 job 完成 prepare → candidate/no-candidate →
   finalize/defer；一次显式 distill 最多处理 3 条，任一 job 的失败不得污染其他 job。

**Notes**

- `/hm:distill` 是当前宿主的立即执行入口：读取证据、生成会话摘要、提炼候选并自动处理当前 job 的低风险项；Hook 才会唤醒后台 Dream，默认摘要仍必须让用户知道会话做了什么
- `/hm:review` 是 audit inbox：确认、拒绝、undo、替换候选都在这里发生
- 成功蒸馏后默认尝试安全清理原文；只删除适配器支持且通过静默/CAS/hash 校验的独立来源，共享或不安全容器保持不动；项目可配置 `distill.delete_source_after_complete=false` 保留原文，实际结果以 `source_cleanup.status` 为准
- 不要把具体客户端写死为默认来源；默认入口必须是 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根目录>)`
- agent 历史可能是用户全局数据源，默认必须按当前项目路径过滤；跨项目导入必须由用户显式要求 `scope="all"`
- 用户主路径只有 `hm-distill` 的 Slash / 自然语言 + MCP + Skill；没有第二套 distill CLI 兜底
- MCP server 的 cwd 不等于当前 agent 项目目录；调用 `prepare_session_distill` 时必须显式传 `project_root`。`ingest_sessions` 是低层诊断/同步工具，不是用户主路径
