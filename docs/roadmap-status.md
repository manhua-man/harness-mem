# Roadmap Status（公开状态页）

> 最后核对：2026-06-16。版本号以 `pyproject.toml` 与 `harness_mem.__version__` 为准；发版记录见 `CHANGELOG.md`。
>
> 本文面向**使用者与贡献者**：说明当前版本、已交付能力、明确不做项，以及规划中的方向。
> 逐版本设计稿见 `docs/roadmap-v*.md`；**不**在此复述客户端联调矩阵、运行日志或本机路径。
> 发版审计与跨客户端测试包见文末「维护者材料」。

## 当前版本

| 来源 | 值 |
|---|---|
| `pyproject.toml` | `5.0.0` |
| `harness_mem/__init__.py` | `5.0.0` |
| `CHANGELOG.md` | 已有 `5.0.0` 段；`Unreleased` 当前为空 |

## 产品基线

当前收口基线是 v5.0.0：v1.5 baseline、v1.6 persistent vectors / bucket budget、
v1.7 temporal truth、v1.8 procedural skill、v2.0 heuristic distill 移除、
v2.1 maintenance-only CLI、v2.2 用户入口闭环、v2.3 signals/replay、v2.4
reflection queue（默认关闭的 opt-in host 触发）、v2.5 context assembly /
wake renderer / file_context、v2.6 knowledge cache / wiki bridge /
contradiction 候选面、v2.7 cross-project procedural skill、v2.8
session-distill maintenance surfaces，v2.9.0–v2.9.61 这一整条从 `/hm:prd-sync`
起步、随后扩成 maintenance / triage /
truth-sync 的 release train、v3.1 Auto Dream Memory Maintenance、v3.2
Generated Knowledge Compiler + Basic Freshness、v3.3 Temporal Query and
Supersede Explainability、v3.4.x Runtime Health / Cost Discipline / Regression Gates、
v3.5 Benchmark Evidence and Public Claim Readiness、v3.6 Generated Claim Hardening、
v3.7 Skill Evolution Governance、v3.8 True Hybrid Retrieval Shootout contract，
v4.0.0 Storage v2 Baseline / Benchmark / Migration Contract、v4.0.1-v4.0.5
canonical store / Rust facade / index fabric / lifecycle / distribution gate，
v4.1.0 Context Sufficiency + Task-Aware Wake、v4.2.x Memory Eval Matrix /
Retrieval Quality Pack、v4.3.0 Code-Memory Federation、v4.4 Claim Promotion
Pack、v4.5.0 Release Evidence Pack，以及 v4.6-v5.0 Evidence Hardening Track
都已落地。

v3.2.0 已发布 Generated Knowledge Compiler + Basic Freshness：source map、
atomic claim metadata、citation validation、claim diff、incremental compile metrics、
freshness/status 可见性和 compact context drilldown 已落地；generated wiki / compact
output 仍不替代 confirmed truth。

v3.3.3 已发布 Temporal Query and Supersede Explainability：MCP
`temporal_query` 可按 current/history/as_of 查询 confirmed truth 的 temporal read
model，返回 valid/recorded time、source provenance、supersede chain、timeline、
explanation 和 abstention metadata；它是 read-side projection，不改写 truth。

v3.4.4 已发布完整 v3.4.x：MCP tool 成功调用后会在本地
`events.log` 记录 surface cost 元数据，估算 wake/search/distill/file_context/dream
等输出 token，标记 high-output，并通过 MCP `surface_cost_report` 汇总最近高成本调用
和 drilldown 机会；runtime health report 汇总 job/cache/retrieval health；
benchmark matrix report 显示 per-surface regression gate；version drift report 检查
plugin/skill/slash/MCP wire-format；cost budget policy 记录预算、截断和 drilldown 元数据。
observer 不保存 raw query、raw path 或 response content；失败不阻断主调用。

v3.8.0 已完成 v3.5–v3.8 收口：benchmark matrix 升级到 artifact-state
taxonomy、BENCH purpose map、`RESULTS.md` / release snapshot / public-claim gates；
generated compact 输出携带 Trust / Drilldown，hash drift 或 invalid citation 进入
generated review queue；skill result outcome ledger 记录 success/failure、surface、
source ids 与 reason，但不改写 skill body；true-hybrid retrieval shootout 有 fixture
manifest、dataset/query contract、report renderer、retrieval recall gate 与 embedding
候选治理。当前 token/cost saving 仍为 `ready=false`；true vector-hybrid latency 与
retrieval recall 只对 2026-06-09 本地 synthetic / smoke artifact ready，不能写成
生产延迟、端到端回答正确率或 broad corpus quality。

v4.5.0 已完成剩余 v4.0.x、v4.1.x、v4.2.x、v4.3.x、v4.4 和 v4.5 runtime foundation：v4.0.0
保留 Storage v2 dry-run / apply / rollback contract；v4.0.1 新增 canonical
SQLite store、JSON snapshot export 与 storage doctor report；v4.0.2 新增
Rust core facade / crate skeleton 与 pure-Python fallback；v4.0.3 新增 Local
Memory Index Fabric 和 SearchBackend contract；v4.0.4 新增 hot/warm/cold/archive
lifecycle tiering 与 `deep_recall`；v4.0.5 新增 distribution report；v4.1.0
新增 deterministic `context_sufficiency`、`retrieval_plan`、`context_plan`、
`iterative_retrieval_trace`、query rewrites、required-slot gates 和 task-aware
`wake_packet`；v4.2.x 新增 `memory_eval_matrix`、retrieval quality pack、
bounded multi-query/rewrite profiles 与 optional reranker dependency profile；
v4.3.0 新增 code-memory federation，让 `file_context` 返回 current file
fingerprint、Python symbols 和 stale code-evidence status；v4.4 新增
claim-promotion policy gate，机器化区分 blocked public claims 与 bounded local
claims；v4.5 新增 release-evidence pack，验证 clean-checkout snapshot、
packaged benchmark resources 与 claim-promotion visibility。

当前版本 v5.0.0 在此基础上完成 v4.6-v5.0 Evidence Hardening Track：v4.6
补齐 cost/token evidence；v4.7 把 `storage_v2_baseline`、
`migration_roundtrip` 和 `canonical_store_runtime_baseline` 推到 accepted
`10k/100k/1m` scale runs；v4.8 补齐
`index_fabric_runtime_conformance` runtime artifact；v4.9 通过 PyO3 暴露可导入的
native `harness_mem_core_rs` 模块并让 `rust_core_hot_path` 进入 accepted
release snapshot；v5.0 把 `evidence_hardening_track` 和
`default_change_decision_gate` 机器化到 `benchmark_matrix_report` 与 release
snapshot。

v4.0.x-v5.0 的 benchmark suite 已新增 `canonical_store_runtime_baseline`、
`rust_core_hot_path`、`index_fabric_runtime_conformance`、`context_sufficiency_gate`
和 `task_aware_wake_precision`、`memory_eval_matrix`、`retrieval_quality_pack`、
`code_memory_federation`、`claim_promotion_pack`、`release_evidence_pack`。
2026-06-12/2026-06-13/2026-06-16 的 canonical-store、context-sufficiency、
memory-eval、retrieval-quality、code-memory、claim-promotion、release-evidence
和 evidence-hardening artifacts 证明 contract / surface availability、claim
governance、默认项变更门槛与 bounded evidence 形状；它们不构成公开性能收益、全局
token saving、默认 reranker/HyDE 启用、ANN/Tantivy/LanceDB readiness、
code-intel token/runtime 或端到端回答质量 claim。

日常用法：`/hm:distill`、`/hm:wake`、`/hm:search`（或自然语言等价指令）；默认启用的
`harness-mem-autopilot` skill 提供 conversation-level 自动学习：在清晰任务边界主动
wake/search、创建有证据的候选或建议 distill。学习结果仍走 candidate/review loop；
受控自动化已做：autopilot、opt-in host hook / scheduler、默认关闭 Auto Dream。默认
常驻后台不做；truth 不静默改。

## 已交付能力（按主题）

| 主题 | 你能用到什么 | 说明 |
|---|---|---|
| 检索与证据 | 渐进式 search → timeline → 原始 observation；可选 hybrid 向量 | 默认 embedding 基线 `all-MiniLM-L6-v2` |
| 真理与候选 | MemoryEntry、Rule、Relation、Handoff、Supersede/Skill 等候选层；`auto_review` 处理低风险项 | 可以自动维护，但不能静默覆盖 confirmed truth；必须走 candidate / review / supersede / ledger |
| 用户入口 | `/hm:*`、repo-local Skill、自然语言；MCP 在 Agent 背后 | CLI 仅安装、doctor、purge、maintenance |
| Conversation Autopilot | `harness-mem-autopilot` skill 默认启用，可在明确任务边界主动 wake/search、创建证据候选或建议 distill | conversation-level 自动学习；`autopilot.enabled=false` 是显式关闭；不会默认启用 daemon / IDE hook、无条件 per-turn 写入或 silent confirmed truth |
| Distill | `prepare_session_distill` + LLM `suggest_*`；多客户端 session 自动识别 | v2.0 起已移除启发式 distill |
| Wake | 分层 wake（L0–L2 已确认真理）；可选 compact renderer、skill hints | 默认不注入 pending 或完整 Skill body |
| Context Sufficiency / Task-Aware Wake | `search_memory` / `wake` 返回 deterministic sufficiency report、retrieval plan、context plan、iterative trace；`wake` 可按当前任务和 token budget 组包 | 质量门是本地 deterministic check；证据不足时可建议补查或带 caveat，不自动改写 truth |
| Memory Eval / Retrieval Quality Pack | `benchmark_matrix_report` 暴露 memory eval matrix 与 retrieval quality component gate；默认 simple query 仍是轻路径，rewrite/multi-query 只在 multi-hop 或 insufficiency 后触发 | `harness-mem[rerank]` 只是 optional profile；不默认启用 reranker、HyDE 或更换 embedding baseline |
| Code-Memory Federation | `file_context` 可返回 current file fingerprint、Python symbols、code evidence stale status；MCP surface 支持 `project_root` | generated code wiki / module atlas 不是 truth store；代码证据只作为可复核 provenance |
| 维护面 | `/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry`、`/hm:prd-sync`、`/hm:status` | PRD sync 默认 dry-run |
| Auto Dream | `/hm:dream` 读取 DreamRun 账本；MCP `dream_ledger` / `dream_run` / `dream_auto_tick` / `undo_dream_item` 支撑 opt-in 自动维护 | 默认关闭；没有 `pending_review`；不 hard delete confirmed truth |
| Generated Knowledge | `maintenance rebuild-wiki-bridge` 产出 source map、atomic claims、claim diff、freshness / compile metrics；compact wake 显式 opt-in 消费可校验 claim | generated layer 不是 truth；hash drift / citation invalid 的 claim 不进 compact wake |
| Temporal Query | MCP `temporal_query` 读取 temporal read model，支持 current/history/as_of、valid/recorded range、supersede timeline、explanation、abstention | read-side projection；不自动改写 confirmed truth |
| Runtime Health / Cost / Benchmark Evidence | MCP `health_summary`、`get_project_status`、`surface_cost_report`、`benchmark_matrix_report` 汇总 job health、generated cache、retrieval latency/result/truncation、surface token、budget overrun、version drift、artifact-state taxonomy、BENCH purpose map、regression gates、true-hybrid shootout summary、v4.0.x-v5.0 surface coverage、public-claim readiness、claim-promotion gate、release-evidence pack、evidence-hardening track 和 default-change decision gate | 不采集云端、不保存 raw content；observer 失败不阻断主路径；cost discipline 单独成类；当前 token/cost saving 仍未 ready；true-hybrid latency / retrieval recall 只限本地 synthetic / smoke artifact；v4/v5 的 smoke/contract 不外推性能或回答质量；blocked claims 不因 release evidence 或 gate ready 自动升级成 public claims |
| 可选触发 | `host_entry` + IDE hook 模板（`triggers.*` 默认 `off`） | 无 always-on daemon；`worker.mode` 仅为配置门控 |
| 跨项目 Skill | 显式 shared `search_skills`、审核后 promotion | 可以跨项目复用，但不能默认污染 wake；必须显式搜索、提示、展开 |

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
| v3.4.4 | 已发布：Cost Budget Policy |
| v3.4.x | 已发布：Runtime Health, Cost Discipline, and Regression Gates |
| v3.5.x | 已完成：Benchmark Evidence and Public Claim Readiness |
| v3.6.x | 已完成：Generated Claim Hardening |
| v3.7.x | 已完成：Skill Evolution Governance |
| v3.8.0 | 已完成：True Hybrid Retrieval Shootout |
| v3.8.x | 已完成：True Hybrid Retrieval Shootout |
| v4.0.0 | 已完成：Baseline, Benchmark, and Migration Contract |
| v4.0.1 | 已完成：Canonical SQLite Store |
| v4.0.2 | 已完成：Rust Core MVP facade + fallback |
| v4.0.3 | 已完成：Local Memory Index Fabric + SearchBackend contract |
| v4.0.4 | 已完成：Lifecycle Tiering and deep recall |
| v4.0.5 | 已完成：Distribution and Release Gate diagnostics |
| v4.0.x | 已完成：Storage v2 + Rust Core + Local Memory Index Fabric runtime foundation |
| v4.1.0 | 已完成：Context Sufficiency + Task-Aware Wake |
| v4.2.x | 已完成：Memory Eval Matrix + Retrieval Quality Pack |
| v4.3.0 | 已完成：Code-Memory Federation |
| v4.4.0 | 已完成：Claim Promotion Pack |
| v4.5.0 | 已完成：Release Evidence Pack |
| v4.6-v5.0 | 已完成：Evidence Hardening Track |
| v5.0.0 | 当前版本：Evidence Hardening Track |

## 已完成：Evidence Hardening Track

这条线已经完成 artifact-backed evidence 收口：release snapshot 现保留历史
accepted runs，并叠加本轮新增的 v4.6-v5.0 evidence。完成不等于 public claim
放开，边界仍受限：

| 切片 | 当前状态 | 仍然不能说什么 |
|---|---|---|
| v4.6 Cost / Token Evidence | 已完成：`memory_shortcut_vs_source_recovery` accepted paired run + `functional_token_economics` accepted fixture run，`cost_token_evidence.passed=true` | 不能说全局 token/cost saving；只能说 bounded 长源恢复任务收益 |
| v4.7 Storage v2 Scale Evidence | 已完成：`storage_v2_baseline`、`migration_roundtrip`、`canonical_store_runtime_baseline` 都有 accepted `10k/100k/1m` runs，`storage_v2_scale_evidence.passed=true` | 不能把 contract/scale evidence 直接写成 public Storage v2 speedup，不能自动切默认 canonical store |
| v4.8 Index Fabric Runtime Evidence | 已完成：`index_fabric_runtime_conformance` accepted runtime artifact，`index_fabric_runtime_evidence.passed=true` | 不能说 Tantivy/LanceDB/ANN readiness 或 broad runtime superiority |
| v4.9 Rust Native Hot Path Evidence | 已完成：`harness_mem_core_rs` 通过 PyO3 暴露 native module，accepted `rust_core_hot_path` artifact 已进入 snapshot，`rust_native_hot_path_evidence.passed=true` | 不能把本地 bounded artifact 夸大成跨平台普适 Rust performance claim |
| v5.0 Default Change Decision Gate | 已完成：`default_change_decision_gate.ready=true` | 不因 gate ready 就自动改变默认 storage/index/reranker/HyDE；仍需显式产品决策 |

这条线吸收 `codedb-mcp` 的 index discipline、benchmark discipline 和
cost observer discipline；不把 `harness-mem` 变成 code-intel 产品，也不放松
candidate / review / supersede / ledger。

## 未完成 / 不做项

这些条目不要冒充已发布：

| 条目 | 当前状态 | 规划归宿 |
|---|---|---|
| 后台 daemon / 默认 IDE 随手记 | host 触发已实现但默认 `off`；无 always-on daemon | 见 `docs/roadmap-v24.md` |
| Context Assembly / File Context | 已完成 | 见 `docs/roadmap-v25.md` |
| Wiki Bridge / Compact Index | 已完成到 v3.2.0；compact wake 为 opt-in，generated compiler 有 source map / citation / freshness / metrics | 见 `docs/roadmap-v26.md` 与 `docs/roadmap-v32.md` |
| Temporal Query / Supersede Explainability | 已完成到 v3.3.0；`temporal_query` 提供 read-side current/history/as_of 与 supersede timeline | 见 `docs/roadmap-v33.md` |
| 自动改写 confirmed truth | 不做 | 可以自动维护，但不能静默覆盖；confirmed truth 变更必须走 candidate / review / supersede / ledger |
| 跨项目 Skill 默认注入 wake | 不做 | 可以跨项目复用，但不能默认污染 wake；shared skill 必须显式搜索、提示、展开 |
| REST API 作为产品入口 | 已移除 | 不恢复 |
| CLI 日常 `wake` / `search` / 候选复核 | 已移除 | IDE / Agent + MCP |
| v1.9「Dream」旧 vision | 已拆分 | v2.3–v2.4、v2.6；v3.1 为新的可选自动维护设计 |

## 已完成的 v3.5–v3.8 收口

| 切片 | 状态 | 目标 | 文档 |
|---|---|---|---|
| v3.5.x Benchmark Evidence and Public Claim Readiness | 已完成 | artifact state taxonomy、BENCH purpose map、`RESULTS.md`、release snapshot、public-claim gate | `docs/roadmap-v35.md` |
| v3.6.x Generated Claim Hardening | 已完成 | claim-first compiler、citation/hash validation、freshness / generated review queue、compact Trust / Drilldown | `docs/roadmap-v36.md` |
| v3.7.x Skill Evolution Governance | 已完成 | skill outcome ledger、revision/deprecation/promotion candidates、显式 shared activation | `docs/roadmap-v37.md` |
| v3.8.x True Hybrid Retrieval Shootout | 已完成 | FTS / vector / hybrid recall contract、latency/cost/fallback renderer、embedding shootout governance、retrieval recall claim gate | `docs/roadmap-v38.md` |

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
| v3.5.x | 已完成：Benchmark Evidence and Public Claim Readiness：BENCH artifact hygiene、RESULTS、public-claim gate | `docs/roadmap-v35.md` |
| v3.6.x | 已完成：Generated Claim Hardening：claim-first、citation verification、freshness / review queue | `docs/roadmap-v36.md` |
| v3.7.x | 已完成：Skill Evolution Governance：skill outcome ledger、revision/deprecation/promotion candidate、显式 activation | `docs/roadmap-v37.md` |
| v3.8.x | 已完成：True Hybrid Retrieval Shootout：FTS / vector / hybrid recall、latency、cost、fallback 对照 | `docs/roadmap-v38.md` |
| v4.0.0 | 已完成：Baseline, Benchmark, and Migration Contract：synthetic corpus、storage-v2 baseline、migration roundtrip、local index fabric smoke artifact schema | `docs/roadmap-v40.md` |
| v4.0.x | 已完成：Storage v2 + Rust Core + Local Memory Index Fabric：canonical store、Rust facade、index fabric/SearchBackend、lifecycle tiering、distribution gate | `docs/roadmap-v40.md` |
| v4.1.0 | 已完成：Context Sufficiency + Task-Aware Wake：sufficiency report、retrieval plan、context plan、iterative trace、wake packet budgeter | `docs/roadmap-v40.md` |
| v4.2.x | 已完成：Memory Eval Matrix + Retrieval Quality Pack：memory eval dimensions、retrieval quality component gates、optional reranker profile、bounded query rewrite/multi-query | `docs/roadmap-v40.md` |
| v4.3.0 | 已完成：Code-Memory Federation：file fingerprint、code symbols、code evidence stale checks、MCP `project_root` | `docs/roadmap-v40.md` |
| v4.4.0 | 已完成：Claim Promotion Pack：机器化 blocked / bounded / public-ready claim policy | `docs/roadmap-v40.md` |
| v4.5.0 | 已完成：Release Evidence Pack：clean-checkout snapshot、packaged resources、claim-promotion visibility | `docs/roadmap-v40.md` |
| v4.6-v5.0 | 已完成：Evidence Hardening Track：cost/token、Storage v2 scale、Index Fabric runtime、Rust native、default-change gate | `docs/roadmap-v40.md` |
| v5.0.0 | 当前版本：Evidence Hardening Track：artifact-backed cost/token、Storage v2 scale、Index Fabric runtime、Rust native、default-change gate | `docs/roadmap-v40.md` |

## 短结论

从 v1.5 baseline 到 v5.0.0 Evidence Hardening Track，主实现路线已经按一个版本一个文档重切并连续收口。
v1.5 baseline、v1.6 persistent vectors / bucket budget、v1.7 temporal truth、
v1.8 procedural skill、v2.0 heuristic distill 移除、v2.1 maintenance-only CLI、
v2.2 用户入口闭环（Slash/Skill/自然语言 + Agent 背后 MCP；跨客户端能力已交付，细节见维护者测试包）、
v2.3 signals/replay、v2.4 reflection queue、v2.5 context assembly、v2.6
wiki/contradiction、v2.7 cross-project skill、v2.8 session-distill maintenance，
以及 v2.9 的 PRD sync / maintenance / triage / truth-sync release train、
v3.1 的默认关闭 Auto Dream / DreamRun 账本 / handle-all / undo 面、v3.2 的
source map / atomic claim / citation validation / incremental metrics、v3.3 的
current/history/as_of temporal query / supersede timeline / abstention、v3.4.x 的
MCP surface cost observer / high-output detection / `surface_cost_report` / runtime health /
benchmark matrix / version drift / cost budget policy、v3.5 的 benchmark evidence /
public claim gate、v3.6 的 generated claim hardening、v3.7 的 skill evolution
governance、v3.8 的 true hybrid retrieval shootout contract、v4.0.0 的
storage-v2 baseline / migration roundtrip / local-index-fabric smoke contract、
v4.0.1-v4.0.5 的 canonical store / Rust facade / index fabric / lifecycle /
distribution gate、v4.1.0 的 context sufficiency / task-aware wake、v4.2.x 的
memory eval matrix / retrieval quality pack、v4.3.0 的 code-memory federation、
v4.4 的 claim-promotion gate、v4.5.0 的 release-evidence pack，以及 v5.0.0 的
Evidence Hardening Track 都已落地。

受控自动化已做；默认常驻后台不做。confirmed truth 可以自动维护，但不能静默覆盖；
必须走 candidate / review / supersede / ledger。cross-project skill 可以跨项目复用，
但不能默认污染 wake；必须显式搜索、提示、展开。

v3.1 Auto Dream Memory Maintenance 默认关闭、用户显式开启；在保留审计与撤销的前提下组合 signals / metabolism / reflection，并优先复用客户端/host 的定时触发能力，而不是引入独立后台进程。

v3.8 已收口 benchmark evidence、generated claim hardening、skill evolution governance
和 true hybrid retrieval shootout contract。后续规划不补默认 daemon，也不放松 truth /
skill 边界；未 ready 的 token/cost saving 不能写成已证明的公开节省事实，已 ready 的
true-hybrid latency / retrieval recall 也必须限定在本地 synthetic / smoke artifact。

v4.0.x 已把 Storage v2、canonical SQLite、Rust facade、Local Memory Index Fabric、
SearchBackend contract、lifecycle tiering 和 distribution diagnostics 做成可测试地基；
v4.1.0 在这个地基上加入 context sufficiency 与 task-aware wake；v4.2.x 把 memory eval
matrix 与 retrieval quality pack 产品化；v4.3.0 加入 code-memory federation；v4.4
把 public-claim promotion 机器化；v4.5.0 把 release evidence 打包成 clean-checkout
可消费的 snapshot/resource gate；v5.0.0 再把 cost/token、Storage v2 scale、
Index Fabric runtime、Rust native hot path 和 default-change decision gate
收口成 artifact-backed release truth。默认
truth governance 不变：confirmed truth 仍必须走 candidate / review / supersede / ledger；
v4/v5 smoke/contract artifacts 仍只证明 contract / surface availability 与门槛形状，
不证明公开性能收益、默认 reranker/HyDE 启用、code-intel token/runtime 或端到端回答质量。

## 维护者材料（非用户文档）

| 材料 | 用途 |
|---|---|
| `docs/v2-user-test-packet.md` | 跨客户端 release 测试包（仅完整 clone；公开源码归档已排除，见 `docs/releasing.md`） |
| `docs/roadmap-v29.md` 及 `openspec/changes/archive/` | 切片级验收与历史决策链 |

请勿将上述文件中的场景编号、客户端日志或本机路径摘进对外 README。
