# 参考项目深读：记忆运行时、知识库与自进化

> **Maintainer-only — not user-facing.** 含可选本地 upstream 镜像路径；公开 clone 不必配置这些目录。

> 状态：持续维护的参考地图。
>
> 初次收录：2026-05-18。中文化与本地深读修订：2026-05-19。
>
> 本文记录对 `harness-mem` 设计有参考价值的外部项目。它不是路线图本身；当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。若需回看当时的历史路线设计，再参考 `roadmap-v15x.md`、`roadmap-v16x.md`、`roadmap-v17x.md` 与 `roadmap-vision-v16-v18.md`。

## Reference Scorecard and Absorption Priorities

> 说明：本节是 maintainer decision artifact，不是公开 benchmark，也不是路线图承诺。
> 分数是 0-10 的主观成熟度估算，用来判断 `harness-mem` 该借什么、不该借什么。
> `harness-mem v3.4 shipped` 代表 v3.1-v3.4 完成后的当前基线；具体已发布能力仍以
> [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。
> 对外硬指标必须再看 `benchmark_matrix_report()["claim_readiness"]`：
> 当前 token/cost saving 不是 ready 状态；true vector-hybrid latency / retrieval
> recall 只对本地 synthetic / smoke artifact ready。

### 对比维度

| 维度 | 看什么 | 对 `harness-mem` 的意义 |
|---|---|---|
| Memory runtime | 记忆写入、检索、wake、候选审核、跨 session 使用 | 当前主产品能力，不能被其它路线稀释 |
| Evidence safety | 原文追溯、source ids、citation、candidate-first、truth 不被生成物污染 | `harness-mem` 的核心护城河 |
| Generated knowledge | source map、atomic claims、wiki bridge、compact context、incremental cache | v3.2 主线 |
| Temporal query | current/history/as_of、valid/recorded time、supersede timeline、abstention | v3.3 主线 |
| Auto maintenance | dream/reflection/metabolism、queue/job health、维护动作账本 | v3.1 主线 |
| Observability | health、freshness、failures、version drift、doctor/status/report | v3.4 主线之一 |
| Cost discipline | token 输出、上下文浪费、宽泛查询、全文 dump、budget policy | 必须单独成类，不能混进 observability |
| Performance | tool latency、index/cache、增量更新、warm-call speed | 影响主链是否被 memory 系统拖慢 |

### 主观 Scorecard

| 项目 | Memory | Evidence | Generated | Temporal | Auto maint | Observability | Cost discipline | Performance |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `harness-mem v2.9.61` | 8.0 | 8.2 | 5.5 | 5.0 | 3.5 | 4.0 | 4.5 | 6.5 |
| `harness-mem v3.4 shipped` | 8.7 | 8.8 | 8.8 | 8.7 | 8.3 | 8.6 | 8.8 | 7.8 |
| `claude-mem` | 7.5 | 7.0 | 4.5 | 4.0 | 7.5 | 7.5 | 6.8 | 6.8 |
| `mempalace` | 8.0 | 8.5 | 5.5 | 7.5 | 5.0 | 5.5 | 6.0 | 6.5 |
| `codedb-mcp` | 4.0 | 7.0 | 9.0 | 3.0 | 4.0 | 8.0 | 9.2 | 9.3 |
| `Graphiti / Zep` | 6.5 | 7.0 | 5.0 | 9.0 | 6.0 | 6.5 | 6.0 | 7.0 |
| `Letta` | 8.5 | 6.5 | 5.0 | 5.5 | 7.0 | 6.5 | 6.0 | 6.8 |
| `evo` | 3.0 | 5.0 | 3.0 | 2.0 | 9.0 | 8.0 | 7.5 | 7.0 |
| `OpenSpace` | 5.5 | 5.8 | 4.0 | 3.0 | 9.0 | 8.5 | 8.5 | 7.5 |
| `Memento-Skills` | 6.8 | 5.8 | 4.0 | 4.0 | 8.5 | 7.5 | 6.5 | 6.5 |
| `llm_wiki` | 5.0 | 8.0 | 9.0 | 4.0 | 6.5 | 7.5 | 7.5 | 7.0 |
| `meta-kb` | 4.0 | 9.0 | 9.2 | 6.0 | 7.0 | 8.0 | 8.0 | 7.0 |
| `hypatia` | 8.0 | 7.5 | 3.5 | 8.5 | 4.0 | 6.0 | 6.0 | 8.0 |
| `EverOS` | 8.5 | 7.0 | 6.0 | 7.0 | 7.5 | 7.5 | 6.8 | 7.2 |
| `hindsight` | 8.8 | 6.5 | 5.0 | 8.0 | 7.5 | 7.5 | 6.5 | 8.0 |
| `MemChinesePalace` | 7.0 | 7.5 | 4.0 | 7.0 | 5.0 | 5.0 | 8.5 | 7.0 |

### 数值图口径

这些条形图是 maintainer 估算，不是 benchmark。它们回答“产品能力成熟度大概在哪”，
不回答“对外可发布的 token / latency 硬指标是否成立”。

```text
整体成熟度（主观，加权）

harness-mem v2.9.61      ██████▋     6.6
harness-mem v3.4 shipped ████████▋   8.6
claude-mem               ██████▊     6.8
mempalace                ███████     7.0
codedb-mcp               ██████▊     6.8
Graphiti / Zep           ███████▌    7.5
Letta                    ███████     7.0
evo                      ██████▏     6.2
```

`harness-mem v3.4 shipped` 的能力提升主要来自 v3.1 Auto Dream、v3.2 Generated
Knowledge、v3.3 Temporal Query、v3.4 Runtime Health / Cost / Regression，而不是基础
search 从低分突然变满分：

```text
能力维度变化（主观）

Memory runtime       8.0 -> 8.7  ████████▋
Evidence safety      8.2 -> 8.8  ████████▊
Generated knowledge  5.5 -> 8.8  ████████▊
Temporal query       5.0 -> 8.7  ████████▋
Auto maintenance     3.5 -> 8.3  ████████▎
Observability        4.0 -> 8.6  ████████▋
Cost discipline      4.5 -> 8.8  ████████▊
Performance          6.5 -> 7.8  ███████▊
```

### 硬指标 Claim Gate

主观分数不能替代 artifact。当前 v3.8 benchmark matrix 的真实发布门槛是：

| Claim | Matrix field | Current value | 对外口径 |
|---|---|---:|---|
| Benchmark artifact gate | `gate.passed` | `true` | 可以说当前 11 个 BENCH artifact 内部通过 |
| Token/cost saving | `claim_readiness.token_cost_saving.ready` | `false` | 不能说 token/cost saving 已被证明 |
| True vector-hybrid latency | `claim_readiness.true_vector_hybrid_latency.ready` | `true` | 只能说本地 synthetic true-hybrid probe 无 fallback；不能外推生产延迟 |
| Retrieval recall | `claim_readiness.retrieval_recall.ready` | `true` | 只能说本地 smoke source-hit recall；不能外推端到端回答正确率 |

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
`token_usage` 来源以及正向 saving delta；对外讲 true vector-hybrid latency 时，
`benchmark_matrix_report()` 的 `claim_readiness.true_vector_hybrid_latency.ready`
必须为 `true`，且文案必须保留 local synthetic fixture 边界。

### 吸收优先级

| 已落地线 | P0 参考 | 已吸收 | 不吸收 |
|---|---|---|---|
| v3.1 Auto Dream | `claude-mem` + `evo` + `OpenSpace` + `Memento-Skills` | queue/job health、显式 DreamRun 账本、apply/reject/undo、host/scheduler 触发、skill/dream 健康信号 | always-on daemon、自治 truth mutation、默认 subagent orchestration、skill 自改后直接替换 confirmed truth |
| v3.2 Generated Knowledge Compiler | `codedb-mcp` + `llm_wiki` + `meta-kb` + `ai-harness` | project-local generated layer、source map、atomic claims、citation validation、incremental cache、freshness/status 可见性 | 把 DeepWiki/wiki prose 或 generated cache 当 truth |
| v3.3 Temporal Query | `Graphiti` + `hypatia` + `mempalace` + `hindsight` | current/history/as_of、valid/recorded time、supersede timeline、temporal query traces、abstention metadata | 完整图数据库、自动 ontology、AI 直接改 confirmed truth |
| v3.4 Runtime Health / Cost / Regression | `codedb-mcp` + `claude-mem` + `evo` + `EverOS` + `OpenSpace` | cost observer、per-surface budget、runtime health、version drift、benchmark dimensions、false-success accounting | 云端 telemetry、dashboard-first、observer 自治调参 |

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
| P0 | 补强 BENCH-001：用可见 token/cost counter 重跑 enabled/disabled。 | `codedb-mcp` / OpenSpace 的公开叙事都有 token/cost delta；当前 BENCH-001 token unavailable，不能宣传省钱。 |
| P0 | 补强 BENCH-004：在 embedding 可用时重跑真实 vector/hybrid latency。 | `hypatia` 等参考项目给了 embedding latency/quality 表；当前 BENCH-004 hybrid fallback 到 FTS。 |
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
