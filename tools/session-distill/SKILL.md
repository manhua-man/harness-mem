---
name: session-distill
version: 1.6.1
description: |
  Harness-mem 项目的主动会话蒸馏技能。用于把当前项目相关的 Codex / Claude Code / Cursor / Antigravity / opencode / Hermes / generic agent 会话整理成候选记忆，并自动处理低风险项。
  当用户主动要求蒸馏会话、整理记忆、提炼经验、固化项目规则或生成任务交接时使用（无论触发方式是 slash 命令、自然语言请求还是其他客户端入口）。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - mcp__mcp_router__get_project_status
  - mcp__mcp_router__prepare_session_distill
  - mcp__mcp_router__submit_distill_chunk
  - mcp__mcp_router__finalize_session_distill
  - mcp__mcp_router__govern_memory
  - mcp__mcp_router__list_candidates
  - mcp__harness_mem__get_project_status
  - mcp__harness_mem__prepare_session_distill
  - mcp__harness_mem__submit_distill_chunk
  - mcp__harness_mem__finalize_session_distill
  - mcp__harness_mem__govern_memory
  - mcp__harness_mem__list_candidates
---

# Session Distiller (harness-mem 主链)

## 定位

`session-distill` 是用户主动蒸馏时的默认体验层。

本目录中的 `SKILL.md` 和 references 是 `/hm:distill` 的 Agent 指令层；
本目录不包含独立 CLI、packet store 或 runtime helper。所有执行、持久化和
治理能力都由 `harness_mem` MCP/runtime 提供。
与多平台上游 `session-distill-skills` 的机制同步边界见
[`UPSTREAM_ALIGNMENT.md`](UPSTREAM_ALIGNMENT.md)。

默认目标是把当前项目相关会话转成候选，并在同一轮里运行 auto-review apply-low-risk。低风险项可以自动进入 `auto_confirmed` 或 `provisional` 记忆；`/hm:review` 是事后 audit / undo / confirm 入口，不是日常逐条写入闸门。

## 主链

用户只有一条默认主链：`/hm:distill` / 自然语言等价入口。Agent 不要求用户区分 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 历史；入口统一调 `prepare_session_distill(client="auto", scope="project", project_root=<当前项目根>, evidence_mode="semantic", detail_level="compact", budget_tokens=3000)`。runtime 自动识别来源、保存完整 native revision、校验并 checkpoint 全部原始 chunk，再返回按 exchange 组织的有序 compact manifest；重复事件、过程播报、被动 wait 和工具参数留在 drilldown，不占用日常 packet。

```text
模糊结论 / session-end
  -> MCP prepare_session_distill(client="auto", project scoped, evidence_mode="semantic")
  -> runtime 校验/checkpoint 全部 raw chunks；Agent 完整读取 compact manifest
  -> 按 drilldown_exchange_indexes 读取候选 semantic windows
  -> 必要时按 query/chunk index 读取候选相关 raw proof
  -> prepare_session_distill 返回 reviewing 状态
  -> final-session semantic review
  -> grill-me 准入（标准模式：高风险深度拷问 / 普通候选轻量 checklist）
  -> distillation-rules
  -> govern_memory(action="suggest")（admit；narrow 后可写；defer/reject 不写）
  -> 内部 search_memory / 代码检索；外部来源证据（smart-search 为参考候选，confirm 前必须补证）
  -> finalize_session_distill（结构完整性 + 会话末尾审查后，限定当前 job 自动审核并运行 Dream）
  -> /hm:review audit / undo / user_confirmed
```

## 默认动作序列

### 0. MCP 工具命名

先检查当前 task 的可调用工具，再按逻辑名选择实际 namespace：
`prepare_session_distill`、`submit_distill_chunk`、`finalize_session_distill`、
`govern_memory` 等。客户端如何把它们映射成可调用 alias（带短横线 /
不带短横线 / 带 server 前缀）由客户端自己决定，本 skill 不假设。

通过 MCP Router 接入 Codex 时，工具通常位于 `mcp__mcp_router__*`；直连
server 时通常位于 `mcp__harness_mem__*`，也有客户端直接暴露裸工具名。
三种都能跑，prompt 里不要写死单一前缀。查询 `harness_mem` /
`harness-mem` alias 失败时，必须先检查 `mcp_router` 和当前工具清单，再判断
MCP 是否真的不可用。

MCP 对外是单一 public memory surface。`finalize_session_distill` 是当前 job
唯一收尾入口，并在语义门禁通过时执行限定范围的 low-risk auto-review；
`/hm:review` 用于审计、undo、用户确认、拒绝和 supersede。

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
- `evidence_mode="semantic"`
- `detail_level="compact"`
- `budget_tokens=3000`

不要用 `observation_limit` 或 `max_chars_per_observation` 把 native transcript
当成摘要窗口。存在完整 source revision 时，runtime 会校验并 checkpoint 全部
expected raw chunks，同时返回由宿主 parser rendering 确定性生成的
`semantic_evidence.chunks` compact manifest：保留全部 exchange 索引、风险信号
和短预览。Agent 必须按 `semantic_chunk_index` 顺序完整读取 manifest；然后对
可能产生候选的索引调用 `drilldown_exchange_indexes=[...]` 读取完整 semantic
window。具体命令、精确版本、错误堆栈或被折叠过程若要成为候选证据，必须再做
raw drilldown。只有 native transcript 不可用时，
才会返回明确标记为 `legacy_partial` 的 observation 审计视图，该视图不得宣称
完整读取或自动提升。

默认只摄取当前 agent 环境、当前项目路径匹配的 session。

- Claude Code: 读取与当前项目路径对应的 `~/.claude/projects/...` 会话目录。
- Codex: 读取 Codex rollout/archive，并按 session `cwd` 过滤到当前项目路径。
- 只有用户明确要求跨项目/全局历史时，才允许 `scope="all"`。

semantic 快路径返回时 job 已进入 `reviewing`。先对候选索引调用
`prepare_session_distill(..., evidence_mode="semantic",
drilldown_exchange_indexes=[...])`；如果某条候选还需要命令输出、精确版本或
其它高风险原文证据，再调用
`prepare_session_distill(..., evidence_mode="semantic",
drilldown_query="<关键词>")`；已知位置时也可用
`drilldown_chunk_indexes=[...]`。最多读取 8 个只读 raw chunk；不要重复提交。

`detail_level="full"` 只用于显式完整语义审计。日常不得用 full 绕过 compact
预算；`budget_state` 表示消费视图预算状态，不表示 raw revision 被截断。

如果 runtime 明确回退为 `evidence_mode="raw"`，或用户明确要求逐字/合规审计，
则逐块完整读取返回的 raw chunk，用 `distill_job_id`、`chunk_id`、`lease_owner`
调用 `submit_distill_chunk`，直到 `reviewing`。不要调用
`Bash`、`cmem`、`timeline`、`get_observations`、`ls`、`cat` 或 `find` 去摸索
同一份 transcript；只有工具报错或明确返回 `legacy_partial` 时才排障。

### 3. 读 packet、draft claims、标准准入（grill-me / grill-before-distill）

进入 `reviewing` 后，semantic 模式按 `semantic_chunk_index` 汇总全部 evidence；
raw 兼容模式按 `chunk_index` 汇总 checkpoint result。完成一次
覆盖整场会话的 final-session review，再形成 candidate claim。然后自动跑准入
（无需用户说「先拷问」）。能加载 `plugins/harness-mem/skills/grill-before-distill`
就用；否则内联同规则。不要让 `tools/session-distill` 硬依赖某个插件安装路径。

final-session review 必须包含：`final_user_request`、`final_outcome`、
`last_turn_status`、`contradictions`、`unfinished_work`、`evidence_status`、
`promotion_decision`。不得从局部 chunk 推断这些整场字段。

**按风险选深度，不要每次都走重流程：**

| 场景 | 模式 |
|---|---|
| 用户明确规则 / 高影响记忆 | **深度拷问**（一次一问） |
| 普通 distill 候选 | **轻量 checklist** 过一遍 |
| 已确认记忆回看 | **lookback**（dream/抽查；见 skill Mode C） |

结合 `references/distillation-rules.md` 判断每条 claim。`admit` 进入 Step 4；`narrow` 改窄后进入 Step 4；`defer` 本轮不写候选，后续有新证据时再处理；`reject` 不写候选。

### 4. 写候选（govern_memory）

仅对 Step 3 为 `admit` 或已改窄的 `narrow` 项调用
`govern_memory(action="suggest")`。

产出时优先拆成几类：

- `arguments.kind="memory"`: 稳定项目知识、架构事实、可复用排障经验。
- `arguments.kind="rule"`: 会改变未来 AI 默认行为的项目规则。
- `arguments.kind="relation"`: 明确的依赖、归属、替代、冲突等实体关系。
- `action="handoff"`: 当前任务状态、阻塞点、下一步。

这些 suggest 工具只写 candidate layer。不要退回 CLI 或直接写 truth；如果工具不可用，应停止并报告当前 MCP surface 不完整。

每条候选都必须带 0.9.5 evidence envelope：`evidence_basis`、
`verification_outcome` 和 content-free `verification_refs`。

- 代码、API、文件、版本、发布和测试状态：只允许 `repository + verified`；ref
  使用项目相对路径与当前文件 SHA-256。Agent 负责语义判断，runtime 在准入前重新
  校验路径边界和摘要当前性。
- 用户明确偏好、纠正或项目决定：使用
  `user_statement + verified/not_applicable`；ref 只保存 user role、exchange index
  和完整 semantic window SHA-256。
- 只有 transcript 说法且无法由仓库或用户明确陈述验证：使用
  `transcript + unverified`。它可以解释为什么没有候选，但不能晋升 durable truth。
- ref 不得保存绝对路径、session id、source alias 或证据正文。证据不足时不要伪造
  `verified`；finalize 会将缺失、变化、越界或不匹配的 envelope 终结为 rejected。

外部事实、政策、论文或第三方 API 语义没有项目本地可验证来源时，默认不生成
durable candidate。smart-search 只是参考候选，不是当前 hm 依赖或已安装能力。

不要生成这些候选：

- 当前 distill 调用过程本身（无论是 slash、MCP 还是其他触发方式）。
- `Bash`、`cmem`、`ToolSearch`、MCP 参数错误、agent idle、TeamCreate/SendMessage/TeamDelete 等工具编排故障，除非目标项目本身就是这些工具。
- `/plan-eng-review`、`/plan-ceo-review`、`/plan-design-review` 等 AI review workflow，除非用户明确要记录为全局工作流记忆。
- 对应用/游戏项目而言，把 AI 工作流、评审方式或工具名写成项目架构事实。

### 5. 最终审查与自动审核

完成每个 lossless chunk 的 checkpoint 后，提交会话末尾审查并调用
`finalize_session_distill(project_name=<project>, job_id=<job>, semantic_review=...)`。
它只审核该 `distill_job_id` 产生的候选，且仅当 `promotion_decision="promote"`
时才会 apply-low-risk 并运行 Dream。

默认 distill 路径必须直接消费 `finalize_session_distill` 返回的自动治理结果。shared policy 自动确认安全项，并终结噪声、高风险或证据不足项，使已完成 job 不留下日常人工待办：

- `auto_confirmed`
- `auto_rejected`
- `completion.disposition` (`promoted` / `no_candidate`)
- `source_cleanup.status` (`retained` / `deleted` / `partial_failure` / `unsupported`)
- `applied_decisions`
- `evidence_admission` (`repository_verified` / `user_stated` /
  `unverified_blocked` / `contradicted`)

日常摘要使用 `completion.disposition`、`queue_effect` 和 `source_cleanup.status`；`applied_decisions` 留在 audit drilldown。若用户追问某个候选为什么被确认或拒绝，解释 candidate id、evidence id 和 policy reason。

`list_candidates` 可用于显式 review drilldown。`auto_review_candidates` 是项目级审计/维护工具，不是 lossless session 的收尾入口；`govern_memory(action="decide")` 属于 `/hm:review` durable gate，不是默认 distill 主链。

最后给用户看自动处理摘要，只说明“形成长期记忆/无需长期记忆”和原文的实际清理状态；需要细节时再提示 `/hm:review` 审计或 undo。

## Runtime guardrails

- native transcript revision 是权威证据；compact manifest 和 semantic window 都是同 revision 的 parser-derived 消费视图，不是第二份 truth，也不能替代候选所需的精确 raw proof。
- 每个 expected raw chunk 都必须有 durable checkpoint，才能进入 final review；semantic 快路径由 runtime 完成 hash 校验和 checkpoint。
- final review 未通过时，不 auto-review、不 Dream，候选终结为 rejected，job 记为 `no_candidate`。
- distill 默认保留宿主 transcript 和 raw revision。只有持久配置
  `distill.delete_source_after_complete=true` 时，完成链才执行 receipt-first
  source cleanup；长期 truth 保留并标记 `source_pruned` provenance，实际结果
  必须按 `retained/deleted/partial_failure/unsupported` 报告。
- 不创建独立 manifest、packet workspace、session note 或 memory-drafts truth store。

KB / PRD 语义不再作为 session-distill 的独立子系统存在。产品决策、架构事实、项目知识和规则都应抽成 harness-mem candidates，由 finalize 自动治理；`/hm:review` 用于事后纠错和 undo。正式 PRD 或 roadmap 文档若存在，属于普通项目文档编辑，不由 session-distill 维护。

## Dream maintenance boundary

session-distill 不再定义独立的后台维护入口。它只负责指导 Agent 从完整
compact manifest、选中的 semantic windows 和 raw proof（或 raw checkpoint results）生成 harness-mem candidates；没有 Agent 时只排队并显示 `waiting_for_agent`
wake/search/review 等路径产生的 signals。

- **没有独立维护 MCP 工具**。不要调用或描述 standalone preview/run 维护工具；对外入口是 `/hm:dream` / MCP dream tools 和 dream ledger/undo。
- **Signals 是后台证据，不进入本 skill 主链**。`wake_surfaced` / `search_hit` / `confirmed` / `rejected` / `supersede_completed` 等信号由 runtime 记录，dream 在自己的调度窗口中消费。
- **durable write 必须可审计**。session-distill 产候选并由 finalize 自动治理；`/hm:review` 用于事后纠错、undo 或显式升级 trust tier，自动维护通过 dream ledger 审计。dream/lookback 处理已确认或维护中的 truth，不是新候选准入动作。

## 外置协作者

| 协作者 | 默认? | 职责 |
|---|---|---|
| `grill-before-distill` (grill-me) | **是**（标准准入，按风险分档） | `govern_memory(action="suggest")` 之前给主链动作：admit / narrow / defer / reject；已确认记忆回看用 lookback |
| smart-search-style CLI | 否（参考候选） | 外部主张举证方案研究；当前不作为 hm 依赖 |
| `search_memory` | 是（MCP） | 仓库内主张举证，review 前 |
| Trellis | 否（项目级） | PRD/任务编排，不进 hm 核心 |

详见 `docs/memory-adoption.md`。smart-search / Trellis 仅作参考或项目级选择；准入分档逻辑不跳过（skill 不可用则内联轻量 checklist）。

## 不做的事

- 不要求普通用户手动跑 `harness-mem ingest` 或 `harness-mem distill`。
- 不默认把用户级全局 agent 历史灌进当前项目。
- 不把 "no patterns found" 当成最终高质量蒸馏结论；那只说明 fallback 没抽到明显模式。
- 不把逐条分类或晋升工作交给用户；AI 必须自动治理当前 job，高风险、冲突或证据不足项不进入 truth，review 只做事后纠错。
- 不维护独立的 `knowledge-base.md`、KB review/prune 命令、PRD sync 文件或产品文档桥。
- 不创建或调用独立 `session-distill.py` CLI；用户入口是 `/hm:*` 或自然语言等价命令。
- 不把 smart-search / Trellis 硬编码进 hm runtime；smart-search 当前只作为参考证据工具研究，grill-before-distill 是 distill 默认 Skill 步骤，不是新 MCP。

## 兜底策略

MCP 不可用时，明确报告 runtime 工具不可用；不要回退到已删除的独立 CLI。

Skill 无法读取足够 evidence 时，先报告缺口和下一步补证方式，不要把空结果包装成"蒸馏完成"。
