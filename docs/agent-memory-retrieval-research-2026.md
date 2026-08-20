# Agent Memory & Retrieval 调研纪要（2026）

**版本：** 1.0  
**日期：** 2026-06-28  
**范围：** harness-mem 对外产品方向（Truth / retrieval / maintenance / recall contract / 边界）+ 检索内核改进（不换 SearchFacade / SQLite）  
**方法：** arXiv API、主要 AI lab 官方研究（OpenAI / Anthropic / Google / DeepSeek / xAI）、官方产品文档、开源实现对照；通用 WebSearch 仅作兜底  
**调研 skill：** `~/.grok/skills/local-first-retrieval-research/SKILL.md`（含 lab 检索配方）

> 本文档汇总两轮调研结论，供产品叙事、架构决策和 P0–P3 改进排期使用。  
> 版本路线见 [`roadmap.md`](./roadmap.md)；recall 契约见 [`recall-audit.md`](./recall-audit.md)。

---

## 目录

1. [执行摘要](#1-执行摘要)
2. [2026 前沿共识](#2-2026-前沿共识)
3. [对标项目](#3-对标项目)
4. [学术论文与 benchmark](#4-学术论文与-benchmark)
5. [harness-mem 对齐判断](#5-harness-mem-对齐判断)
6. [改进方案（P0–P3）](#6-改进方案-p0p3)
7. [对外产品应继续加厚什么](#7-对外产品应继续加厚什么)
8. [内核 vs 产品：两层分工](#8-内核-vs-产品两层分工)
9. [落地路径与代码锚点](#9-落地路径与代码锚点)
10. [Adopt / Defer / Reject 矩阵](#10-adopt--defer--reject-矩阵)
11. [来源索引](#11-来源索引)
12. [修订记录](#12-修订记录)

---

## 1. 执行摘要

**主判断（两轮调研一致）：**

- **不要换搜索引擎**，不要上 store v3，不要把 Tantivy/LanceDB/完整图库作为默认路径。
- **先做 retrieval-isolated benchmark**（测「检索对了没」，不是 LoCoMo 答题分），再在小步上改 hybrid 栈。
- **对外产品**继续加厚 core loop：`wake → search → distill → review → dream`，`autopilot_search_tick` 负责任务态检索调度，`/hm:review` 是 audit inbox，dream 默认维护、recall contract、单 MCP 公开面不变。
- **2026 前沿**从「embedding-first + chat QA benchmark」转向 **agent-native memory = 数据管理系统**：canonical truth、filter-first retrieval、localized maintenance、可审计边界。

**一句话：** 借鉴 Mem0/Zep 的 retrieval quality 思路 + sqlite-vec/vstash 的 local-first 实现 + Tenure/MemoryData 的评测与 Truth 结构；Rust 只做 optional 热点加速。

---

## 2. 2026 前沿共识

[MemoryData（arXiv:2606.24775）](https://arxiv.org/abs/2606.24775)（2026-06-23）将 agent memory 拆为四模块：

```text
representation & storage  →  持久表示 + canonical 状态
extraction                  →  从对话/证据写入结构化记忆
retrieval & routing         →  按需检索与路由
maintenance                 →  合并、失效、压缩、生命周期治理
```

**实证结论：**

- 没有单一架构通吃所有 workload；效果取决于 **memory 结构与瓶颈是否对齐**。
- **Localized maintenance** 比全局重组更省成本（与 harness-mem dream + ledger 方向一致）。
- 现有评测多用端到端任务指标（F1/BLEU），把系统当黑盒，**检索精度、更新正确性、隔离、成本** 测量不足。

[Tenure / PrecisionMemBench（arXiv:2605.11325）](https://arxiv.org/abs/2605.11325)（2026-05）进一步指出：

- LoCoMo 等测的是「模型答对了没」，不是「memory 检索对了没」。
- 返回整个 belief store 可得 recall=1.0，仍能通过 answer-quality 评测。
- 领域语料上 **纯 cosine similarity precision 约 0.05–0.08**；换 20× 规模 embedding 无法根治。
- 需要 **retrieval-isolated** benchmark：`mustExclude`、`scope`、`supersession` 等硬断言。

---

## 3. 对标项目

### 3.1 Mem0

**来源：** [Search 文档](https://docs.mem0.ai/core-concepts/memory-operations/search)、[AI Memory Benchmarks 2026](https://mem0.ai/blog/ai-memory-benchmarks-in-2026)、[State of AI Agent Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)

**管线：** query processing → vector search → filters/rerank → metadata delivery

**2026 算法要点：**

- Multi-signal retrieval：semantic + BM25 + **entity boost** 并行融合
- Platform v3 **Temporal Reasoning**（时间有效性）
- OSS `explain=True` 暴露 `score_details`（semantic、BM25、entity、threshold）
- **scope/filter 一等公民**：`user_id` 等硬过滤，防跨用户污染

**Benchmark 叙事：** LoCoMo、LongMemEval、BEAM——测 multi-session continuity，但应 **成对报 accuracy + token/latency**；不等于 retrieval precision。

**借鉴：** filter-first、explain 分项、entity boost、temporal。  
**不照搬：** 云托管全栈、大而全 CLI。

---

### 3.2 Zep / Graphiti

**来源：** [Searching the Graph](https://help.getzep.com/searching-the-graph)、[Observations](https://help.getzep.com/observations)

**检索：** semantic + BM25 + **RRF**；可选 BFS、MMR、`node_distance` reranker

**数据形状：**

- **Facts**：边级、带时间戳的细粒度声明
- **Observations**：跨实体、证据支撑的 durable 模式（自动派生、dedup、supersede 退休）
- **Auto search**：跨 edges/nodes/episodes/observations 并行检索 + cross-scope rerank，打包 `context` 块

**Temporal：** `valid_at` / `invalid_at` / `expired_at` 等 filter——**metadata 失效**，不是评分衰减

**借鉴：** relation/decision 的 graph boost 思路、observation 层、temporal invalidation、cross-scope 多样性  
**不适合现在：** 完整图数据库替换 SQLite runtime

---

### 3.3 Letta

**来源：** [Archival memory](https://docs.letta.com/guides/core-concepts/memory/archival-memory/)

**分层：**

- **Core memory blocks**：常驻上下文、频繁变更状态
- **Archival memory**：语义可搜 DB，**仅通过 tool 按需查询**，不塞进 context window

**借鉴：** harness-mem 的 wake（紧凑 brief）+ search（按需深查）分层  
**产品哲学：** 长期记忆不应默认全量注入 prompt

---

### 3.4 sqlite-vec

**来源：** [Hybrid search](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/)、[Metadata filtering](https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/)

**栈：** FTS5 + vector + RRF，单文件 SQLite，metadata 列预过滤

**判断：** 与 harness-mem 现状最接近的 **短期实现路径**；不必为 benchmark 未证明的瓶颈换引擎。

---

### 3.5 Tantivy

**来源：** [Tantivy](https://github.com/quickwit-oss/tantivy)

**定位：** Rust embedded 全文库，非产品层

**判断：** 仅当 SQLite FTS 在 scale benchmark 中确为瓶颈时，作为 **optional Rust 加速** 考虑；不作默认替换。

---

### 3.6 vstash（学术 + 同栈参考）

**来源：** [arXiv:2604.15484](https://arxiv.org/abs/2604.15484)（2026-04）

**栈：** sqlite-vec + FTS5 + RRF + adaptive per-query IDF weighting

**正面：**

- Adaptive RRF 在 BEIR 五数据集全涨（ArguAna 最长 query +21.4%）
- Vector distance 作 relevance/confidence signal（优于 score spread）
- Disagreement-mined embedding 微调（无标注 hard negatives）
- 50K chunks 中位延迟 ~20.9ms

**负面结果（重要）：**

- post-RRF 的 frequency+decay、history boost、**cross-encoder rerank** 均未提升 NDCG

---

### 3.7 Tenure（2026 前沿对照）

**来源：** [arXiv:2605.11325](https://arxiv.org/abs/2605.11325)、[precisionmembench](https://github.com/tenurehq/precisionmembench)

**主张：** precision-first、structured belief、hard scope isolation、multi-path BM25（analyzer asymmetry + alias boost）

**Benchmark：** 89 cases，scope / mutation / isolation / session drift；**不经过 LLM** 评 retrieval precision

**与 harness-mem：** 方法论高度相关（Truth canonical、project isolation、supersede）；纯 BM25 路线与现有 hybrid 栈不同，宜 **借鉴评测与 Truth 结构**，非替换 SearchFacade。

---

## 4. 学术论文与 benchmark

| ID / 名称 | 日期 | 核心贡献 | 对 harness-mem |
|-----------|------|----------|----------------|
| [2606.24775](https://arxiv.org/abs/2606.24775) MemoryData | 2026-06 | 四模块框架；12 系统横评；localized maintenance | 产品/module 对齐检查清单 |
| [2605.11325](https://arxiv.org/abs/2605.11325) PrecisionMemBench | 2026-05 | Retrieval-isolated precision；belief schema | **P0 golden 设计主参考** |
| [2604.15484](https://arxiv.org/abs/2604.15484) vstash | 2026-04 | Adaptive RRF；distance confidence；hybrid 负面结果 | **P1 算法主参考**（同 SQLite 栈） |
| [2210.11934](https://arxiv.org/abs/2210.11934) Fusion analysis | 2022 | RRF vs convex combination；RRF 参数敏感 | fusion 调参需 golden 分桶 |
| LoCoMo / LongMemEval / BEAM | 2024–2026 | Multi-session QA / 长程记忆 | **背景参考**；不作检索 KPI |

**评测原则（PrecisionMemBench + Mem0 2026 blog）：**

- 检索与生成 **拆开测**（unit test vs integration test）
- 指标 **成对报**：R@k / precision + p95 latency + leak rate + token budget
- 含 **abstention**、**vector_off**、**cross-project isolation**

---

## 5. harness-mem 对齐判断

### 5.1 已对齐（保持并写清文档）

| 维度 | 现状 |
|------|------|
| Core loop | `wake → search → distill → review → dream`（README、v4） |
| Truth | TruthStore canonical；CandidateStore + auto preflight；audit inbox + supersede / valid_to |
| 公开面 | 单 MCP public memory surface；dream 默认维护 + ledger + undo |
| Retrieval | SearchFacade 统一 `source_kind` / `truth_status` / `project_name` / temporal metadata |
| Recall | `search_memory` / `trace_relations` additive `recall` 对象 |
| 栈 | SQLite FTS + optional vector + weighted RRF；index 可重建 |
| 分层 | wake 紧凑上下文；search 按需检索（Letta 式） |

### 5.2 缺口（调研指向的改进区）

| 维度 | 缺口 |
|------|------|
| 评测 | 无 retrieval-isolated golden suite；RRF 权重未 grid search |
| Retrieval | Filter 可能偏 fusion 后；无 adaptive IDF；无 distance 置信度 tier |
| Truth | 缺 imperative `why_it_matters` 类字段；supersede 靠 filter 一致性需 golden 守 |
| Recall | steps/score 分项可加厚；与 Mem0 explain 对标不足 |
| 文档 | 对外「不宣称什么」需与调研结论同步；自动搜索调度与 audit inbox 口径需统一 |

---

## 6. 改进方案（P0–P3）

**原则：** 不换 SearchFacade / SQLite；先可测，再小步增强。

### P0 — 建立基准（1–2 周）

建 **retrieval-isolated** golden suite（约 80 条），**不经过 LLM** 打分。

| 类别 | 验证点 |
|------|--------|
| truth / observation / relation / decision | 各 `source_kind` 命中率 |
| project_isolation | 跨项目泄漏 = 0 |
| temporal_current / temporal_history | supersede 默认排除 vs 显式历史 |
| abstention | 不存在事实不误召回 |
| vector_off | FTS-only 退化可接受 |
| scale_smoke | 1k / 10k / 100k 延迟（可选） |

**指标成对报：** R@5 + p95；isolation leak rate；vector_off ΔnDCG@5。

**交付物：**

```text
code/tests/benchmarks/fixtures/search_minimal.py
code/tests/benchmarks/search_golden_queries.yaml
code/tests/benchmarks/test_search_golden.py
```

**复用：** `code/tests/test_storage_search_invariants.py` 的 fixture / `read_api.search_memory` 模式。

---

### P1 — 算法小步（benchmark 驱动，逐项 A/B）

| 顺序 | 项 | 参考 |
|------|-----|------|
| 1 | Filter 前置加固（project / truth_status / temporal_scope） | Mem0、Zep、Tenure |
| 2 | Adaptive IDF RRF | vstash 2604.15484 |
| 3 | Vector distance 置信度 / abstention tier | vstash |
| 4 | 同源 MMR 去重 | vstash、Zep MMR |
| 5 | 1-hop relation/decision boost | Zep BFS-lite |

**明确不做：** post-RRF 时间衰减评分、默认 cross-encoder rerank、换 Tantivy/LanceDB。

**主要改动文件：** `harness_mem/search/backend.py`、`harness_mem/search/hybrid_search.py`

---

### P2 — 可选 Rust 加速（P0 证明热点后）

仅当 benchmark 显示热点 >10% query 时间：

- RRF fusion 算术
- bulk derived-index row build
- benchmark runner 编排

**入口：** `harness_mem/rust_core.py` optional facade；**不替换** SQLite 查询层与 SearchFacade。

---

### P3 — 中期（golden 稳定后）

- Disagreement-mined embedding 微调（vstash）
- `retrieval_quality.py` 的 temporal/multi_hop fanout 用 golden 验证收益后再默认化

---

## 7. 对外产品应继续加厚什么

与 v4 §5、README 一致；调研补充如下。

### Truth

- 统一返回 `truth_status`、`temporal_scope`、`source_kind`
- supersede **存储层失效** + 默认 search 只 current
- review inbox / state audit 叙事写进对外文档
- 可选：truth 级 `why_it_matters`（wake 行为指令，非裸 fact）

### Retrieval（产品可见部分）

- recall contract 完善：`evidence` / `sources` / `steps` / `status`
- project isolation 结构化；`scope=all` 按 project 分组
- 空结果 / 低置信语义（`empty` / `low_confidence`）
- **不新增** MCP 工具；加厚 metadata 与 explain

### Maintenance

- 仅强化 **dream**：auto gate、ledger、undo
- dream 产出尽量走 supersede **audit**，非静默改 truth
- CLI 保持 operator console；purge/rebuild 不进 Daily workflow

### Recall contract

- 读路径解释层；**不**创建 candidate、不 confirm truth
- 与 `record_context_outcome` 形成闭环

### 对外宣称边界

**宣称：**

```text
local-first · auditable · wake→search→distill→review→dream
truth canonical · index rebuildable · vector optional
dream = default maintenance (ledger + undo)
single public MCP surface
```

**不宣称：** LoCoMo/BEAM 榜单、Mem0/Zep 全替代、graph DB 默认检索、MCP profile 选择、Rust 作为产品版本号。

---

## 8. 内核 vs 产品：两层分工

| 层 | 内容 | 用户可见 |
|----|------|----------|
| **产品** | Core loop、audit inbox、recall contract、dream、单 MCP 面、文档边界 | 是 |
| **内核** | Golden benchmark、adaptive RRF、filter 前置、distance tier、Rust 热点 | 否（仅改善 search 可信度） |

**规则：** 内核改进 **不扩展** public MCP tool 列表；不以 LoCoMo 答题分证明检索质量。

---

## 9. 落地路径与代码锚点

### 调用链

```text
MCP search_memory
  → harness_mem/mcp/tool_handlers.py
  → harness_mem/read_api.py::search_memory
  → harness_mem/search/backend.py::SearchFacade
  → HybridSearchLayer + sqlite_index (FTS + optional vector)
```

### 必读仓库文档（按顺序）

1. [`roadmap.md`](./roadmap.md)
2. [`recall-audit.md`](./recall-audit.md)
3. [`../README.md`](../README.md) Core Loop
4. [`../code/plugins/harness-mem/skills/harness-mem/SKILL.md`](../code/plugins/harness-mem/skills/harness-mem/SKILL.md)

### 必读代码

| 路径 | 作用 |
|------|------|
| `harness_mem/search/backend.py` | SearchFacade、filters、temporal、kind merge |
| `harness_mem/search/hybrid_search.py` | RRF + confidence exponent |
| `harness_mem/search/retrieval_quality.py` | bounded quality pack |
| `harness_mem/recall.py` | recall 构建 |
| `harness_mem/mcp/tool_specs.py` | PUBLIC_MCP_TOOL_NAMES |
| `code/tests/test_storage_search_invariants.py` | 不变量与 fixture 模式 |

### Golden case 最小 schema

```yaml
id: truth_hit_001
taxonomy: truth_hit
query: "..."
project: demo-project
mode: hybrid
vector_enabled: true
filters:
  scope: project
  truth_status: [accepted]
  include_history: false
expected:
  source_ids: [mem:...]
forbidden:
  source_ids: [mem:stale...]
  projects: [other-project]
assertions:
  - temporal_scope: current
  - cross_project_leak: false
```

---

## 10. Adopt / Defer / Reject 矩阵

| 想法 |  verdict | 说明 |
|------|----------|------|
| 保持 SearchFacade + SQLite | **ADOPT** | v4 不变量 |
| FTS5 + sqlite-vec + RRF | **ADOPT** | local-first 主路径 |
| PrecisionMemBench 式 golden | **ADOPT** | P0 |
| Filter 前置 | **ADOPT** | Mem0/Zep/Tenure |
| Adaptive IDF RRF | **ADOPT** | vstash；P1 |
| Vector distance 置信度 | **ADOPT** | vstash；P1 |
| 1-hop relation/decision boost | **ADOPT** | Zep-lite；P1 |
| Recall explain / steps | **ADOPT** | 产品面 |
| dream + ledger + undo | **KEEP** | 已对齐 MemoryData |
| why_it_matters 字段 | **DEFER** | Tenure；可选 |
| Disagreement embedding 微调 | **DEFER** | P3；需 golden |
| Convex combination fusion | **DEFER** | 需 golden 对比 |
| Tantivy 替换 FTS | **DEFER** | 仅 scale 证明瓶颈 |
| Cross-encoder rerank 默认 | **REJECT** | vstash 负面 |
| post-RRF temporal decay 评分 | **REJECT** | vstash 负面；用 filter |
| ColBERT / 图 DB 默认 | **REJECT** | 范围与成本 |
| LoCoMo F1 作检索 KPI | **REJECT** | PrecisionMemBench |
| store v3 / 换搜索引擎 | **REJECT** | 调研一致结论 |

---

## 11. 来源索引

### arXiv（优先核验）

```bash
curl "https://export.arxiv.org/api/query?id_list=2606.24775,2605.11325,2604.15484,2210.11934"
```

| ID | 标题 |
|----|------|
| 2606.24775 | Are We Ready For An Agent-Native Memory System? |
| 2605.11325 | Structured Belief State and PrecisionMemBench |
| 2604.15484 | vstash: Local-First Hybrid Retrieval with Adaptive Fusion |
| 2210.11934 | An Analysis of Fusion Functions for Hybrid Retrieval |

### 官方文档

| 来源 | URL |
|------|-----|
| Mem0 Search | https://docs.mem0.ai/core-concepts/memory-operations/search |
| Mem0 Benchmarks 2026 | https://mem0.ai/blog/ai-memory-benchmarks-in-2026 |
| Mem0 State 2026 | https://mem0.ai/blog/state-of-ai-agent-memory-2026 |
| Zep Graph Search | https://help.getzep.com/searching-the-graph |
| Zep Observations | https://help.getzep.com/observations |
| Letta Archival Memory | https://docs.letta.com/guides/core-concepts/memory/archival-memory/ |
| sqlite-vec hybrid | https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/ |
| sqlite-vec metadata | https://alexgarcia.xyz/blog/2024/sqlite-vec-metadata-release/ |
| Tantivy | https://github.com/quickwit-oss/tantivy |
| MemoryData code | https://github.com/OpenDataBox/MemoryData |
| PrecisionMemBench | https://github.com/tenurehq/precisionmembench |

### 主要 AI Lab 研究渠道（Tier 1b）

| Lab | 官方入口 | 记忆/检索相关主题 |
|-----|----------|-------------------|
| OpenAI | https://openai.com/research/ · https://developers.openai.com/cookbook/ | ChatGPT memory、Agents SDK context、workspace agents |
| Anthropic | https://www.anthropic.com/research · https://docs.anthropic.com | agentic 行为、长上下文、工具使用 |
| Google | https://research.google/blog/ · https://deepmind.google/research/ · https://ai.google.dev/gemini-api/docs/long-context | Titans/MIRAS、ReasoningBank、Gemini long context |
| DeepSeek | https://github.com/deepseek-ai · https://api-docs.deepseek.com | R/V 系列、Agent 能力、技术报告 |
| xAI | https://x.ai · https://docs.x.ai | Grok API/产品；公开论文较少，需 arXiv 交叉验证 |

Lab 博文若引用 arXiv，**两条都要记**（博文日期 + 论文 ID）。

### 通用调研 skill（用户级）

`~/.grok/skills/local-first-retrieval-research/SKILL.md` — arXiv + 五大 lab + vendor 的分层检索 workflow。

---

## 12. 修订记录

| 版本 | 日期 | 说明 |
|------|------|------|
| 1.0 | 2026-06-28 | 合并两轮调研：对标项目、vstash/Tenure/MemoryData、P0–P3、产品五柱、落地路径 |
