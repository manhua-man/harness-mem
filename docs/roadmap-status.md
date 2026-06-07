# Roadmap Status（公开状态页）

> 最后核对：2026-06-08。版本号以 `pyproject.toml` 与 `harness_mem.__version__` 为准；发版记录见 `CHANGELOG.md`。
>
> 本文面向**使用者与贡献者**：说明当前版本、已交付能力、明确不做项，以及规划中的方向。
> 逐版本设计稿见 `docs/roadmap-v*.md`；**不**在此复述客户端联调矩阵、运行日志或本机路径。
> 发版审计与跨客户端测试包见文末「维护者材料」。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `3.4.4` |
| `harness_mem/__init__.py` | `3.4.4` |
| `CHANGELOG.md` | 已有 `3.4.4` 段；`Unreleased` 当前为空 |

## 产品基线

当前收口基线是 v3.4.4：v1.5 baseline、v1.6 persistent vectors / bucket budget、
v1.7 temporal truth、v1.8 procedural skill、v2.0 heuristic distill 移除、
v2.1 maintenance-only CLI、v2.2 用户入口闭环、v2.3 signals/replay、v2.4
reflection queue（默认关闭的 opt-in host 触发）、v2.5 context assembly /
wake renderer / file_context、v2.6 knowledge cache / wiki bridge /
contradiction 候选面、v2.7 cross-project procedural skill、v2.8
session-distill maintenance surfaces，v2.9.0–v2.9.61 这一整条从 `/hm:prd-sync`
起步、随后扩成 maintenance / triage /
truth-sync 的 release train、v3.1 Auto Dream Memory Maintenance、v3.2
Generated Knowledge Compiler + Basic Freshness、v3.3 Temporal Query and
Supersede Explainability，以及 v3.4.x Runtime Health, Cost Discipline, and
Regression Gates 都已落地。

v3.2.0 已发布 Generated Knowledge Compiler + Basic Freshness：source map、
atomic claim metadata、citation validation、claim diff、incremental compile metrics、
freshness/status 可见性和 compact context drilldown 已落地；generated wiki / compact
output 仍不替代 confirmed truth。

v3.3.3 已发布 Temporal Query and Supersede Explainability：MCP
`temporal_query` 可按 current/history/as_of 查询 confirmed truth 的 temporal read
model，返回 valid/recorded time、source provenance、supersede chain、timeline、
explanation 和 abstention metadata；它是 read-side projection，不改写 truth。

当前版本 v3.4.4 已发布完整 v3.4.x：MCP tool 成功调用后会在本地
`events.log` 记录 surface cost 元数据，估算 wake/search/distill/file_context/dream
等输出 token，标记 high-output，并通过 MCP `surface_cost_report` 汇总最近高成本调用
和 drilldown 机会；runtime health report 汇总 job/cache/retrieval health；
benchmark matrix report 显示 per-surface regression gate；version drift report 检查
plugin/skill/slash/MCP wire-format；cost budget policy 记录预算、截断和 drilldown 元数据。
observer 不保存 raw query、raw path 或 response content；失败不阻断主调用。

日常用法：`/hm:distill`、`/hm:wake`、`/hm:search`（或自然语言等价指令）；默认启用的
`harness-mem-autopilot` skill 提供 conversation-level 自动学习：在清晰任务边界主动
wake/search、创建有证据的候选或建议 distill。学习结果仍走 candidate/review loop；
没有后台 daemon / hook、无条件 turn-end 写入或静默 durable truth 写入。

## 已交付能力（按主题）

| 主题 | 你能用到什么 | 说明 |
|---|---|---|
| 检索与证据 | 渐进式 search → timeline → 原始 observation；可选 hybrid 向量 | 默认 embedding 基线 `all-MiniLM-L6-v2` |
| 真理与候选 | MemoryEntry、Rule、Relation、Handoff、Supersede/Skill 等候选层；`auto_review` 处理低风险项 | 高风险与证据不足仍交给人 |
| 用户入口 | `/hm:*`、repo-local Skill、自然语言；MCP 在 Agent 背后 | CLI 仅安装、doctor、purge、maintenance |
| Conversation Autopilot | `harness-mem-autopilot` skill 默认启用，可在明确任务边界主动 wake/search、创建证据候选或建议 distill | conversation-level 自动学习；`autopilot.enabled=false` 是显式关闭；不启用 daemon、hook、无条件 per-turn 写入或 silent confirmed truth |
| Distill | `prepare_session_distill` + LLM `suggest_*`；多客户端 session 自动识别 | v2.0 起已移除启发式 distill |
| Wake | 分层 wake（L0–L2 已确认真理）；可选 compact renderer、skill hints | 默认不注入 pending 或完整 Skill body |
| 维护面 | `/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry`、`/hm:prd-sync`、`/hm:status` | PRD sync 默认 dry-run |
| Auto Dream | `/hm:dream` 读取 DreamRun 账本；MCP `dream_ledger` / `dream_run` / `dream_auto_tick` / `undo_dream_item` 支撑 opt-in 自动维护 | 默认关闭；没有 `pending_review`；不 hard delete confirmed truth |
| Generated Knowledge | `maintenance rebuild-wiki-bridge` 产出 source map、atomic claims、claim diff、freshness / compile metrics；compact wake 显式 opt-in 消费可校验 claim | generated layer 不是 truth；hash drift / citation invalid 的 claim 不进 compact wake |
| Temporal Query | MCP `temporal_query` 读取 temporal read model，支持 current/history/as_of、valid/recorded range、supersede timeline、explanation、abstention | read-side projection；不自动改写 confirmed truth |
| Runtime Health / Cost | MCP `health_summary`、`get_project_status`、`surface_cost_report`、`benchmark_matrix_report` 汇总 job health、generated cache、retrieval latency/result/truncation、surface token、budget overrun、version drift 和 regression gates | 不采集云端、不保存 raw content；observer 失败不阻断主路径；cost discipline 单独成类 |
| 可选触发 | `host_entry` + IDE hook 模板（`triggers.*` 默认 `off`） | 无 always-on daemon；`worker.mode` 仅为配置门控 |
| 跨项目 Skill | 显式 shared `search_skills`、审核后 promotion | 不进默认 wake、不静默跨项目注入 |

## 发版锚点

| 切片 | 状态 |
|---|---|
| v1.5.x – v2.8.x | 已完成（详见各 `docs/roadmap-v*.md` 与 `CHANGELOG.md`） |
| v2.9.x | 已完成：PRD sync、状态分诊、维护面与入口文档真值收口 |
| v3.1.0 | 已发布：Auto Dream Memory Maintenance |
| v3.1.x | 已发布：Auto Dream Memory Maintenance |
| v3.2.0 | 已发布：Generated Knowledge Compiler + Basic Freshness |
| v3.2.x | 已发布：Generated Knowledge Compiler + Basic Freshness |
| v3.3.0 | 已发布：Temporal Query and Supersede Explainability |
| v3.3.1 | 已发布：Release CI dependency fix |
| v3.3.2 | 已发布：Cross-platform CI compatibility |
| v3.3.3 | 已发布：Plugin Script CI Compatibility |
| v3.3.x | 已发布：Temporal Query and Supersede Explainability |
| v3.4.0 | 已发布：MCP Surface Cost Observer |
| v3.4.1 | 已发布：Runtime Health Report |
| v3.4.2 | 已发布：Benchmark Matrix and Regression Gates |
| v3.4.3 | 已发布：Version and Install Drift Visibility |
| v3.4.4 | 当前版本：Cost Budget Policy |
| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates |

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / 默认 IDE 随手记 | host 触发已实现但默认 `off`；无 always-on daemon | 见 `docs/roadmap-v24.md` |
| Context Assembly / File Context | 已完成 | 见 `docs/roadmap-v25.md` |
| Wiki Bridge / Compact Index | 已完成到 v3.2.0；compact wake 为 opt-in，generated compiler 有 source map / citation / freshness / metrics | 见 `docs/roadmap-v26.md` 与 `docs/roadmap-v32.md` |
| Temporal Query / Supersede Explainability | 已完成到 v3.3.0；`temporal_query` 提供 read-side current/history/as_of 与 supersede timeline | 见 `docs/roadmap-v33.md` |
| 自动改写 confirmed truth | 不做 | 仅 candidate / review / supersede |
| 跨项目 Skill 默认注入 wake | 不做 | v2.7.x non-goal |
| REST API 作为产品入口 | 已移除 | 不恢复 |
| CLI 日常 `wake` / `search` / 候选复核 | 已移除 | IDE / Agent + MCP |
| v1.9「Dream」旧 vision | 已拆分 | v2.3–v2.4、v2.6；v3.1 为新的可选自动维护设计 |

## 规划中

| 切片 | 状态 | 目标 | 文档 |
|---|---|---|---|
| v3.4.x Runtime Health, Cost Discipline, and Regression Gates | 已发布 | 已落地本地 cost observer、token estimate、high-output detection、missed-opportunity hints、per-surface token budget、runtime health report、benchmark regression gates、version drift visibility | `docs/roadmap-v34.md` |

## 版本索引

| 切片 | 主题 | 文档 |
|---|---|---|
| v1.5.x | Retrieval baseline + ingest/onboarding 基础：自动 ingest、跨项目搜索、doctor/安装闭环 | `docs/roadmap-v15x.md` |
| v1.6.x | Persistent vectors + memory typing + bucket budget：measurement foundation、typing、persistent vectors | `docs/roadmap-v16x.md` |
| v1.7.x | Temporal truth + supersede + bounded relation graph：temporal schema、supersede、verbatim exact evidence search | `docs/roadmap-v17x.md` |
| v1.8.x | Procedural memory 保守闭环：`ProceduralCandidate`、confirmed `Skill`、`search_skills`、`record_skill_result` | `docs/roadmap-vision-v16-v18.md` |
| v2.0.x | Heuristic distill 移除：distill 从 heuristic runtime 收束成 LLM agent 流程 | `docs/roadmap-status.md` |
| v2.1.x | Maintenance-only CLI + Slash/Skill/Agent workflow 重写：daily-memory surface 退出 CLI | `docs/roadmap-status.md` |
| v2.2.x | AI IDE 入口闭环：`/hm:distill`、`/hm:wake`、`/hm:search`、跨客户端测试、auto-review UX | `docs/roadmap-v22x.md` |
| v2.3.x | Signals / Replay 地基：`RetrievalSignal`、`MetabolismRun`、replay window、`metabolism_preview` | `docs/roadmap-v23.md` |
| v2.4.x | Host-triggered Reflection + Queue Health：job lifecycle、config toml、维护子命令管配置、hook 仅业务命令、doctor | `docs/roadmap-v24.md` |
| v2.5.x | Context Assembly + File Context：Memory Stack renderer、file-context、分层 wake | `docs/roadmap-v25.md` |
| v2.6.x | Wiki Bridge + Compact Index + Contradiction：knowledge cache、claim index、stale/merge/supersede suggestions | `docs/roadmap-v26.md` |
| v2.7.x | Cross-Project Skills + Controlled Activation：shared skills、skill hints、skill improvement suggestions | `docs/roadmap-v27.md` |
| v2.8.x | Session-Distill Maintenance Surfaces：`/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 的正式版本线 | `docs/roadmap-v28.md` |
| v2.9.x | PRD sync 起步，随后扩成 maintenance / triage / truth-sync release train：`/hm:prd-sync`、`/hm:status`、plugin doctor helper、maintenance CLI collateral、reflection/config truth sync、wake/distill/status 入口真值收口 | `docs/roadmap-v29.md` |
| v3.1.x | Auto Dream Memory Maintenance：自动做梦、自动解析、自动处理全部结果，单入口 `/hm:dream` 梦境账本 | `docs/roadmap-v31.md` |
| v3.2.x | Generated Knowledge Compiler + Basic Freshness：source map、atomic claim、incremental cache、基础 freshness / compile metrics、generated context UX | `docs/roadmap-v32.md` |
| v3.3.x | 已发布：Temporal Query and Supersede Explainability：current/history/as_of 查询、supersede timeline、explanation、abstention；多跳图后置 | `docs/roadmap-v33.md` |
| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates：token budget、runtime health report、benchmark regression、version drift | `docs/roadmap-v34.md` |

## 短结论

从 v1.5 baseline 到 v3.4.4 Runtime Health, Cost Discipline, and Regression Gates，主实现路线已经按一个版本一个文档重切并连续收口。
v1.5 baseline、v1.6 persistent vectors / bucket budget、v1.7 temporal truth、
v1.8 procedural skill、v2.0 heuristic distill 移除、v2.1 maintenance-only CLI、
v2.2 用户入口闭环（Slash/Skill/自然语言 + Agent 背后 MCP；跨客户端能力已交付，细节见维护者测试包）、
v2.3 signals/replay、v2.4 reflection queue、v2.5 context assembly、v2.6
wiki/contradiction、v2.7 cross-project skill、v2.8 session-distill maintenance，
以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release train、
v3.1 的默认关闭 Auto Dream / DreamRun 账本 / handle-all / undo 面、v3.2 的
source map / atomic claim / citation validation / incremental metrics、v3.3 的
current/history/as_of temporal query / supersede timeline / abstention，以及 v3.4.x 的
MCP surface cost observer / high-output detection / `surface_cost_report` / runtime health /
benchmark matrix / version drift / cost budget policy 都已落地。

当前仍未启用 always-on daemon；shared skill 坚持显式消费；truth 变更只走候选与人工复核。

v3.1 Auto Dream Memory Maintenance 默认关闭、用户显式开启；在保留审计与撤销的前提下组合 signals / metabolism / reflection，并优先复用客户端/host 的定时触发能力，而不是引入独立后台进程。

v3.4 已收口 runtime health report / regression gates / version drift / budget policy；
后续只保留 artifact-backed benchmark 扩展与 dashboard 等非必要后置项。

## 维护者材料（非用户文档）

| 材料 | 用途 |
|---|---|
| `docs/v2-user-test-packet.md` | 跨客户端 release 测试包（仅完整 clone；公开源码归档已排除，见 `docs/releasing.md`） |
| `docs/roadmap-v29.md` 及 `openspec/changes/archive/` | 切片级验收与历史决策链 |

请勿将上述文件中的场景编号、客户端日志或本机路径摘进对外 README。
