# Roadmap: harness-mem v4.0

> 状态：v4.0.0-v4.0.5 已完成；v4.1.0 已完成第一版。
>
> 主题：Storage v2 + Rust Core + Local Memory Index Fabric。把 harness-mem 从
> "Python 编排 + JSON blob truth + SQLite index" 升级为 "DB-first canonical
> store + Rust hot path + 本地可审计索引织物 + Python/Agent orchestration"。
> v4.0 只打存储、索引、热路径和 benchmark 地基；v4.1 已进入 context
> sufficiency、task-aware wake 和 local routing；v4.2 再把 memory evals 产品化。

---

## 一句话

v4.0 不是一次性 Rust 大重写，也不是把 harness-mem 变成本地通用 Agent 平台。
它要先解决本地记忆越长越慢、碎文件越来越多、索引派生产物不可控、性能收益不可证明的问题。

更硬一点的产品定位是：

```text
harness-mem is a local-first agentic memory runtime with auditable evidence,
candidate-gated learning, task-aware wake context, context sufficiency checks,
and release-gated memory quality evaluation.
```

这意味着后续不是补"基础 Agentic RAG 形态"，而是把已经存在的 raw evidence、candidate-before-truth、
progressive disclosure、runtime health、cost budget 和 benchmark governance 升级成
enterprise-grade memory quality gates。

```text
v3.x
Python stores
  -> JSON blob truth
  -> SQLite metadata / FTS / sqlite-vec
  -> Python hybrid ranking
  -> benchmark evidence mostly around current retrieval surfaces

v4.0 target
Python MCP / CLI / Skills
  -> PyO3 / stable JSON contract
  -> harness_mem_core_rs
       -> canonical SQLite store
       -> bulk ingest / session scanner
       -> Local Memory Index Fabric
            -> compact sidecars
            -> lazy exact / word / trigram / vector / graph indexes
            -> manifest-last generation commits
       -> lifecycle tier scorer
       -> migration / export / rollback
       -> benchmark artifact contract
```

## v4.x 分层边界

| 版本线 | 定位 | 为什么不混在一起 |
|---|---|---|
| v4.0 | Storage v2 + Rust Core + Local Memory Index Fabric | 先让本地 store、index、migration、benchmark 可证明，避免在慢底座上堆 agentic loop。 |
| v4.1 | Context Sufficiency + Task-Aware Wake | 在 v4.0 的 corpus / metadata / index contract 上做证据充分性检查、wake packet budget、local routing 和可审计 context plan。 |
| v4.2 | Memory Evals + Retrieval Quality Pack | 把 LongMemEval / memory eval matrix 产品化，再做 reranker、query rewriting、HyDE/multi-query、embedding shootout、recall drift suite。 |
| v4.3 | Code-Memory Federation | 把 repo code-intel substrate 与 memory runtime 联邦起来，引用代码证据，但不把 generated prose 写成 truth。 |

核心判断：**Agentic 是检索编排能力，不是自治改记忆能力。** 智能路由、补查、说明证据不足可以做；
confirmed truth 变更仍必须走 candidate / review / supersede / ledger。

## 为什么现在做

v3.8 已经把 benchmark evidence、generated claim hardening、skill governance 和 true-hybrid
retrieval shootout 边界说清楚了。下一步的瓶颈不再是"有没有 hybrid search"，而是：

| 痛点 | v3.x 当前形态 | v4.0 目标 |
|---|---|---|
| 小文件 I/O | structured / verbatim truth 仍大量落在逐条 JSON 文件 | canonical payload 进入 SQLite；JSON 退到 export / debug / compat surface |
| 热路径 Python 对象开销 | JSON 反序列化、candidate 排序、RRF、trigram/exact 仍在 Python 层 | Rust 承担 bulk parse、tokenize、ranking、index build |
| 索引派生产物松散 | FTS/vector/generated cache 各自维护，缺少统一 freshness / commit 纪律 | Local Memory Index Fabric 管理 generation sidecars、manifest-last commits、lazy rebuild |
| 检索后端耦合 | SQLite FTS5 / sqlite-vec 与 store 强绑定 | SearchBackend contract 由 v4.0 index fabric 承载，后续可评测 Tantivy / LanceDB |
| 生命周期治理 | 已有 signals / metabolism / temporal truth，但冷热分层不是存储一等概念 | hot/warm/cold/archive tier 成为 read-path 与 maintenance-path 的正式字段 |
| 发行复杂度 | 纯 Python wheel 简单，但高性能扩展路径不成体系 | maturin wheel / fallback pure-Python path / platform matrix 一起设计 |
| 功能收益不稳定 | benchmark 已有，但还不足以覆盖存储迁移、索引重建和 drift | 每个 v4.x 功能必须绑定 before/after benchmark、regression test 和 public claim gate |

## 参考项目吸收：`codedb-mcp` 的真正价值

`codedb-mcp` 不是 memory runtime，但它展示了本地索引系统应该怎么长出来。v4.0 要重点吸收它的底层
工程经验，而不是只把它当成 "Tantivy / LanceDB spike"。

| `codedb-mcp` 机制 | v4.0 可吸收形态 | 边界 |
|---|---|---|
| `.codedb-mcp/` project-local generated layer | `.harness-mem/index/` 或 DB-adjacent generated layer，派生产物显式可删、可诊断 | generated layer 不是 truth store |
| cache v23 generation sidecars | `generation_id` 命名的 compact binary sidecars | 不能让半写入 sidecar 成为可见 truth |
| manifest-last commits | 先写所有 sidecar，最后原子切 manifest | crash 后继续使用上一代可用索引 |
| `index.*.bin`、`fingerprints.*.bin`、offset-addressed outlines | compact binary postings、fingerprint、offset tables | 先做 memory/query index，不追求完整 code-intel |
| lazy `word_index.bin` / `text_search_index.bin` / `callers.bin` / `deps.*.bin` | lazy exact / word / trigram / vector / relation graph indexes | 未加载 sidecar 不应拖慢 wake/search fast path |
| Model2Vec lazy file embeddings + flat cosine scan | 轻量 vector baseline 的可选本地实现与 benchmark 对照 | 默认 embedding 不因路线图静默替换 |
| `codedb_context` / `codedb_explore` output budgets | memory context plan 也要预算化、可解释、可 drilldown | 不把长 source dump 伪装成"高质量上下文" |
| tool-cost observer | v4.x benchmark 要记录 output token、wide search、missed context/fusion opportunity | observer 失败不阻断主调用 |
| warm process fast path | Rust core / index fabric 支持 warm in-process measurement | benchmark 必须区分 cold start、first lazy load、warm query |

结论：v4.0 的核心新增不是"换一个搜索库"，而是引入一层 **Local Memory Index Fabric**：
它把 canonical store、派生索引、freshness、sidecar generation、lazy rebuild、benchmark
artifact 和 fallback semantics 统一起来。

## 产品原则

1. **Local-first 不变**：默认仍是本地文件、SQLite、本地模型，不引入云服务依赖。
2. **Truth governance 不变**：AI 可以建议、归纳、归档，但 confirmed truth 变更必须走
   candidate / review / supersede / ledger。
3. **Rust 是 hot path，不是产品壳**：第一阶段只迁移确定性数据工作；MCP / Skill / Agent workflow
   继续由 Python 承担。
4. **DB-first，不是 JSON-free**：SQLite 成为 canonical store；JSON 仍保留为导出、调试、兼容迁移和
   human-readable snapshot。
5. **Index fabric，不是数据库崇拜**：SQLite 是 truth 和默认索引底座；compact binary sidecar
   是可重建派生产物。
6. **Benchmark 决定默认项**：Tantivy、LanceDB、embedding 模型、ANN 策略、reranker 都必须过
   recall / latency / disk / install friction gate，不能凭感觉切默认。
7. **可逆优先**：v4.0 必须支持 side-by-side backend、dry-run migration、export rollback 和 fallback。
8. **Serverless-like 本地体验**：无默认 daemon、无云、按需运行、自动建索引、自动 fallback、doctor 可诊断。

## 目标架构

```text
┌──────────────────────────────────────────────────────────────┐
│ Agent / Slash / Skill / MCP                                  │
│ wake, search, distill, candidate review, maintenance          │
└───────────────────────────────┬──────────────────────────────┘
                                │ Python stable facade
┌───────────────────────────────▼──────────────────────────────┐
│ harness_mem Python package                                    │
│ - MCP server / tool schemas                                    │
│ - CLI maintenance / doctor                                     │
│ - Pydantic compatibility schemas                               │
│ - candidate workflow orchestration                             │
└───────────────────────────────┬──────────────────────────────┘
                                │ PyO3 / JSON contract / HM-xxx errors
┌───────────────────────────────▼──────────────────────────────┐
│ harness_mem_core_rs                                           │
│ - canonical store API                                          │
│ - session scanner + tolerant JSONL parser                      │
│ - bulk index builder                                           │
│ - lifecycle tier scorer                                        │
│ - migration/export engine                                      │
│ - Local Memory Index Fabric                                    │
└───────────────┬───────────────────────────────┬──────────────┘
                │                               │
┌───────────────▼──────────────┐ ┌──────────────▼───────────────┐
│ SQLite canonical store        │ │ Generated index sidecars      │
│ payload_json, metadata, FTS5,  │ │ exact/word/trigram/vector/    │
│ vec rows, access stats        │ │ graph, manifest-last commits  │
└───────────────────────────────┘ └──────────────────────────────┘
```

## v4.0.0：Baseline, Benchmark, and Migration Contract

**用户故事**：维护者知道 v4.0 要解决的性能问题有多大，迁移是否真的值得。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 10k / 100k / 1M synthetic corpus | 固定 corpus generator、seed、entry mix、payload size、project count |
| P0 | baseline report | v3.8 backend 的 ingest throughput、search p50/p95、wake p95、RSS、DB size、JSON file count |
| P0 | migration contract | dry-run 输出变更摘要；apply 前后 logical checksum 一致 |
| P0 | rollback contract | 从 canonical store export 回 v3-compatible JSON blobs |
| P0 | benchmark artifact schema | 每次结果带 benchmark id、dataset hash、command、hardware、commit、p50/p95、RSS、disk、fallback fields |
| P1 | real-dogfood sample | 对本机真实 session archive 做 private benchmark，不进公开 claim |

实现说明：这一步不改默认存储。先建立 `storage_v2_baseline`、`migration_roundtrip`、
`local_index_fabric_smoke` 三类 benchmark collection，以及
`maintenance migrate-store-v2 --dry-run` 的 contract。

### 当前实现（2026-06-12）

v4.0.0 已完成为一个 contract / evidence slice，不改默认 runtime backend：

- `harness_mem/storage/store_v2_migration.py` 提供 side-by-side Storage v2
  migration contract：dry-run 扫描 v3 JSON blobs、apply 写
  `store_v2/canonical.sqlite`、logical checksum 校验、rollback export 回
  v3-compatible JSON blobs。
- `harness-mem maintenance migrate-store-v2 --dry-run` 是默认无写入口；
  `--apply` 才写 canonical DB；`--export-rollback <dir>` 默认仍 dry-run，
  只有配合 `--apply` 才写 rollback snapshot。
- `benchmark-suite/tools/storage_v2_fixture.py` 固定 synthetic corpus generator，
  seed / entry mix / payload size / project count 可复现，并提供
  `--profile 10k|100k|1m` profile；smoke 默认仍跑小样本。
- `benchmark-suite/storage_v2_baseline`、`migration_roundtrip`、
  `local_index_fabric_smoke` 三类 collection 已进入 `suite.json` 和 packaged
  resource schema，结果字段包含 benchmark id、dataset hash、command、hardware、
  commit、p50/p95、RSS、disk、DB size、sidecar size、fallback / claim readiness。
- 本 slice 的本地 evidence 是三条 diagnostic smoke artifact：
  `2026-06-12-storage-v2-baseline-smoke-v400`、
  `2026-06-12-migration-roundtrip-smoke-v400`、
  `2026-06-12-local-index-fabric-smoke-v400`，均通过
  `benchmark-suite/tools/validate_run.py`。这些 artifact 证明合同和 schema，
  不证明公开性能收益。

明确未做：v4.0.0 不把 canonical SQLite 设为默认 truth store，不引入 Rust core，
不实现 runtime SearchBackend / real Local Memory Index Fabric，不启动 v4.1 的
context sufficiency、task-aware wake 或 local routing。

## v4.0.1：Canonical SQLite Store

**用户故事**：百万级记忆不再依赖百万个小 JSON 文件，读写、备份和维护都有一个主事实来源。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | canonical entity tables | observations、memory_entries、rules、skills、relations、candidates、signals 等 payload_json 入库 |
| P0 | indexed metadata columns | `project_id`、`corpus_id`、`type`、`truth_status`、`confidence`、`created_at`、`valid_from/valid_to` 可过滤 |
| P0 | compatibility reader | 老 JSON blob data dir 可读；首次迁移不阻塞 search / wake |
| P0 | dual-write gate | experimental profile 可同时写 JSON + DB，checksum 比对 |
| P0 | doctor support | 检测未迁移、部分迁移、checksum drift、WAL 体积、index drift |
| P1 | export snapshots | `maintenance export-json-snapshot` 输出 human-readable JSON snapshot |

设计立场：SQLite 主库是 truth，FTS/vector/exact/sidecar 是 index，JSON 是 snapshot。不要再让 JSON blob
和 SQLite row 互相当对方的半真相。

### 当前实现（2026-06-12）

v4.0.1 已完成 canonical store 的第一版 runtime contract：

- `harness_mem/storage/canonical_store.py` 提供 observations、memory_entries、
  rules、skills、relations、candidates、signals、task_handoffs 等 canonical
  entity tables，并保留 payload_json。
- indexed metadata 覆盖 `project_id`、`corpus_id`、`type`、`truth_status`、
  `confidence`、`created_at`、`valid_from`、`valid_to`、`tier` 与 access fields。
- `maintenance migrate-store-v2 --apply` 会构建 canonical entity store；
  `HARNESS_MEM_STORAGE_V2_DUAL_WRITE` 作为 experimental dual-write gate。
- `maintenance export-json-snapshot --export-dir ...` 输出 human-readable JSON
  snapshot；doctor 输出 Storage v2 block，但 `health_summary()` 顶层 contract
  保持兼容。

验证：`tests/storage/test_canonical_store.py`、
`tests/cli/test_export_json_snapshot.py` 与 `tests/cli/test_store_v2_migration.py`。

## v4.0.2：Rust Core MVP

**用户故事**：热路径性能来自一个可测试、可发布、可回退的 Rust core，而不是散落的 Python micro-optimizations。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `harness_mem_core_rs` crate | 通过 PyO3 暴露稳定 API；Python facade 不泄露 Rust 内部类型 |
| P0 | tolerant JSONL scanner | Codex / Claude session 解析与现有 Python parser contract 等价 |
| P0 | bulk index builder | 批量写 canonical store、FTS payload、exact/trigram candidates |
| P0 | ranking primitives | RRF、exact boost、metadata penalty、source diversity 在 Rust 侧有 deterministic tests |
| P0 | error mapping | Rust errors 映射到稳定 `HM-xxx` 或 Python exception class |
| P1 | pure-Python fallback | 没有 Rust wheel 时，doctor 明确提示，核心 read path 不硬崩 |

迁移边界：第一阶段不迁 MCP server，不迁 candidate review policy，不迁 distill skill。Rust core 只负责
deterministic data work。

### 当前实现（2026-06-12）

v4.0.2 已完成 Rust Core MVP 的发布形态地基：

- `harness_mem/rust_core.py` 暴露 stable Python facade：`rust_core_status`、
  `scan_jsonl`、`build_bulk_index_rows`、`reciprocal_rank_fusion`、
  `rank_candidates`、`error_to_hm_code`。
- 新增 `Cargo.toml` 与 `crates/harness_mem_core_rs/` crate skeleton，sdist
  include 已覆盖 Rust workspace。
- 没有 native wheel 时进入明确的 `python_fallback`；doctor / distribution
  report 可见 fallback，不让 read path 硬崩。

验证：`tests/test_rust_core_facade.py`；Rust unit tests 由 `cargo test --workspace`
作为 release gate 覆盖。

## v4.0.3：Local Memory Index Fabric MVP

**用户故事**：检索索引、派生缓存和可选后端可以独立演化，但上层 wake/search/candidate 逻辑不跟着重写。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `IndexManifest` | manifest-last commit，包含 generation id、source fingerprint、schema version、sidecar list、build metrics |
| P0 | compact binary sidecars | exact / word / trigram postings 支持 mmap 或 bounded read；半写入 generation 不可见 |
| P0 | lazy rebuild semantics | exact/word/trigram/vector/graph sidecar 可按需构建，source fingerprint drift 时重建 |
| P0 | SearchBackend contract | `search(query, filters, mode, limit)` 返回统一 score、source id、fallback metadata |
| P0 | SQLite backend conformance | 现有 FTS5 + sqlite-vec 行为通过 contract tests |
| P0 | context budget output | search/context 结果携带 budget、truncation、source coverage、drilldown hints |
| P1 | Tantivy spike | 只作为 experimental backend；默认开关关闭 |
| P1 | LanceDB spike | 只在 vector benchmark 证明 sqlite-vec 成为瓶颈后进入候选 |
| P1 | graph sidecar prototype | relation / supersede / source graph 只作为可重建索引，不写 truth |

默认策略：SQLite backend 仍是 v4.0 默认。Tantivy / LanceDB 是 evidence-driven upgrade，不是路线图口号。
Local Memory Index Fabric 是 SearchBackend contract 的物理层，也是 v4.1 corpus routing 的基础。

### 当前实现（2026-06-12）

v4.0.3 已完成 Local Memory Index Fabric 和 SearchBackend contract 的第一版：

- `harness_mem/search/backend.py` 定义 `SearchFilters`、
  `BackendSearchResult`、`SearchBackendResponse` 与 `SQLiteSearchBackend`，
  统一 score、source id、fallback metadata、budget、truncation、source coverage
  和 drilldown hints。
- `harness_mem/index_fabric/manifest.py` 实现 manifest-last generation、
  source fingerprint drift、lazy rebuild 和 exact/word/trigram/graph JSON
  sidecars；半写入 generation 不成为可见索引。
- 默认 backend 仍是 SQLite；Tantivy / LanceDB 仍是 future evidence-driven
  candidates，不在 v4.0.3 默认路径。

验证：`tests/search/test_search_backend_contract.py` 与
`tests/test_index_fabric_manifest.py`。

## v4.0.4：Lifecycle Tiering and GC

**用户故事**：记忆越多，默认上下文越干净；旧东西还在，但不会默认污染 wake。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | tier fields | `tier=hot/warm/cold/archive`、`last_accessed_at`、`access_count`、`decay_score` 入 canonical store |
| P0 | read-path semantics | 默认 search/wake 查 hot/warm；deep recall 显式包含 cold/archive |
| P0 | lifecycle candidates | tier downgrade、merge、stale、archive 都写候选或 ledger，不静默改 confirmed truth |
| P0 | access signal writeback | search/wake 命中可记录 bounded access signal，observer 失败不阻断主路径 |
| P1 | compression/archive | archive tier 可压缩 payload 或移入 archive segment，但必须可恢复 |

安全边界：GC 是 governance，不是删除脚本。confirmed truth 默认不会 hard delete，除非用户显式 purge。

### 当前实现（2026-06-12）

v4.0.4 已完成 lifecycle tiering 的 read-path 和 candidate contract：

- `MemoryEntry` 增加 `tier` 与 `decay_score`；canonical metadata 也保留 tier
  和 access fields。
- `LocalStructuredStore.search_memory_entries/list_memory_entries` 默认排除
  cold/archive；`deep_recall=True` 显式纳入 cold/archive。
- MCP `search_memory` / `wake` 和 read API 暴露 `deep_recall`，保持默认输出兼容。
- `harness_mem/lifecycle.py` 只选择 downgrade / archive / merge 等候选，不静默
  mutation confirmed truth。

验证：`tests/test_lifecycle_tiering.py`。

## v4.0.5：Distribution and Release Gate

**用户故事**：用户安装 v4.0 不需要懂 Rust toolchain；维护者能看到哪个平台用的是 Rust wheel，哪个平台 fallback。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | wheel matrix | Windows / macOS / Linux，x64 / arm64 目标明确 |
| P0 | local build docs | 没有预编译 wheel 时可从源码构建，错误信息清楚 |
| P0 | release gate | pytest / ruff / mypy + Rust unit tests + Python/Rust contract tests + benchmark smoke |
| P0 | public claim gate | README 只写 artifact ready 的性能 claim |
| P0 | doctor platform report | Rust wheel、fallback、index fabric manifest、sidecar freshness 都能诊断 |
| P1 | binary size budget | wheel size、cold import time、doctor startup time 有阈值 |

### 当前实现（2026-06-12）

v4.0.5 已完成 distribution gate 的诊断与文档地基：

- `harness_mem/distribution.py` 汇总 platform、Rust mode/fallback、index fabric
  manifest freshness 和 release gate hints。
- doctor CLI 输出 distribution block；`health_summary()` 顶层键保持兼容，避免
  破坏既有 MCP health consumers。
- `pyproject.toml` sdist include 覆盖 `Cargo.toml` 与 `crates`，public release
  export 规则同步 Rust workspace。

验证：`tests/test_distribution_report.py`、
`tests/test_health_summary.py` 与 `tests/cli/test_doctor_vector_health.py`。

## v4.1：Context Sufficiency + Task-Aware Wake

v4.1 不是补基础 RAG，也不是本地 Google RAG 平台。它要把 harness-mem 已有的 evidence、
source ids、progressive disclosure、candidate-before-truth 和 cost budget 延伸到回答前的
质量门：**没有足够证据，就不把 recall 伪装成 truth。** 本地实现继续保持轻量、可审计、
无云、无默认 daemon。

```text
query
-> cheap query classifier
   -> simple: current hybrid search
   -> cross-corpus / multi-hop: local retrieval planner
-> CorpusProfile routing
-> MetadataFilter prefilter
-> per-corpus hybrid retrieval
-> merge + RRF + diversity
-> SufficiencyReport
   -> sufficient: ContextPlan
   -> insufficient and budget remains: IterativeRetrievalTrace + one more targeted retrieval
   -> still insufficient: abstain + missing evidence report
```

### Context Sufficiency Gate

`wake/search/answer-me` 不只返回 top-k，而是返回证据充分性：

```yaml
context_sufficiency:
  status: sufficient | partial | insufficient
  support_level: direct | inferential | weak | missing
  missing_evidence:
    - "缺最近一次 accepted decision"
    - "缺失败测试原始日志"
  safe_to_answer: true | false
  recommended_action:
    - expand_observations
    - run_timeline
    - ask_user
    - answer_with_caveat
```

第一版优先 deterministic checks：关键实体覆盖、时间范围覆盖、source diversity、required slots、
证据冲突、top-k 分数断崖、truth_status / valid_from / valid_to。LLM sufficiency judge 可以 optional，
但不能成为默认 truth gate。

### Wake Packet Budgeter

v3.4 已经有 cost budget 和 truncation metadata；v4.1 已把它升级成主动上下文调度器。

```yaml
wake_packet:
  budget_tokens: 6000
  hard_include:
    - accepted/current rules
    - active task handoff
    - recent blockers
  soft_include:
    - related observations
    - procedural skills
  evict_first:
    - stale truths
    - low-support summaries
    - repeated handoffs
  why_included:
    - source_id: "..."
      reason: "task matches active blocker"
  why_omitted:
    - source_id: "..."
      reason: "cold tier and not needed for current query"
  budget_trace:
    requested: 6000
    used: 5480
    truncated: true
```

这让 wake 从"confirmed memory renderer"升级成 task-aware minimal sufficient context packet。

| 构件 | 作用 | 边界 |
|---|---|---|
| `CorpusProfile` | `corpus_id`、description、domain、entities、time_range、source_types、trust_level、metadata_schema | 描述本地 corpus，不注册云资源 |
| `RetrievalPlan` | 说明查哪些 corpus、为什么查、跳过哪些、预算多少 | 必须可输出给用户或日志审计 |
| `MetadataFilter` | schema-based prefilter，先缩候选再做 FTS/vector | 默认走 SQLite indexed fields；不先引入重服务 |
| `SufficiencyReport` | `covered`、`missing`、`conflicting`、`confidence`、`next_queries` | 第一版优先 deterministic checks，LLM judge 只能 optional |
| `IterativeRetrievalTrace` | 记录第二轮或第三轮补查的 query、corpus、filter、结果 | 最多 1-2 轮，有预算和 kill switch |
| `ContextPlan` | 最终给下游的 context、source ids、why included、drilldown hints | 输出 top-k 之外的可解释计划 |

v4.1 不做本地 Gemini Enterprise，也不做本地 Vertex AI。它只是：

```text
local-first memory runtime
+ corpus routing
+ metadata prefilter
+ hybrid retrieval
+ sufficiency check
+ iterative retrieval
+ auditable context plan
```

### 当前实现（2026-06-12）

v4.1.0 已完成 Context Sufficiency + Task-Aware Wake 的第一版 deterministic
runtime surface：

- `harness_mem/core/schemas/context_sufficiency.py` 定义 `CorpusProfile`、
  `RetrievalPlan`、`MetadataFilter`、`SufficiencyReport`、
  `IterativeRetrievalTrace`、`ContextPlan` 与 `WakePacket`。
- `harness_mem/context_sufficiency.py` 提供 task-aware context assembly，
  默认最多两轮 retrieval，输出 missing evidence、next queries、safe_to_answer
  与 why-included / why-omitted。
- MCP `search_memory` 返回 `context_sufficiency`、`retrieval_plan`、
  `context_plan`、`iterative_retrieval_trace`；MCP `wake` 额外接受
  `current_task`、`budget_tokens`、`deep_recall` 并返回 `wake_packet`。
- 质量门只做 deterministic checks，不把 LLM judge 当默认 truth gate；证据不足时
  建议补查、ask_user 或 answer_with_caveat，不静默 mutation confirmed truth。

验证：`tests/test_context_sufficiency.py` 与
`tests/mcp/test_context_sufficiency_surfaces.py`。

## v4.2：Memory Evals + Retrieval Quality Pack

v4.2 只在 v4.1 pipeline 可解释之后做质量增强，避免先上模型再找理由。它的第一优先级是把
memory evals 从维护工具升级成 release gate：不仅测 search latency，也测 memory runtime 是否真的
帮 agent 少犯错。

```yaml
memory_eval_matrix:
  - cross_session_resume
  - stale_truth_rejection
  - raw_evidence_recovery
  - candidate_noise_rejection
  - task_aware_wake_precision
  - multi_client_consistency
  - wire_format_backward_compat
  - context_sufficiency_accuracy
```

| 能力 | 默认策略 | Benchmark gate |
|---|---|---|
| Memory eval matrix | release gate，不是手工维护脚本 | cross-session、stale truth、raw evidence、candidate noise、task-aware wake、multi-client、wire-format、sufficiency accuracy |
| Reranker | `harness-mem[rerank]` optional，不进默认轻路径 | precision@k、latency、RSS、model size、cold start |
| Query rewriting | 规则 / 小模型可插拔，默认只在 multi-hop 或 insufficiency 后触发 | recall uplift 必须大于 false-positive drift |
| Multi-query / HyDE | experimental profile | 记录 fanout cost、duplicate rate、answer sufficiency delta |
| Embedding shootout | 继续以 `all-MiniLM-L6-v2` 为 baseline，候选模型走 artifact gate | recall、latency、disk/cache、install friction 全部过线才换默认 |
| Retrieval drift suite | 固定 query pack + source-hit + negative queries | 每次索引或模型变更都跑 smoke gate |

## v4.3：Code-Memory Federation

v4.3 把 `codedb-mcp` 类 code-intel substrate 与 harness-mem 的 long-term memory 联邦起来。
这不是把 harness-mem 改成 code search 引擎，而是让记忆能引用代码证据、模块图和当前源码状态。

```text
repo code-intel substrate
  -> file fingerprints / symbols / deps / module atlas
  -> source evidence ids

harness-mem memory runtime
  -> decisions / rules / observations / temporal truth
  -> references code evidence, not generated prose as truth
```

验收方向：

- `file_context` 能同时看到历史 memory、当前 file fingerprint、代码符号和相关决策。
- generated code wiki / module atlas 只能作为派生解释层，不能直接写 accepted memory。
- memory entry 引用代码证据时必须有 source id、file path、fingerprint 或 line range 的 stale 检查。
- benchmark 要比较 broad file reads/searches 是否减少，但不能把 `codedb-mcp` 的 token/runtime 直接写成 harness-mem 收益。

## 测试矩阵

```text
Roadmap truth tests
  docs index includes v4.0
  v4.0/v4.1/v4.2/v4.3 boundaries are explicit
  benchmark gate and no-silent-truth-mutation boundary stay present

Contract tests
  Python schema -> Rust API -> Python schema
  old JSON blobs -> canonical DB -> exported JSON
  SearchBackend response -> Python MCP response

Storage tests
  empty store
  legacy store
  partial migration
  checksum drift
  WAL recovery
  old JSON read compatibility

Index fabric tests
  manifest-last commit
  interrupted generation ignored
  stale sidecar rebuilt lazily
  exact / word / trigram fixture hits
  vector fallback metadata
  graph sidecar does not mutate truth

Retrieval tests
  FTS-only
  vector-only
  hybrid
  metadata prefilter
  exact/code-aware
  missing vector table fallback
  backend mismatch fallback

Lifecycle tests
  access signal writeback
  tier downgrade candidate
  deep recall includes archive
  default wake excludes archive

Distribution tests
  wheel import
  pure-Python fallback
  doctor platform report
```

Regression rule：任何 v3.8 search/wake/candidate behavior 被 v4.0 改动影响，都必须加 regression test。

## Benchmark Gates

v4.0 不以单项性能数字宣布胜利。至少同时看：

| 维度 | Gate |
|---|---|
| Ingest throughput | 100k corpus bulk ingest 明显优于 v3.8，且 checksum 一致 |
| Migration safety | dry-run / apply / export rollback logical checksum 全部一致 |
| Search latency | warm p95 不退化；first lazy sidecar load 单独记录 |
| Wake latency | L0-L2 assembly 不因 canonical store 增加不可解释开销 |
| Recall | FTS/vector/hybrid source-hit 不低于 v3.8 contract |
| Metadata filter | prefilter 后候选集缩小比例、latency、recall loss 都有 artifact |
| Index freshness | source fingerprint drift 后能 lazy rebuild；半写入 generation 不可见 |
| Memory | RSS、DB size、index size、sidecar size 有 artifact |
| Install friction | wheel install / import / doctor 有跨平台结果 |
| Reversibility | migrate + export rollback 通过 logical checksum |
| Token/output cost | context output tokens、truncation、drilldown、missed fusion opportunity 可观测 |

每个 benchmark artifact 必须包含：

```text
benchmark_id
dataset_id / dataset_hash
query_pack_id
commit
command
hardware / OS / Python / Rust wheel mode
cold_start / first_lazy_load / warm_run distinction
p50 / p95 / max
RSS / DB size / sidecar size
fallback fields
claim_readiness
```

没有 artifact，就不能把收益写进 README 或 release note。测试通过不是 benchmark；smoke 通过也不是
public claim。

## GStack Engineering Review Checklist

按 gstack eng review 的口径，v4.0 实现前后必须回答这些问题：

| 类别 | 问题 | v4.0 要求 |
|---|---|---|
| What already exists | v3.8 已有 FTS/vector/hybrid、benchmark matrix、candidate governance | 复用现有 contract，不重造用户入口 |
| NOT in scope | 通用 Agent 平台、默认 daemon、默认云服务、AI 自治改 truth | 明确写在 non-goals 并由测试锁住关键文案 |
| Failure modes | migration 损坏、sidecar 半写入、fallback 静默退化、benchmark false success | doctor、checksum、manifest-last、fallback metadata、artifact gate |
| Performance | Rust / sidecar 真的更快吗 | before/after benchmark + warm/cold 拆分 |
| Testability | 新能力怎么防漂移 | roadmap truth tests + contract tests + benchmark smoke + release gate |
| Parallelization | 哪些 workstream 可并行 | benchmark/schema/Rust/index/lifecycle/distribution 分 lane |

## 不在 v4.0 范围

| 不做 | 理由 |
|---|---|
| 一次性全量 Rust rewrite | 同时改语言、协议、发行、测试和用户入口，风险过大 |
| Rust MCP server 默认替换 Python MCP | 协议层先保持稳定；等 Rust core contract 稳定后再评估 |
| 默认切 Tantivy / LanceDB | 必须先有 benchmark artifact 和 fallback semantics |
| 默认上 reranker / query rewriting | 属于 v4.2 Retrieval Quality Pack，不该拖慢 v4.0 默认路径 |
| 默认 Planning Agent / SCA loop | 属于 v4.1 Context Sufficiency + Task-Aware Wake，v4.0 先打索引和 metadata 地基 |
| 默认后台 daemon | 项目边界不变；trigger 仍是 opt-in |
| AI 自治删除 confirmed truth | 违反 candidate / review / supersede / ledger |
| 云端索引或托管记忆 | 违反 local-first |
| 默认 embedding 模型更换 | 仍需 recall、latency、disk/cache、install friction 全部过 gate |

## 风险与缓解

| 风险 | 缓解 |
|---|---|
| Rust wheel 发布失败 | pure-Python fallback + doctor 明确 platform report |
| migration 损坏用户数据 | dry-run、backup、logical checksum、export rollback、默认不自动 apply |
| 双写期间 JSON/DB drift | checksum 比对、doctor drift hint、单向 canonical truth 决策 |
| sidecar 半写入被读到 | generation sidecars + manifest-last commits + startup cleanup |
| lazy sidecar 造成首查抖动 | benchmark 区分 first lazy load 和 warm query；doctor 可预热 |
| 新 backend recall 退化 | backend contract tests + v3.8 retrieval shootout baseline |
| Rust/Python schema 分裂 | JSON contract tests、golden fixtures、error mapping tests |
| 回答前质量门过早进默认路径 | v4.0 不抢跑；v4.1 已按 cheap classifier + budget + trace 的硬边界落地 |
| 性能 claim 过度营销 | public claim readiness gate；未 ready 不写 README |

## 并行实施建议

| Lane | 范围 | 依赖 |
|---|---|---|
| A | benchmark corpus、baseline report、claim gate | 无 |
| B | canonical SQLite schema、migration/export、doctor | A 的 corpus contract |
| C | Rust core crate、JSONL scanner、bulk index builder | B 的 schema contract |
| D | Local Memory Index Fabric、manifest、sidecars、SearchBackend conformance | A 的 retrieval baseline，部分依赖 C |
| E | lifecycle tiering、GC candidates、deep recall semantics | B 的 canonical fields |
| F | wheel/distribution/release gate | C 的 crate shape |
| G | v4.1 CorpusProfile / RetrievalPlan planning spec | D 的 metadata/index contract 稳定后启动 |

执行顺序：先 A + B；B 稳定后 C + E 可并行；D 在 A/C 后进入；F 贯穿但不能最后才补。
G 是 v4.1 预研，不阻塞 v4.0 release。

## 交付判定

v4.0 只有在以下条件满足时才算完成：

1. 老用户不迁移也能继续 wake/search。
2. dry-run migration 可解释、可复现、可回滚。
3. canonical store 通过 v3.8 行为回归。
4. Local Memory Index Fabric 支持 manifest-last、generation sidecars、lazy rebuild 和 fallback metadata。
5. Rust core 在支持平台有 wheel，非支持平台有清晰 fallback。
6. benchmark report 同时覆盖性能、recall、memory、disk、install friction、migration safety 和 index freshness。
7. README / roadmap-status 只声明已被 artifact 支撑的收益。
8. v4.1 context sufficiency / task-aware wake / local routing 的接口可以依赖 v4.0 contract，但不作为 v4.0 发布条件。

## 短结论

v4.0 是 harness-mem 的存储、索引和执行内核换挡，不是产品入口换挡。

Python 继续负责 AI 协作层，Rust 负责确定性的本地数据工作。SQLite 继续做 local-first canonical
基础，JSON 退到 snapshot 和兼容层。Local Memory Index Fabric 借鉴 `codedb-mcp` 的 generation
sidecars、compact binary indexes、lazy rebuild 和 manifest-last commit 纪律，但不把 generated layer
当 truth。v4.1 已在这个地基上做 context sufficiency、task-aware wake 和 local routing。最重要的是：每个功能都要能测试、
能 benchmark、能回滚；记忆可以自动整理，不能静默篡改。
