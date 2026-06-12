# 参考项目深读：记忆运行时、知识库与自进化

> **Maintainer-only — not user-facing.** 含可选本地 upstream 镜像路径；公开 clone 不必配置这些目录。

> 状态：持续维护的参考地图。
>
> 初次收录：2026-05-18。中文化与本地深读修订：2026-05-19。
>
> 本文记录对 `harness-mem` 设计有参考价值的外部项目。它不是路线图本身；当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。若需回看当时的历史路线设计，再参考 `roadmap-v15x.md`、`roadmap-v16x.md`、`roadmap-v17x.md` 与 `roadmap-vision-v16-v18.md`。

## 证据化当前评估与参考锚点

> 说明：本节是 maintainer decision artifact，不是公开 benchmark，也不是路线图承诺。
> 它只回答四件事：`harness-mem` 当前版本已经做到哪里、证据来自哪里、参考项目在哪些
> 维度仍然更强、哪些说法不能对外发布。当前版本状态仍以
> [`roadmap-status.md`](./roadmap-status.md)、`CHANGELOG.md` 和
> `benchmark-suite/release-snapshot.json` 为准。
>
> 本文不再维护跨项目总分榜。参考项目只作为能力锚点：用来说明该借什么、不该借什么，
> 不把不同目标、不同数据集、不同产品边界的项目硬拼成一个排行榜。

### 评分规则

下表中的分数是内部 release triage 分，不是 public benchmark。它必须同时看产品面、
测试/文档、artifact 和负面边界；对外 claim 只能跟随
`benchmark_matrix_report()["claim_readiness"]`。

| 分段 | 判定 |
|---:|---|
| 0-3 | 只有概念、路线图或零散脚本，不能当当前能力。 |
| 4-6 | 有实现或测试，但入口、证据、边界或可复现性不足。 |
| 7-8 | 已发布产品面，测试/文档能锁定行为，并有 bounded artifact 或明确的安全边界。 |
| 8-9 | 多入口闭环稳定，release snapshot / benchmark gate 能支撑受限 claim，失败模式可诊断。 |
| 9+ | 需要跨语料、跨环境或生产级长期证据；当前 `harness-mem` 不把任何维度宣传到这一级。 |

### 当前版本结论

`harness-mem` v4.1.0 已经不是单纯的 session memory MVP。它的当前形态是一个
local-first、candidate-first、MCP/Skill/Slash 驱动的记忆运行时：默认用户入口是
`/hm:*` 或自然语言，Agent 背后走 MCP；confirmed truth 通过候选、复核、supersede
和 ledger 保持可审计；generated knowledge、temporal read model、Auto Dream、skill
governance、benchmark matrix、Storage v2 canonical store / Rust facade / index
fabric / lifecycle / distribution diagnostics，以及 context sufficiency /
task-aware wake 都已形成产品面。

当前强项集中在 evidence safety、truth/review 边界、generated boundary、temporal
query、runtime health 和参考项目吸收纪律。当前短板也很清楚：token/cost saving
没有 ready，性能和 retrieval recall 仍是 local synthetic / smoke artifact，Auto
maintenance 没有生产长期 false-positive 证据，Storage v2 还没有 10k / 100k /
1M release artifact 或 native Rust wheel speedup evidence，context sufficiency
也还不是端到端回答正确率 benchmark；`harness-mem` 仍不是 `codedb-mcp`
那种专门 code-intel 性能系统。

### v4.1.0 证据分析

| 能力维度 | 证据分 | 当前状态 | 主要证据 | 仍不能说什么 |
|---|---:|---|---|---|
| Memory runtime / wake / search | 8.6 | Slash/Skill/自然语言是用户入口，MCP 是 Agent 背后传输层；wake 分层渲染，search/timeline/drilldown 走渐进式取证；v4.1 wake/search 返回 task-aware context plan 和 sufficiency metadata。 | `roadmap-status.md` 的已交付能力；MCP smoke 覆盖 `wake` / `search_memory` / `timeline`；v2.5 context assembly 与 v4.1 context sufficiency 已收口。 | 不能说它已经替代 code-intel、full KG 或所有外部知识检索。 |
| Evidence safety / provenance | 8.8 | candidate-first、source ids、raw observation、verbatim exact evidence、generated 不冒充 truth 已成为核心边界。 | BENCH-002：5/5 accepted，30 条 evidence items，含 insufficient-evidence abstention；v1.7 exact evidence search。 | 不能把 guarded task set 说成所有 Agent 回答都不会过度声称。 |
| Truth 安全 / review 边界 | 8.7 | 自动维护可以提出和处理低风险项，但 confirmed truth 不被静默覆盖；supersede 保留历史和来源。 | BENCH-006：6/6 accepted，19 个 maintenance actions，6 个 truth-mutation checks；Dream/skill/supersede 都有 ledger。 | 不能宣称 AI 可以自治删除或直接改 accepted memory。 |
| Generated knowledge | 8.5 | v3.2/v3.6 形成 source map、atomic claim、citation/hash validation、claim diff、freshness 和 generated review queue。 | BENCH-005：5/5 accepted，23 个 generated claims inspected，source-map incomplete 和 citation laundering 都被识别。 | 不能说 generated prose 有完美 source-map 覆盖，也不能把 wiki/compact output 当 truth。 |
| Temporal query | 8.4 | `temporal_query` 支持 current/history/as_of、valid/recorded time、supersede chain、timeline、explanation 和 abstention。 | BENCH-003：5/5 accepted，覆盖 current/history/as_of、ambiguous scope 和 missing evidence；v3.3.0 已发布。 | 不能说这是完整图数据库、自动 ontology 或 LongMemEval temporal 总分。 |
| Auto maintenance / Dream | 8.0 | Auto Dream 默认关闭，显式 opt-in；DreamRun/DreamItem 记录 apply/reject/archive/failed、undo 和处理摘要。 | v3.1.0 已发布；BENCH-006 覆盖 merge、stale、supersede、reject、undo、ledger。 | 不能宣称默认 daemon、unattended optimize loop 或生产长期 precision/recall。 |
| Observability / health | 8.4 | `health_summary`、`get_project_status`、doctor/status、version drift、false-success accounting 和 runtime health 已成体系。 | BENCH-007：6/6 accepted，false_success_count total 2；v3.4.1-v3.4.4 已发布。 | 不能说有云端 telemetry、真实 billing 监控或自动调参。 |
| Cost discipline | 7.4 | 已有 surface cost observer、token estimate、high-output、budget policy、drilldown 建议和报告面。 | `surface_cost_report`、cost budget policy、BENCH-007；release snapshot 显示 `token_cost_saving.ready=false`，且 token-visible paired run 是负向 saving delta。 | 不能宣传 token/cost saving；这比旧的“预算面已做”更严格。 |
| Performance / retrieval quality | 7.7 | Synthetic warm-path FTS/wake latency可测；v3.8 true-hybrid shootout 有 FTS/vector/hybrid contract、fallback accounting 和 local smoke recall。 | BENCH-004：FTS p95 9.901ms、wake p95 9.86ms；true-hybrid probe p95 286.799ms no fallback；BENCH-008 local smoke source-hit recall R@5=1.0。 | 不能外推生产延迟、广语料质量或端到端回答正确率。 |
| Storage v2 / canonical runtime foundation | 7.6 | v4.0.x 建立 deterministic corpus、side-by-side migration、canonical entity store、Rust facade/fallback、index fabric/SearchBackend contract、lifecycle tiering 和 distribution diagnostics。 | `maintenance migrate-store-v2` / `maintenance export-json-snapshot`；v4.0.0 三条 Storage v2 diagnostic smoke；`canonical_store_runtime_baseline` 2026-06-12 smoke；相关 Python contract tests。 | 不能说默认 canonical store 已启用、native Rust wheel speedup 已证明、Storage v2 10k/100k/1M 性能收益已证明。 |
| Context sufficiency / task-aware wake | 7.5 | v4.1.0 给 search/wake 增加 deterministic sufficiency report、retrieval plan、context plan、iterative trace 和 wake packet budgeter。 | `context_sufficiency_gate` 2026-06-12 smoke；`tests/test_context_sufficiency.py`；`tests/mcp/test_context_sufficiency_surfaces.py`。 | 不能把 deterministic sufficiency smoke 说成端到端回答正确率、LLM judge 精度或 broad corpus quality。 |
| 用户负担与入口闭环 | 8.3 | 日常入口收敛到 `/hm:*`、Skill、自然语言；CLI 退到安装、doctor、purge、maintenance；autopilot 可在清晰任务边界辅助学习。 | `roadmap-status.md` 用户入口与已交付能力；v2.8/v2.9 维护面和 status/doctor 收口。 | 不能默认启用 IDE 随手记、per-turn 无条件写入或 silent learning。 |

### 参考项目锚点，不做排行榜

| 维度 | 主要参考 | 参考项目强在什么 | `harness-mem` 当前位置 |
|---|---|---|---|
| Progressive disclosure / queue health | `claude-mem` | hook lifecycle、worker sidecar、CLAIM-CONFIRM queue、File Read Gate、生产 health 指标。 | 已吸收 search/timeline/drilldown 和 failure-visible 思路；不默认引入 Claude-only worker 或阻断式 file gate。 |
| Raw/verbatim + memory stack | `mempalace`、`ai-harness` | raw drawer / closet、source docs -> cache -> palace、manual/generated 分层。 | 已坚持 raw/provenance 和 generated cache 分层；不照搬 palace 术语或把运行产物当 truth。 |
| Code-intel performance / generated layer | `codedb-mcp` | project-local `.codedb-mcp/`、DeepWiki source citations、module atlas、token/runtime benchmark。 | 是 P0 性能与 generated-layer 纪律参考；`harness-mem` 当前不宣称达到 code-intel token/runtime 水平。 |
| Generated claim safety | `llm_wiki`、`meta-kb`、`codedb-mcp` | two-step ingest、claims-first、citation verification、incremental compile、review queue。 | v3.2/v3.6 已吸收到 source map / atomic claims / freshness；不把 generated prose 反写 truth。 |
| Temporal / graph memory | `Graphiti / Zep`、`hypatia`、`mempalace`、`hindsight` | temporal KG、statement triples、parallel keyword/semantic/graph/time retrieval。 | v3.3 只做 bounded read-side temporal query；不引入完整图数据库或自动 ontology。 |
| Auto maintenance / skill evolution | `evo`、`OpenSpace`、`Memento-Skills` | runtime ledger、host adapter、quality monitoring、skill lineage、Read -> Execute -> Reflect -> Write。 | v3.1/v3.7 吸收账本、health、候选治理和显式 activation；不做默认自治 skill rewrite。 |
| Memory OS / broader platform | `Letta`、`EverOS`、`hindsight` | agent memory API、user/agent scopes、多模态和平台化入口。 | 作为产品边界参考；当前主线仍是 local-first runtime，不转 cloud-first/dashboard-first。 |
| Compact / Chinese compression | `MemChinesePalace`、`mempalace` AAAK | 文简/简牍、palace hierarchy、有损 compact renderer。 | 只作为 compact wake renderer 实验，不进入 canonical storage。 |

### 快照更新规则

- 新版本只在完成可使用的产品面、测试真值或 benchmark artifact 后调分。
- 每次调分必须写一句原因，并引用状态页、CHANGELOG、测试或 BENCH artifact。
- Cost discipline 和 Performance 分开评估；前者看预算、浪费、token/cost 证据，后者看延迟、索引、缓存、fallback 和 retrieval quality。
- 证据变差时要降分。例如 token-visible paired run 出现负向 saving delta 后，Cost discipline 的收益证明不能沿用机制成熟度高分。
- Public claim 不跟随内部分数；只能跟随 `benchmark_matrix_report()["claim_readiness"]`。

### 硬指标 Claim Gate

内部评分不能替代 artifact。当前 v4.1 benchmark matrix 的真实发布门槛是：

| Claim | Matrix field | Current value | 对外口径 |
|---|---|---:|---|
| Benchmark artifact gate | `gate.passed` | `true` | 可以说当前 accepted BENCH artifact 内部通过，但 v4 smoke 仍是 contract/surface evidence |
| Token/cost saving | `claim_readiness.token_cost_saving.ready` | `false` | 不能说 token/cost saving 已被证明；token-visible paired run 的 saving delta 为负 |
| True vector-hybrid latency | `claim_readiness.true_vector_hybrid_latency.ready` | `true` | 只能说本地 synthetic true-hybrid probe 无 fallback；不能外推生产延迟 |
| Retrieval recall | `claim_readiness.retrieval_recall.ready` | `true` | 只能说本地 smoke source-hit recall；不能外推端到端回答正确率或 broad corpus quality |

因此 `codedb-mcp` 在 cost/performance 上仍是更强的 code-intel 参考；`harness-mem`
当前只能讲本地 cost discipline surface、预算/截断可观测、synthetic warm-path FTS/wake
latency、local true-hybrid probe 和 local smoke source-hit recall，不能把这些说成
code-intel 级 token/runtime benchmark。

### `codedb-mcp` cost / performance benchmark anchor

`codedb-mcp` 不只是 generated knowledge 参考，也是 cost discipline 和 performance 的 P0 参考。
它的 README benchmark snapshot 记录了同一 `u3dclient` 仓库、同类中文 feature-analysis prompt 下，
启用/禁用 `codedb-mcp` 的 Codex self-reported token 和 runtime 对比：

| 指标 | `codedb-mcp enabled` | `codedb-mcp disabled` | 效果 |
|---|---:|---:|---:|
| Total feature-analysis runs | 335,940 tokens / 920.9s | 590,834 tokens / 1,482.9s | 省 254,894 tokens；token 降 43.1%；runtime 快 37.9% |
| World-map marching logic | 92,639 tokens / 272.5s | 231,810 tokens / 617.8s | token 降 60.0%；runtime 快 55.9% |
| Hero attributes and power calculation | 114,436 tokens / 348.0s | 173,576 tokens / 379.9s | token 降 34.1%；runtime 快 8.4% |
| Alliance rally and join-rally logic | 128,865 tokens / 300.4s | 185,448 tokens / 485.2s | token 降 30.5%；runtime 快 38.1% |

本地 observer 样例 `../../upstreams/codedb-mcp/.codedb-mcp/observe-u3d-12h.json` 还显示，
`codex-observe.mjs` 能从 `~/.codex/sessions` 统计 model token、tool-output token、codedb calls、
bundle child breakdown、高输出调用、broad reads/searches、非 codedb source lookup，以及 missed
`codedb_bundle` / `codedb_context` opportunities。这个形态直接支撑 `harness-mem` v3.4 把
**Cost discipline** 单列为一级能力。

边界：这组 benchmark 证明的是 `codedb-mcp` 作为 code-intel substrate 的 token/runtime
优势，不能外推成 `harness-mem` 的 memory-runtime 硬分。`harness-mem` 对外讲 token/cost
节省前，必须使用自己的 `client_enabled_vs_disabled` artifact，并且两侧都有可见
`token_usage` 来源以及正向 saving delta。当前 release snapshot 里的 v3.8
token-visible paired run 已经有
可见 token 来源，但 `claim_readiness.token_cost_saving.ready=false`，因为结果是负向
saving delta。对外讲 true vector-hybrid latency 时，
`benchmark_matrix_report()` 的 `claim_readiness.true_vector_hybrid_latency.ready`
必须为 `true`，且文案必须保留 local synthetic fixture 边界。

### 吸收优先级

| 已落地线 | P0 参考 | 已吸收 | 不吸收 |
|---|---|---|---|
| v3.1 Auto Dream | `claude-mem` + `evo` + `OpenSpace` + `Memento-Skills` | queue/job health、显式 DreamRun 账本、apply/reject/undo、host/scheduler 触发、skill/dream 健康信号 | always-on daemon、自治 truth mutation、默认 subagent orchestration、skill 自改后直接替换 confirmed truth |
| v3.2 / v3.6 Generated Knowledge Compiler | `codedb-mcp` + `llm_wiki` + `meta-kb` + `ai-harness` | project-local generated layer、source map、atomic claims、citation validation、incremental cache、freshness/status、Trust/Drilldown 可见性 | 把 DeepWiki/wiki prose 或 generated cache 当 truth |
| v3.3 Temporal Query | `Graphiti` + `hypatia` + `mempalace` + `hindsight` | current/history/as_of、valid/recorded time、supersede timeline、temporal query traces、abstention metadata | 完整图数据库、自动 ontology、AI 直接改 confirmed truth |
| v3.4 / v3.5 Runtime Health / Cost / Benchmark Evidence | `codedb-mcp` + `claude-mem` + `evo` + `EverOS` + `OpenSpace` | cost observer、per-surface budget、runtime health、version drift、benchmark dimensions、false-success accounting、public-claim gates | 云端 telemetry、dashboard-first、observer 自治调参、未过 gate 的 token saving claim |
| v3.7 Skill Evolution Governance | `OpenSpace` + `Memento-Skills` + `evo` + `claude-mem` | skill outcome ledger、revision/deprecation/promotion candidates、低成功率 health、显式 shared activation | skill 自改 confirmed body、shared skill 默认污染 wake |
| v3.8 True Hybrid Retrieval Shootout | `hypatia` + `mempalace` + `codedb-mcp` | FTS/vector/hybrid source-hit contract、latency/fallback/token-cost fields、embedding candidate governance | 用 retrieval recall 冒充端到端 answer correctness，或因单次 shootout 静默替换默认 embedding |
| v4.0.x Storage / Index / Rust Foundation | `codedb-mcp` + `mempalace` | deterministic corpus、migration checksum、canonical store、Rust facade/fallback、manifest-last sidecar discipline、SearchBackend contract、rollback/export evidence | 默认切 canonical store、宣传 native Rust / Storage v2 speedup、把 smoke 当 production performance |
| v4.1 Context Sufficiency | `Graphiti / Zep` + `codedb-mcp` + `hindsight` | deterministic sufficiency report、retrieval plan、context plan、iterative trace、wake packet budgeter | 用 sufficiency smoke 冒充端到端 answer correctness 或 LLM judge benchmark |

## 文档定位

我们之前已经在 [`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 里写过“当前生态坐标（参考与对标）”，但那一节偏 v1.6 到 v1.8 的远景定位。

本文的职责不同：它是参考项目的一手读书笔记。若你在 **memory-lab 工作区** 下拉了 sibling 目录 `upstreams/`，下文路径相对于本仓库为 `../../upstreams/`；否则只把 GitHub 链接当远程线索，不必配置本地镜像。

## 本地 upstream 总览（可选）

`../../upstreams/`（与 `harness-mem` 同级的 `memory-lab/upstreams`）是维护者用的外部参考书架，只用于对照、阅读和 benchmark，不是主产品源码。

| 本地路径（相对 harness-mem） | 上游仓库 | 本文定位 |
|---|---|---|
| `../../upstreams/ai-harness` | `https://github.com/killop/ai-harness.git` | MemPalace workspace 样板：源文档 → knowledge cache → palace。 |
| `../../upstreams/claude-mem` | `https://github.com/thedotmack/claude-mem.git` | Claude Code 插件式记忆：hook、progressive disclosure、降级策略。 |
| `../../upstreams/mempalace` | `https://github.com/MemPalace/mempalace.git` | local-first memory runtime：raw/verbatim、memory stack、temporal KG。 |
| `../../upstreams/codedb-mcp` | `https://github.com/killop/codedb-mcp.git` | 代码知识编译器：project-local generated layer、DeepWiki、module atlas、tool-cost observer。 |
| `../../upstreams/evo` | `https://github.com/evo-hq/evo.git` | 自动实验编排 runtime：`.evo/` 账本、host adapter、frontier strategy、长任务 directive。 |
| `../../upstreams/OpenSpace` | `https://github.com/HKUDS/OpenSpace.git` | skill self-evolution：FIX / DERIVED / CAPTURED、quality monitoring、skill lineage、GDPVal token/economic benchmark。 |
| `../../upstreams/Memento-Skills` | `https://github.com/Memento-Teams/Memento-Skills.git` | deployment-time skill learning：Read -> Execute -> Reflect -> Write、skill market、agent profile、dream daemon。 |
| `../../upstreams/llm_wiki` | `https://github.com/nashsu/llm_wiki.git` | generated wiki app：two-step ingest、source traceability、incremental cache、knowledge graph、review queue。 |
| `../../upstreams/meta-kb` | `https://github.com/chappyasel/meta-kb.git` | self-improving knowledge compiler：raw sources -> claims/articles、citation verification、incremental compile、self-eval。 |
| `../../upstreams/hypatia` | `https://github.com/MarchLiu/hypatia.git` | SQLite/DuckDB graph memory：Knowledge/Statement triples、JSE query、FTS/vector, LoCoMo/LongMemEval benchmark artifacts。 |
| `../../upstreams/EverOS` | `https://github.com/EverMind-AI/EverOS.git` | local memory OS：Markdown + SQLite + LanceDB、user/agent scopes、multimodal ingestion、EverMem benchmark ecosystem。 |
| `../../upstreams/hindsight` | `https://github.com/vectorize-io/hindsight.git` | retain/recall/reflect memory API：world/experience/mental-model pathways、parallel retrieval strategies、enterprise/cloud boundary reference。 |
| `../../upstreams/MemChinesePalace` | `https://github.com/Chandler-Sun/MemChinesePalace.git` | Chinese compression experiment：文简/简牍、palace hierarchy、KG contradiction, compact renderer research only。 |

## 已下载项目深读

### 1. `ai-harness`

已读本地文件：

- `../../upstreams/ai-harness\README.md`
- `../../upstreams/ai-harness\harness-workspace\README.md`
- `../../upstreams/ai-harness\harness-workspace\knowledges-cache\README.md`
- `../../upstreams/ai-harness\harness-workspace\tools\sync-map.json`
- `../../upstreams/ai-harness\harness-workspace\tools\Sync-MemoryCache.ps1`
- `../../upstreams/ai-harness\harness-workspace\tools\Refresh-MemPalace.ps1`
- `../../upstreams/ai-harness\harness-workspace\tools\Rebuild-MemPalace.ps1`
- `../../upstreams/ai-harness\.codex\config.toml`

它不是一个普通竞品仓库，更像一个“MemPalace 知识库工作区样板”。核心数据流是：

```text
source docs
-> tools/Sync-MemoryCache.ps1
-> knowledges-cache/
-> tools/Refresh-MemPalace.ps1
-> .mempalace_local/palace
```

关键机制：

- `knowledges-cache/` 是共享知识源，按 wing 分成 `game_design`、`game_server`、`game_client`、`game_shared`。
- 每个 wing 用 `mempalace.yaml` 定义可挖掘输入。
- `manual/` 放人工长期维护知识，`generated/` 放同步脚本生成内容。
- `sync-map.json` 把上游源目录映射到 knowledge cache，例如 `DesignDoc -> game_design/generated/DesignDoc`、`docs/architecture -> game_shared/generated/docs-architecture`。
- `Refresh-MemPalace.ps1` 先同步 cache，再对每个带 `mempalace.yaml` 的 wing 执行 `python -m mempalace.cli --palace ... mine ...`。
- `.mempalace_local/palace` 是运行产物，不是共享源。

对 `harness-mem` 的启发与已吸收形态：

- v3.2 Generated Knowledge Compiler 已吸收 source cache / generated cache 分层，generated output 不直接写入 runtime truth。
- “人工维护内容”和“脚本生成内容”必须分目录，避免 AI 把生成物当成权威源。
- 当前已落地的知识编译链路遵循这个工作流：

```text
repo docs / accepted memory
-> generated knowledge cache
-> wiki compiler 或 memory mine
-> 可检索知识输出
```

不能照搬：

- 不能把 `.mempalace_local/` 这类运行产物当成协作源。
- 不能把游戏项目的 wing 命名直接套到通用 memory runtime。
- 不能让 `sync-map.json` 成为隐藏真相；映射规则需要在 `doctor` 或文档索引里可见。

### 2. `claude-mem`

已读本地文件：

- `../../upstreams/claude-mem\docs\architecture-overview.md`
- `../../upstreams/claude-mem\docs\public\architecture\overview.mdx`
- `../../upstreams/claude-mem\docs\public\architecture\search-architecture.mdx`
- `../../upstreams/claude-mem\docs\public\context-engineering.mdx`
- `../../upstreams/claude-mem\docs\public\progressive-disclosure.mdx`
- `../../upstreams/claude-mem\docs\public\file-read-gate.mdx`
- `../../upstreams/claude-mem\docs\public\hooks-architecture.mdx`
- `../../upstreams/claude-mem\docs\production-guide.md`

它的核心不是单纯“有 SQLite + ChromaDB”，而是一个 hook 驱动的 Claude Code 外挂记忆系统：

```text
Claude Code hooks
-> CLI / hook command layer
-> Worker service
-> SQLite + FTS5 + ChromaDB
-> MCP/search skill/progressive disclosure
```

关键机制：

- **Hook lifecycle**：SessionStart 注入上下文，UserPromptSubmit 初始化 session，PostToolUse 捕捉工具使用，Stop 生成 summary，SessionEnd 做收尾。
- **Worker sidecar**：后台 Express worker 负责 observation 处理、search API、SSE/UI、SDK agent 调用。
- **CLAIM-CONFIRM queue**：pending -> processing -> confirm/delete；processing 超时后重置 pending，失败项可 retry，避免 hook 进程和 worker 崩溃造成丢消息。
- **Graceful degradation**：worker 不可用时不阻塞 Claude Code 主会话；传输错误 exit 0，客户端 bug 才 exit 2。
- **Progressive disclosure**：先给 observation index，再通过 timeline 和 get_observations 拉细节，避免一上来塞完整历史。
- **3-layer retrieval**：`search(query)` 先拿 ID 索引，`timeline(anchor=ID)` 看上下文，`get_observations([IDs])` 只取筛过的全文。
- **File Read Gate**：拦截大文件 `Read`，如果数据库里已有该文件相关 observations，先展示 timeline 和成本提示，让 agent 决定是否读详情、读 outline，或最后再读全文。
- **Production health**：文档里明确监控 pending_messages、failed queue、active sessions、WAL size、Chroma size、errors/day。

对 `harness-mem` 的启发：

- 我们已经有 `search -> timeline -> get_observations` 的类似工作流，应该继续把它写成强约束，而不是让 agent 直接拉全文。
- `wake` 不应该只追求“多给记忆”，而应该像 progressive disclosure 一样暴露“有什么、成本多少、怎么取详情”。
- 如果将来做文件级记忆辅助，可以参考 File Read Gate 的思想，但在 Codex 侧应更保守：先作为显式建议或工具，不直接拦截用户文件读取。
- `wake-up` 的 auto-ingest / distill 任务如果变重，可以借鉴 CLAIM-CONFIRM queue 和 health 指标，避免 silent stuck。
- “主会话不被记忆系统拖死”是硬边界：memory runtime 失败应可见、可诊断，但不能破坏用户当前开发流。

不能照搬：

- `claude-mem` 是 Claude Code 深绑定 hook 插件；`harness-mem` 的主线是跨 Agent 的本地 memory runtime，MCP 只是隐藏传输层，不能变成只服务 Claude Code 的 hook daemon。
- 不应默认引入常驻 worker/daemon。当前 `harness-mem` 路线已经明确先做本地 runtime 和 MCP 自动化，不把 daemon 当主路线。
- File Read Gate 不应直接变成默认阻断行为；这类能力要先有用户可理解的 escape hatch 和 stale 判断。

### 3. `mempalace`

已读本地文件：

- `../../upstreams/mempalace\README.md`
- `../../upstreams/mempalace\benchmarks\BENCHMARKS.md`
- `../../upstreams/mempalace\benchmarks\README.md`
- `../../upstreams/mempalace\docs\CLOSETS.md`
- `../../upstreams/mempalace\docs\schema.sql`
- `../../upstreams/mempalace\website\concepts\memory-stack.md`
- `../../upstreams/mempalace\website\concepts\the-palace.md`
- `../../upstreams/mempalace\website\concepts\knowledge-graph.md`
- `../../upstreams/mempalace\website\concepts\contradiction-detection.md`
- `../../upstreams/mempalace\website\concepts\agents.md`
- `../../upstreams/mempalace\website\concepts\aaak-dialect.md`
- `../../upstreams/mempalace\mempalace\dialect.py`

它最重要的产品判断是：默认存 raw/verbatim，不先让 LLM 提取后丢原文。MemPalace 自己的 benchmark 文档也把“raw verbatim + semantic search”视为核心发现，而 AAAK 只是实验压缩层。

关键机制：

- **Drawers**：原始内容 chunk，verbatim，是当前搜索和 benchmark 的主路径。
- **Closets**：可搜索索引层，包含 topic/entities/quote，并指回 drawer ID。搜索先命中 closet，再打开 drawer；没有 closet 时 fallback 到 drawer search。
- **Palace hierarchy**：wing 是人/项目，room 是主题，hall 是概念类别，tunnel 是跨 wing 的共享 room 连接。
- **Memory Stack**：L0 identity 常驻，L1 essential story 常驻，L2 room recall 按 topic 加载，L3 deep search 显式查询。
- **Temporal knowledge graph**：SQLite 中的 `entities`、`triples`、`attributes`，triple 带 `valid_from / valid_to / confidence / source_closet / source_file`。
- **Contradiction detection**：文档明确标为 experimental/planned，当前只有 temporal KG primitives，不是完整 MCP/CLI 闭环。
- **Agent diary**：通过稳定 agent name 写入各自 wing 的 diary room，用 AAAK 压缩 diary entry，但当前不宣称完整 agent registry。
- **AAAK**：有损结构化摘要方言，提取 entities/topics/key quotes/emotions/flags，不可还原原文，也不是默认存储。文档中 AAAK mode 的 LongMemEval R@5 低于 raw mode。

对 `harness-mem` 的启发：

- 默认 truth 仍应保留原始 observation 和 provenance，不应让压缩摘要替代原文。
- `wake` 可以借鉴 Memory Stack：常驻层只放 profile / essential rules / recent handoff，topic-specific recall 通过 search 或 wiki bridge 按需加载。
- `closet -> drawer` 很适合映射到我们未来的 `wiki bridge` 或 compact search：先返回短索引和 provenance，再按需打开 source observation。
- temporal KG 的 `valid_from / valid_to` 与本仓 v1.7 方向一致；它证明 SQLite 足够表达最小 bi-temporal 子集，不必一上来引入图数据库。
- contradiction detection 只能作为候选生成器参考，不应直接变成 AI 自动改 truth。
- AAAK 可以作为 wake context renderer 研究，不适合作为 canonical storage。

不能照搬：

- ChromaDB 默认后端不符合 `harness-mem` 当前 SQLite FTS5 + sqlite-vec 路线。
- Palace 的建筑隐喻很强，但本仓面向多 agent client 的 runtime，不应该强迫所有用户接受 wing/room/hall 术语。
- AAAK 对 token budget 有启发，但有损压缩会损害审计性；只能输出短摘要并保留 source ID。
- MemPalace 的 benchmark headline 只能作为复现实验线索，不能直接写进 `harness-mem` README 当比较结论。

### 4. `codedb-mcp`

已读本地文件：

- `../../upstreams/codedb-mcp\README.md`
- `../../upstreams/codedb-mcp\setup-for-agent.md`
- `../../upstreams/codedb-mcp\skills\deepwiki\SKILL.md`
- `../../upstreams/codedb-mcp\skills\deepwiki\references\deepwiki-workflow.md`
- `../../upstreams/codedb-mcp\src\config.rs`
- `../../upstreams/codedb-mcp\src\mcp.rs`
- `../../upstreams/codedb-mcp\src\tools.rs`

它不是 memory runtime，而是“代码知识编译器 / 本地代码情报 MCP”：把一个 repo 编译成 project-local 的代码索引、模块图、DeepWiki 和可观测工具面。核心落点是目标 repo 的 `.codedb-mcp/`，而不是全局 memory truth。

关键机制：

- **Project-local generated layer**：配置、索引、vector、日志、DeepWiki、module atlas 数据都落在 `.codedb-mcp/`，删除目录即可清理该项目派生物。
- **Setup / usage / registration 分层**：`setup-for-agent.md` 明确 setup 负责安装、配置和注册准备；skill 负责已配置后的使用，不把安装面混进日常使用面。
- **DeepWiki 作为派生解释层**：`deepwiki` skill 使用 `codedb_*` MCP 证据和当前 agent reasoning 生成 `.codedb-mcp/deepwiki`，页面带 repo-relative file/line citations。
- **中间结构层先于 prose**：`codedb_module_map` / `codedb_module_atlas` 先给依赖连通、label propagation、entry points、key symbols、semantic neighbors，再由 agent 写 wiki 页面。
- **工程化 MCP 工具体系**：search、text_search、symbol/read、callers、deps、context、explore、query、bundle、graph、communities、module_map、module_atlas、status 等组成 code intelligence substrate。
- **Tool-cost observer**：`skills/codedb-mcp/scripts/codex-observe.mjs` 扫 `~/.codex/sessions`，估算 codedb tool output tokens，标记高输出调用和未使用 bundle/context 的机会。
- **Generated-layer 可见性**：`codedb_status` 展示 indexed files、graph、vector、embedding model、scan、cache、storage，便于 doctor/freshness 类诊断。

对 `harness-mem` 的启发：

- `wiki bridge / knowledge cache` 应借它的 project-local generated layer 纪律：派生产物显式落点、可删除、可诊断，不混入全局 truth。
- 安装、注册、使用、维护应该继续拆开；不要把 MCP 注册、plugin 安装、日常 `/hm:*` 使用写成同一条用户心智路径。
- 更强的 repo knowledge 编译不应直接从 observation 写 prose；应先生成 claim/module/source-map 这类中间结构层，再输出 wiki 或 compact page。
- `wake/search/distill/file_context` 可以借 tool-cost observer：统计输出 token、宽泛检索、missed bundle/context opportunities，用于找浪费上下文的 MCP surface。
- `doctor/status/freshness` 应覆盖 generated cache：索引是否新鲜、source map 是否可解释、cache 是否需要重建。

不能照搬：

- 不能把 `.codedb-mcp/` 这类 generated dir 变成 `harness-mem` 的 truth store。
- 不能把 DeepWiki prose 当 memory truth；它混合 MCP evidence 和 agent reasoning，只能是派生解释层。
- 不能把“代码仓库知识编译器”的目标误当成“跨 session 记忆系统”；它和 `harness-mem` 是互补 substrate，不是替代关系。

### 5. `evo`

已读本地文件：

- `../../upstreams/evo\README.md`
- `../../upstreams/evo\plugins\evo\src\evo\core.py`
- `../../upstreams/evo\plugins\evo\src\evo\dispatch.py`
- `../../upstreams/evo\plugins\evo\src\evo\frontier_strategies.py`
- `../../upstreams/evo\plugins\evo\hooks\hooks.json`
- `../../upstreams/evo\plugins\evo\skills\optimize\SKILL.md`
- `../../upstreams/evo\plugins\evo\src\evo\host_install\__init__.py`
- `../../upstreams/evo\plugins\evo\src\evo\version_check.py`

它不是 memory 系统，也不是 code search，而是自动实验编排 runtime：在 repo 下建立 `.evo/` 工作区，维护 experiment graph / config / annotations / infra log，通过 host hooks、parallel subagents、worktree / remote backend、benchmark gate 和 dashboard 驱动优化循环。

关键机制：

- **显式运行时账本目录**：`.evo/` 下维护 `graph.json`、`config.json`、`annotations.json`、`infra_log.json`、`meta.json`、`project.md` 等运行状态。
- **Host adapter / capability matrix**：`SUPPORTED_HOSTS`、host installer adapters、hook 机制、dispatch host 支持面都显式建模。
- **Plugin 与 CLI 版本锁步**：host plugin、hooks、CLI 共享 wire format；install/update 成功后自动同步 CLI，避免版本漂移静默破坏协议。
- **Frontier strategy registry**：frontier 策略集中注册、参数校验，CLI/dashboard/picker 共用同一个策略真值。
- **Explore/read phase cache**：`dispatch.py` 缓存 explorer session；复用条件包含 host、parent commit、skill hash、explore context hash 等，不缓存最终实验结论。
- **Directive banner + ack**：`optimize` skill 规定 runtime 注入 `[EVO DIRECTIVE id=...]`，agent 需 `evo ack <event_id>`，适合长任务中途用户干预。
- **Runtime-first hooks**：Claude hooks 几乎全生命周期接 `evo-hook-drain`，说明它是重 runtime 编排系统，而不是单纯 CLI 或文档工具。

对 `harness-mem` 的启发与已吸收形态：

- v3.1 Auto Dream 已吸收显式 DreamRun / DreamItem 账本；它比隐式后台状态更可审计，且仍保持默认关闭。
- 跨 Claude / Codex / Cursor / Hermes 等 host 时，应有 host adapter 与 capability matrix，而不是在各入口里散落特判。
- v3.4 已吸收 plugin / skill / slash / MCP wire-format drift 诊断，避免安装面和运行面不一致。
- dream prioritization / directive ack / explore-phase cache 仍是后置增强，只能服务 opt-in maintenance，不能变成默认自治循环。

不能照搬：

- 不能把 `harness-mem` 变成 benchmark optimizer 或 autonomous experiment loop。
- 不能默认引入 `evo` 那种重 hooks / runtime 生命周期；`harness-mem` 的默认主线仍是显式 `/hm:*`、Skill、MCP behind the curtain。
- 不能把 memory maintenance 做成无审核自治实验循环；truth 变更仍走 candidate / review / supersede。
- 不能把 subagent orchestration 当成默认用户路径；它只适合重型离线分析或明确 opt-in 的 auto dream。

## 对 `harness-mem` 的直接设计结论

### 1. 已下载项目共同指向“索引先行，全文按需”

前三个 memory 参考项目都在不同层面支持同一个方向：

- `ai-harness`：先整理 source docs 到 knowledge cache，再 mine。
- `claude-mem`：先展示 observation index，再按 ID 拉详情。
- `mempalace`：先搜 closet，再打开 drawer。

所以 `harness-mem` 后续的正确形态不是“wake 时塞更多全文”，而是（v2.5.0/v2.5.1 已落地为分层 context assembly）：

```text
wake-up
-> 分层渲染 L0 项目 profile/identity · L1 essential truth(confirmed rules + accepted current truth) · L2 active task(handoff)
   每条带 source id 与 why-included，每层有预算与截断说明
-> search/timeline/get_observations 按需取详情（relation facts / skill 完整步骤 / raw evidence 属 query-driven L3/L4，不在 cold-start wake）
-> source observation 永远可追溯
```

### 2. wiki bridge 应该从 `codedb-mcp`、`ai-harness` 和 `mempalace closets` 借形

最小可行形态：

```text
accepted memory + curated docs
-> project-local generated knowledge cache
-> claim/module/source-map 中间结构层
-> docs/wiki 或其他可读派生输出
-> 每条 claim 保留 source observation / memory ID
```

这里借的是 project-local generated layer、source cache、generated/manual 分层、短索引指向原文、结构层先于 prose，不是借一个桌面 UI，也不是把派生 wiki 升格成 truth。

### 3. sleep cycle 应该从 `claude-mem` 的队列和 `mempalace` 的 contradiction 边界借形

安全形态：

```text
sleep scan
-> merge / dedupe / conflict / stale detection
-> pending candidates
-> human review 或 auto-low-risk review
-> accepted truth
```

不做：

- AI 直接删 accepted memory
- AI 直接 update confirmed rule
- 失败的后台任务静默丢消息

### 4. compact renderer 可以借 AAAK，但不能变成 truth

可接受：

```text
/hm:wake --format compact
```

输出短摘要、实体、标签、source ID。

不可接受：

```text
把 accepted memory 或 observation 改写成 AAAK 后丢掉原文
```

### 5. 文件级记忆辅助可以学 File Read Gate，但默认不应阻断

File Read Gate 的真正价值是“先给历史索引和成本提示”。在 `harness-mem` 中更适合先做成：

```text
harness-mem file-context <path>
```

或 MCP tool：

```text
get_file_memory(path)
```

先返回过去对这个文件的 observations、改动、决策和 token 成本。是否读取当前文件，仍由 agent 或用户决定。

### 6. code knowledge compilation 与 memory substrate 要分层

`codedb-mcp` 提醒我们：repo code intelligence 是另一条 substrate，和跨 session memory 互补但不能混淆。

可接受：

```text
repo source
-> project-local generated code intelligence / wiki cache
-> harness-mem 按 source ID / file path / claim ID 引用
```

不可接受：

```text
DeepWiki prose
-> 直接写成 accepted memory truth
```

### 7. Auto Dream 已借 `evo` 的账本和协议，不借自治实验循环

v3.1 Auto Dream Memory Maintenance 已吸收：

- 显式 run ledger / infra log
- host capability matrix
- plugin / CLI wire-format drift check
- opt-in host / scheduler trigger

仍只作为后置增强的是：

- prioritization strategy registry
- directive + ack
- explore/read phase cache

明确不借的是：

- 默认 unattended optimize loop
- benchmark hill-climb 产品目标
- 大规模 subagent orchestration 作为普通用户路径

## 新增镜像项目快速深读（2026-06-08）

下面这些项目已经下载到本地 `../../upstreams/` 并完成 README / 核心入口快速深读。
它们补强了参考图谱，但没有推翻当前产品边界：默认常驻后台、静默改 truth、cloud-first
telemetry、dashboard-first 和 generated prose as truth 仍不进入 `harness-mem` 主线。

| 项目 | 已读入口 | 新增可吸收点 | 当前处理 |
|---|---|---|---|
| `OpenSpace` | `README.md`、framework / benchmark sections | skill evolution 的 FIX / DERIVED / CAPTURED 生命周期、quality monitoring、anti-loop / safety gate、GDPVal token/cost benchmark 叙事。 | v3.1/v3.4 已吸收账本、health、cost 方向；不吸收 cloud skill community 或默认自治 skill rewrite。 |
| `Memento-Skills` | `README.md`、v0.3 architecture sections | Read -> Execute -> Reflect -> Write、skill routing/retrieval、agent profile、dream daemon、config migration。 | skill 只能走 candidate/review；agent profile / dream daemon 不成为默认后台主路径。 |
| `llm_wiki` | `README.md`、API/MCP sections | two-step ingest、source traceability、incremental queue、graph relevance、review queue、local API/MCP。 | v3.2 已吸收 source-map / freshness / generated boundary；不吸收 desktop app 或 wiki prose as truth。 |
| `meta-kb` | `README.md`、stats / roadmap sections | raw -> claims/articles、citation verification、自评迭代、incremental compile、claims-first 迁移方向。 | 强化 v3.2 的 atomic claims / citation validation；claims-first 可作为后置编译器增强。 |
| `hypatia` | `README.md`、benchmark sections | Knowledge / Statement triples、JSE 查询、DuckDB + SQLite FTS5、BGE-M3 LoCoMo/LongMemEval 数据。 | v3.3 已吸收 bounded temporal query；其 embedding benchmark 可作为下一轮真实 hybrid/vector 性能参考。 |
| `EverOS` | `README.md`、storage / use-case sections | Markdown + SQLite + LanceDB、user/agent 双轨、multimodal ingestion、benchmark ecosystem。 | 只吸收 use-case/benchmark 分类启发；不把 Markdown directory 变成 truth store，不走 cloud/dashboard-first。 |
| `hindsight` | `README.md`、retain/recall/reflect sections | retain / recall / reflect 三入口、world/experience/mental-model pathway、parallel semantic/keyword/graph/temporal retrieval。 | 支撑“learn not just recall”的产品叙事；不吸收 cloud/enterprise API 作为默认入口。 |
| `MemChinesePalace` | `README.md`、文简规范 / MCP sections | 简/牍双层、中文文简压缩、palace hierarchy、KG contradiction。 | 只作为 compact renderer / 中文压缩实验；不进入 canonical storage truth。 |
| [Jason Zuo X thread](https://x.com/xxxjzuo/status/2038086450013495554) | 想法线索 | “execution -> memory” 的 agent harness 叙事。 | 只有可访问、可引用后才正式摘录。 |

## 后续优先级

| 优先级 | 动作 | 原因 |
|---|---|---|
| P0 | 保持 `reference-projects.md` 作为外部参考唯一入口，后续读项目只补这里。 | 避免 roadmap 变成研究剪贴簿。 |
| P0 | 继续补 BENCH-001：重跑有 token/cost sidecar 的 enabled/disabled，对比要出现正向 saving delta 才能发布节省 claim。 | 当前 v3.8 已有 token-visible artifact，但 delta 为负；`codedb-mcp` / OpenSpace 的公开叙事都有正向 token/cost delta，本仓不能用机制成熟度替代收益证据。 |
| P0 | 扩展 BENCH-004 / BENCH-008：把 true-hybrid latency 与 retrieval recall 从 local synthetic / smoke 推到更大语料、更多 query type 和硬件说明。 | v3.8 已有 true-hybrid probe 与 local smoke source-hit recall，但仍不能外推生产延迟、broad corpus quality 或端到端回答正确率。 |
| P1 | claims-first generated compiler 实验。 | `meta-kb` 显示 claims-first 更适合 attribution accuracy 和增量重编译；只作为 generated layer，不改 truth。 |
| P1 | skill evolution health 只做候选与审计增强。 | `OpenSpace` / `Memento-Skills` 证明 skill evolution 有价值，但不能绕过 `ProceduralCandidate` / review。 |
| P2 | 文简 / AAAK 类压缩只放入 wake renderer 实验。 | 保护可审计性和原文追溯。 |

## 明确不做

- 不做 cloud-first memory platform。
- 不让 AI 自治删除 accepted memory。
- 不在 runtime 和 docs compiler 有价值前先做 desktop UI。
- 不用 Markdown directory 替代 memory source of truth。
- 不允许 skill auto-rewrite 绕过 candidate review。
- 不把 README 级 benchmark headline 直接写成 `harness-mem` 产品收益；本仓只引用自己 artifact-backed 结果。
