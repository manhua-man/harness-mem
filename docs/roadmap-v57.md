# Roadmap: harness-mem v5.7

> 状态：**已发布**（随 v5.8.0 release train 收口；基线版本 v5.6.0；v5.7.0-v5.7.3 主路径 temporal metadata、
> temporal intent hint、`wake` / `search_memory` / `get_project_status`
> `temporal_query` drilldown、generated claim drilldown 已接线并通过 focused tests；
> temporal product eval 已接入 `benchmark_matrix_report`，由既有 accepted
> `temporal_product_query` artifact 支撑）。
>
> 主题：**Temporal-aware Retrieval + Claims Drilldown**。把 v3.3 `temporal_query` 与 v3.2
> generated claims / staleness 接到 v5.2 `SearchBackend` 主链路与 v5.3 DX drilldown 面；
> 不新建 wiki 产品、不引入图数据库、不放宽 truth governance。

---

## 一句话

v5.7 不是重做时序引擎，而是把**已经存在的** temporal read model 和 generated claim
staleness **接到用户每天会用的** `search_memory` / `wake` 主路径上，让 Agent 默认看到
current truth，并在需要时一键钻到 `temporal_query` 或 claim source。

```text
v5.6 现状
  search / wake  → SearchBackend（默认 current truth；include_history 需显式）
  temporal_query → 独立 MCP（current / history / as_of / supersede timeline）
  knowledge_cache → staleness 已映射 valid_to，但 compact / drilldown 未统一接到主路径

v5.7 目标
  search / wake  → 默认 current + temporal_scope 元数据 + 可解释 historical 提示
  drilldown      → stale / superseded / as_of 意图 → temporal_query / source ids
  generated      → Trust / Drilldown 接到同一 drilldown contract（仍非 truth）
```

## 为什么现在做

v5.6 已把日常入口（status / wake / search）、维护摘要、outcome loop 和跨客户端
field-test 收口。下一瓶颈不是「有没有 temporal API」，而是：

| 痛点 | v5.6 现状 | v5.7 目标 |
|---|---|---|
| 主路径与专用 API 分裂 | `temporal_query` 能力完整，但 `wake` / `search_memory` 默认路径不引导时序钻取 | 主路径返回 `temporal_scope`、historical 标记与 drilldown 到 `temporal_query` |
| LongMemEval 弱维 | `temporal-reasoning`、`multi-session` 仍低于 retrieval 总线 | 接线后单独报告两维，不回退 `knowledge-update` / `single-session-*` |
| Generated claims 孤岛 | `knowledge_cache` 已有 `staleness`（含 `valid_to`），compact 有 Trust / Drilldown | stale / historical claim 与 confirmed truth 共用 drilldown hints 形状 |
| DX 已就绪 | v5.3 有 `next_actions` / `why_this_result` / `drilldown_hints` | 把时序类 hint 填实，而不是只留占位字段 |

gstack 审阅结论：**⑥⑦ 强关联，但只需一条「接线切片」**；不做 meta-kb 级 wiki、不做常驻
daemon、不在 v5.7 解锁全局 token saving claim。

## 产品原则

1. **Reuse, don't rebuild**：复用 `read_api` temporal projection、`temporal_query`、
   `knowledge_cache` staleness；不新建 graph DB 或 ontology 学习。
2. **Current by default**：默认检索面仍是 current truth；historical / as_of 必须显式参数
   或 drilldown，不能静默把过期事实当当前事实。
3. **Read-side only**：v5.7 不改写 confirmed truth；supersede / candidate 规则不变。
4. **Generated ≠ truth**：generated compact / claim drilldown 仍不进默认 wake truth surface。
5. **Explainable drilldown**：每条 temporal / stale hint 带 `why`、`source_ids`、建议的
   MCP 工具与参数草图（与 v5.3 drilldown contract 一致）。
6. **Dimension-aware eval**：验收必须贴 LongMemEval 分维表，不接受单一总分掩盖回退。

## 边界（明确不做）

| 不做 | 理由 |
|---|---|
| llm_wiki / meta-kb 级 wiki 产品 | 产品边界在 `reference-projects.md`；hm 只做 bridge |
| Neo4j / 完整 KG 引擎 | v3.3 / v1.7 已否决；多跳图仍后置 |
| always-on daemon / 默认 scheduler | v5.4 / roadmap-v24 纪律不变 |
| outcome-aware decay / 自动 archive | v5.5 已限定为 signal-only；v5.2 明确不做 |
| 全局 token/cost saving 公开 claim | `token_cost_saving.ready=false` 留到 v5.9+ 证据线 |
| Tantivy / LanceDB / 新 SearchBackend | v5.2 默认内核切换已完成；v5.7 不扩后端矩阵 |
| 外部 code graph 并进本体 | code-intel 联邦已在 v4.3；memory 与 code graph 并列 |

## 目标架构

```text
┌─────────────────────────────────────────────────────────────┐
│ MCP: wake / search_memory / get_project_status               │
│      temporal_query (existing)                               │
└────────────────────────────┬────────────────────────────────┘
                             │
┌────────────────────────────▼────────────────────────────────┐
│ SearchBackend + task_context_runtime (v5.2 mainline)           │
│  + temporal_scope metadata on hits                             │
│  + historical_match / superseded hints                       │
│  + drilldown_hints → temporal_query params / source ids        │
└────────────────────────────┬────────────────────────────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
 read_api temporal    knowledge_cache      v5.3 DX layer
 projection (v3.3)    staleness (v3.2)     next_actions / why
```

## v5.7.0：Temporal Scope on Mainline Retrieval

**用户故事**：Agent 用 `search_memory` 或 `wake` 时，能一眼看出每条结果是 current、
historical 还是被 supersede，而不必先猜要不要开 `include_history`。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `temporal_scope` on hits | `SearchBackendResponse` / MCP payload 为 structured truth hits 附带 `temporal_scope`：`current` / `historical` / `superseded`（或等价枚举） |
| P0 | default current filter | 未传 `include_history` 时行为与 v5.6 一致：不返回 historical structured truth |
| P0 | explicit history path | `include_history=true` 时 hits 带 `is_historical` 与 `valid_to`（或等价字段），且 `why_this_result` 说明为何包含历史 |
| P1 | query intent hint | 检测到明显 as_of /「当时」「以前」类 query 时，`next_actions` 建议 `temporal_query`（mode=as_of），不自动执行 |
| P1 | task_context parity | `context_plan` / `wake_packet` 与 `search_memory` 共用同一 temporal metadata 形状 |

**实现锚点（已有代码，v5.7 接线）**：

- `harness_mem.search.backend.SearchFilters.include_history`
- `harness_mem.read_api` 的 `is_historical` / valid_to 投影
- `harness_mem.task_context_runtime` 的 drilldown 合并逻辑

## v5.7.1：Temporal Drilldown Contract

**用户故事**：当结果过期、被取代或用户问历史事实时，Agent 能从 `drilldown_hints` 直接
跳到 `temporal_query` 或 source observation，而不自己拼参数。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | supersede drilldown | 对 superseded hit，`drilldown_hints` 含 `temporal_query` 建议（subject/predicate/entry id + mode） |
| P0 | timeline drilldown | 同一 subject/predicate 多条记录时，hint 指向 `mode=history` 或 timeline 字段 |
| P0 | as_of abstention path | 主路径证据不足时，hint 建议 `temporal_query` + `abstention` 语义，不编造当前状态 |
| P1 | wake packet integration | `wake` 返回的 `next_actions` 在 temporal 场景下与 `search_memory` 一致 |
| P1 | `get_project_status` copy | status 面增加一句「时序钻取请用 temporal_query」仅在有 historical/supersede 候选时出现 |

**与 v3.3 关系**：不扩展 `temporal_query` 的 graph 能力；只增加**谁调用它、用什么参数**
的可发现性。

## v5.7.2：Generated Claims Staleness Drilldown

**用户故事**：compact / generated claim 标记为 stale 或 historical 时，Agent 能回到
confirmed source 或 `temporal_query`，而不是把 generated 文本当真理。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | unified staleness shape | **已发布**：compact generated claim `drilldown_pointers` 带 `temporal_scope` / `valid_to`，与 structured hit 语义对齐 |
| P0 | claim → source drilldown | **已发布**：truth-backed claim drilldown 带 `source_record_id`、`source_ids` 与 `temporal_query` 参数草图 |
| P1 | compact wake opt-in | **已发布**：opt-in compact payload 的 Drilldown 指针使用 v5.7 drilldown contract（v3.6 延伸） |
| P1 | invalid citation unchanged | hash drift / invalid citation 仍进 generated review queue，不进入 default wake |

**与 v3.2 / v3.6 关系**：compiler 与 citation gate 不重写；只统一 **drilldown 出口**。

## v5.7.3：Temporal Product Eval + Regression Gate

**用户故事**：maintainer 能证明 v5.7 改善了时序产品体验，且没有牺牲其它 LongMemEval 维度。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | product query fixtures | 新增 fixture：current-only default、explicit history、as_of 建议、supersede drilldown |
| P0 | LongMemEval dimension report | 发布前对比 v5.6 baseline：`temporal-reasoning`、`multi-session` 不回退；贴六维表 |
| P0 | regression gate | **已接入**：`benchmark_matrix_report` 登记 `temporal_query -> temporal_product_query`，release snapshot 已含 accepted temporal product artifact |
| P1 | MCP smoke extension | `tests/mcp/test_smoke.py` 覆盖 wake/search drilldown → temporal_query 参数形状 |
| P2 | memory_eval_matrix hook | 若已有 temporal 行为维，填入 v5.7 接线项（不阻塞主发布） |

**公开 claim 边界**：

- 可以说：默认检索面强调 current truth；historical / as_of 有显式路径与 drilldown。
- 不能说：全面达到 hindsight / mempalace 自报 recall；不能说 wiki 产品化完成。

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- Focused tests（新增或扩展）：
  - search/wake default current vs `include_history`
  - `temporal_scope` / drilldown_hints 形状
  - supersede / as_of drilldown 建议
  - generated claim staleness drilldown
  - LongMemEval 分维不回退（相对 v5.6 登记 run）
- 文档：
  - `docs/roadmap-status.md` 发版锚点更新
  - `CHANGELOG.md` v5.8.0 段（v5.7-v5.8 同一 release train）
  - 可选：`how-it-works-visual-guide.md` 增一页时序钻取（非阻塞）

## 与后续版本的关系

| 版本 | 主题 | 与 v5.7 关系 |
|---|---|---|
| **v5.7** | Temporal-aware retrieval + claims drilldown | 本文件 |
| v5.8 | Guided maintenance profiles | 见 [`roadmap-v58.md`](./roadmap-v58.md) |
| v5.9 | Bounded claims + quality profile（可选） | 见 [`roadmap-v59.md`](./roadmap-v59.md) |
| v6.0 | **暂定** Mature Runtime | 见 `roadmap-status.md`；设计稿未开 |

## 参考文档

| 文档 | 用途 |
|---|---|
| [`roadmap-v33.md`](./roadmap-v33.md) | `temporal_query` 原始契约 |
| [`roadmap-v26.md`](./roadmap-v26.md) / [`roadmap-v32.md`](./roadmap-v32.md) | wiki bridge / generated compiler |
| [`roadmap-v40.md`](./roadmap-v40.md) | SearchBackend mainline（v5.2） |
| [`reference-comparison-matrix.md`](./reference-comparison-matrix.md) | ⑥⑦ 维度差距与 deliberately-not 边界 |
| [`benchmark/longmemeval-five-dimensions.md`](./benchmark/longmemeval-five-dimensions.md) | 分维验收口径 |
