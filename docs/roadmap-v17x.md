# Roadmap: harness-mem v1.7.x

> 状态：v1.7.0 - v1.7.3 已完成实现并通过 full `pytest / ruff / mypy` release gate。v1.7.3 的收口点是 verbatim exact evidence search：只索引 `Observation.raw_content`，用于证据定位，不替代 FTS5 / vector search。
>
> 配合 [`roadmap-v16x.md`](./roadmap-v16x.md)、[`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 与 [`roadmap-vision-v19-memory-metabolism.md`](./roadmap-vision-v19-memory-metabolism.md) 阅读：v1.7 的职责是让 memory runtime 长出"时间感"，不是提前做 Dream，也不是提前做 procedural memory。

---

## v1.7 的一句话目标

让 `harness-mem` 能区分：

- **当前有效的事实**
- **历史上曾经有效、现在已被替代的事实**
- **AI 建议替代旧事实，但仍在等待人类审核的候选**

这一步的产品价值很直接：AI 不应该因为旧 session 里有一句"这个项目用 Vue"就覆盖今天已经确认的"这个项目改 React"；但用户仍然应该能追溯旧事实、来源证据和替代链。

---

## v1.6 -> v1.7 的前置门槛

v1.7 不应该在 v1.6.2 半截时开工。先收口这些门槛：

| 门槛 | 判定 |
|---|---|
| persistent vector read path | `HybridSearchLayer` 读取 `vec_embeddings`，不再对候选池热路径 encode |
| embedding shootout | `docs/benchmark/v162-embedding-shootout.md` 落盘，默认模型按规则拍板 |
| release gate | `python -m pytest -q`、`python -m ruff check .`、`python -m mypy harness_mem` 全绿 |
| docs truth | `CHANGELOG.md`、`docs/roadmap-v16x.md`、`docs/README.md` 反映 v1.6.2 实际状态 |

---

## 用户视角故事线

| 切片 | 用户能感受到什么 |
|---|---|
| **v1.7.0** | search / wake 默认只拿"当前有效"的结构化记忆；需要时可以显式查历史 |
| **v1.7.1** | 新规则和旧规则冲突时，AI 不会直接改 truth，而是生成 supersede 候选让人确认 |
| **v1.7.2** | AI 能沿关系链解释"为什么这条规则现在有效"，并能把相对时间问题收窄到更准的时间窗口 |
| **v1.7.3** | AI 能用 regex / exact search 快速定位原始 session 证据，不再靠全库扫 `Observation.raw_content` |

---

## 切片之间的依赖向前推

| 切片 | 价值 | 为什么必须先做它 |
|---|---|---|
| v1.7.0 | temporal schema + current/history read contract | 没有 `valid_from / valid_to / recorded_at`，后面的 supersede 只能靠状态字符串硬凑 |
| v1.7.1 | supersede candidate loop | 没有审核闭环就做图查询，会把新旧冲突一起放大 |
| v1.7.2 | temporal retrieval + bounded graph query | 只有旧事实能被正确下沉后，多跳关系和时间窗口才不会把 stale truth 注入 wake |
| v1.7.3 | verbatim exact evidence search | 时间和 supersede 链稳定后，再增强证据定位；避免把 regex 索引误当成 truth 层 |

---

## 已决策

### 决策 1：mark-not-delete

**结论**：v1.7 只标记旧事实失效，不物理删除 truth。

- 新事实确认后，旧事实设置 `valid_to=<confirm_time>`
- 旧事实保留 JSON blob、SQLite row、provenance、source ids
- 默认 search / wake 不返回失效事实
- 显式 `history=true` / `--include-history` 才返回历史事实

理由：`harness-mem` 的护城河是 auditable memory runtime。历史不该消失。

### 决策 2：先做最小 bi-temporal，不做完整 KG 引擎

**结论**：v1.7 只引入本仓需要的最小时间模型：

- `valid_from`
- `valid_to`
- `recorded_at`
- `supersedes`
- `superseded_by`

不引入 Neo4j、专用图数据库、自动 ontology 学习。

### 决策 3：graph query 限制跳数和预算

**结论**：关系图查询保留 SQLite 单文件，用 recursive CTE 或内存 BFS 实现，默认最大跳数 `2`，硬上限 `3`。

理由：图查询是为了解释和召回，不是为了把 harness-mem 变成知识图谱平台。

---

## v1.7.0：Temporal schema + current/history reads

**用户故事**：我搜索项目规则时，默认看到当前有效规则；如果我想追溯历史，可以显式打开 history。

**前置基线**：

- v1.6.2 final 的 LongMemEval 六维表
- `temporal-reasoning` 当前锚点：v1.6.0 hybrid real `0.915`
- 当前结构化 truth schema：`MemoryEntry / RelationFact / ConfirmedRule`

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 给 truth-like structured entities 增加时间字段：`MemoryEntry / RelationFact / ConfirmedRule` 增加 `valid_from / valid_to / recorded_at / supersedes / superseded_by` | schema round-trip 测试覆盖新字段；老 JSON 缺字段可加载 |
| P0 | SQLite migration：`memory_entries / relation_facts / confirmed_rules` 增加对应列 | 旧库打开自动迁移；迁移后索引列可用于 WHERE 过滤 |
| P0 | 默认 current-only：`list / search / wake` 默认过滤 `valid_to IS NULL OR valid_to > now` | 单测覆盖 stale fact 不出现在默认 search / wake |
| P0 | history 显式入口：CLI / MCP / REST 增加 `include_history` 或等价参数 | 默认行为不变；显式 history 返回当前 + 历史，并标注 validity window |
| P1 | Backfill 命令：`harness-mem maintenance assign-temporal-fields --dry-run / --apply` | `valid_from` 从 `created_at / confirmed_at` 派生；连续 apply 后 dry-run 为 0 |
| P1 | 输出可观测性：search / wake 中历史事实显示 `[historical valid_to=...]` | CLI 测试断言历史标注存在 |

**不列入 v1.7.0**：

- 自动 conflict detection
- 自动 supersede
- 多跳图查询
- procedural memory

---

## v1.7.1：Supersede candidate loop + conflict detection

**用户故事**：AI 发现新规则可能替代旧规则时，只提出建议；我确认后，新规则生效，旧规则自动变成历史。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 新增 `SupersedeCandidate` schema：`project_name / target_type / target_id / replacement_type / replacement_id / reason / evidence / confidence / status` | schema round-trip + storage 测试 |
| P0 | MCP 工具：`suggest_supersede / confirm_supersede / reject_supersede / list_candidates` 支持 supersede 类型 | MCP schema 测试；确认后旧 truth `valid_to` 被设置 |
| P0 | CLI 兜底：`harness-mem candidates` 显示 supersede；`confirm <id>` / `reject <id>` 可处理 | CLI 测试覆盖 confirm/reject |
| P0 | `DistillContext.compare(...)` 扩展为可生成 supersede 候选输入，但仍不能直接 mutate truth | 只读边界测试继续防止 `delete / update / purge` 泄漏 |
| P1 | 冲突检测第一版：同项目、同 trigger / relation_type / entity pair 的新旧 fact 进入 conflict review | fixture 覆盖 Vue -> React、旧路径 -> 新路径、旧 API -> 新 API |
| P1 | Supersede event log：记录谁确认、何时确认、被替代链路 | events.log 测试覆盖 |

**不列入 v1.7.1**：

- AI 自动确认 supersede
- 物理删除旧 truth
- 自动合并 ontology

---

## v1.7.2：Temporal retrieval + bounded relation graph

**用户故事**：我问"两个月前那个决定是什么"或"这个模块为什么要这样改"时，系统能先用时间窗口和关系链缩小候选，再把来源证据给出来。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | Temporal query helper：从 query 中识别简单相对时间窗口（如 `yesterday / last week / two months ago`），转成 observation/session 时间过滤 | 单测覆盖相对时间 -> UTC window；无法解析时回退普通 search |
| P0 | `search_memory` 增加 `time_window` 内部参数，先作用于 observations，再作用于 structured truth validity | temporal fixture 中候选数量下降且目标仍在 top-k |
| P0 | Relation graph traversal：`RelationFact` current-only 默认，支持 `source_entity / relation_type / max_depth` 查询路径 | max_depth 默认 2，硬上限 3；返回 path + evidence |
| P1 | MCP / CLI：新增 `trace-relations` 或等价工具，输出受限关系链 | CLI/MCP 测试覆盖单跳、二跳、超过深度拒绝 |
| P1 | wake relation summary：只把高置信、当前有效、短链路关系放入 wake | wake 输出预算不膨胀；stale relation 不注入 |
| P2 | LongMemEval temporal probe：新增 v1.7 temporal slice 报告，重点看 `temporal-reasoning` 和 stale-injection fixture | 文档写入 `docs/benchmark/v170-temporal-baseline.md` 或后续 v172 报告 |

---

## v1.7.3：Verbatim exact evidence search

**用户故事**：AI 需要找某个错误码、函数名、路径片段、日志模式或正则形态时，可以先用本地 n-gram 索引缩小 observation 候选，再对候选原文做真实 regex 验证，而不是全库扫描或误用 embedding。

**参考机制**：Cursor fast regex search 的核心启发是"索引裁剪候选 -> 精确验证"。本仓只吸收机制，不做通用代码搜索产品。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | 新增 verbatim exact index：为 `Observation.raw_content` 建最小 trigram 倒排表（`ngram -> observation_id`），只索引 observations，不索引 workspace 文件 | ingest / save observation 后同步写索引；旧库缺表时可自动创建 |
| P0 | 新增查询路径：`regex_search_observations(pattern, project_name, limit)`，先用 trigram 裁剪候选，再对 JSON blob 原文运行 Python `re` 验证 | 单测覆盖 regex 命中、regex 未命中、非法 regex、CJK/ASCII 混排 |
| P0 | MCP / CLI 入口：提供 `search-raw --regex <pattern>` 或等价工具，返回 observation id、session id、短上下文 snippet | CLI/MCP 测试覆盖 project scope、limit、snippet 输出 |
| P1 | 新鲜度保证：`ingest` 新 observation 后 exact index 同步更新；`doctor` 能检测 index 缺失或陈旧并提示 rebuild | doctor 输出明确修复命令；rebuild 后候选数量恢复 |
| P1 | rebuild 命令：`harness-mem maintenance rebuild-verbatim-index --project <name>` | 大库可增量输出进度；重复运行幂等 |
| P2 | Sparse n-gram spike：当普通 trigram posting list 过大时，评估 deterministic sparse n-gram，写 benchmark 报告再决定是否替换 | 报告比较 index size、query latency、candidate count、false-positive rate |

**不列入 v1.7.3**：

- workspace 代码文件搜索。代码搜索继续交给 `rg` / IDE / 专用 code index。
- 替代 FTS5 或 vector search。exact index 只服务"证据定位"，不是语义召回。
- 一开始就上 sparse n-gram。先用 trigram spike 拿真实数据，再决定是否复杂化。

---

## 成功判定

v1.7.x 不是为了把总 R@5 硬推到某个漂亮数字。成功标准是：

| 维度 | 判定 |
|---|---|
| stale injection | 旧 truth 被 supersede 后，不再默认进入 search / wake |
| auditability | 历史 truth 可查，provenance 不丢，supersede 链可解释 |
| temporal retrieval | 相对时间 fixture 能明显缩小候选窗口，并保持目标可召回 |
| graph retrieval | 多跳关系有深度上限、预算上限、证据输出 |
| exact evidence search | regex / exact pattern 能快速定位原始 observation，且必须二次验证原文 |
| regression | v1.6.2 final 六维 LongMemEval 不出现无法解释的回退 |

---

## OpenSpec 拆分建议

| 变更 | 目录建议 |
|---|---|
| v1.7.0 temporal schema | `openspec/changes/v170-temporal-schema-current-history/` |
| v1.7.1 supersede loop | `openspec/changes/v171-supersede-candidate-loop/` |
| v1.7.2 graph retrieval | `openspec/changes/v172-temporal-graph-retrieval/` |
| v1.7.3 exact evidence search | `openspec/changes/v173-verbatim-exact-evidence-search/` |

每个 change 至少覆盖：

- `proposal.md`
- `design.md`
- `tasks.md`
- `specs/structured-memory/spec.md`
- 涉及 CLI/MCP/REST 时同步写 `specs/cli`、`specs/mcp`、`specs/api`

---

## 与 v1.8 / v1.9 的边界

| 方向 | 放在哪里 | 原因 |
|---|---|---|
| procedural memory / Skill schema | v1.8 | 需要 v1.7 的 semantic truth 和 supersede 链作为地基 |
| Dream / Memory Metabolism | v1.9 | 需要 v1.6 分型预算、v1.7 时间感、v1.8 procedural layer 都完成 |
| 自动删 truth | 不做 | 和 auditable memory runtime 冲突 |
| 常驻 daemon / proactive assistant | 不做 | 超出 memory layer |
| 完整 ontology 演化 | v2.0 以后再评估 | 当前目标是 local-first 可解释最小子集 |
| 通用代码搜索引擎 | 不做 | v1.7.3 只索引 harness-mem observations，代码搜索继续交给专用工具 |

---

## 第一批实施文件

v1.7.0 启动时优先看这些文件：

- `harness_mem/core/schemas/memory_entry.py`
- `harness_mem/core/schemas/relation_fact.py`
- `harness_mem/core/schemas/confirmed_rule.py`
- `harness_mem/storage/sqlite_index.py`
- `harness_mem/storage/local_structured_store.py`
- `harness_mem/storage/local_verbatim_store.py`
- `harness_mem/read_api.py`
- `harness_mem/commands/search.py`
- `harness_mem/commands/wake.py`
- `harness_mem/mcp/server.py`
- `harness_mem/api/server.py`

优先测试：

- `tests/storage/`
- `tests/cli/test_search_and_wake.py`
- `tests/test_memory_type_search_payload.py`
- 新增 `tests/temporal/`
- 新增 `tests/supersede/`
- 新增 `tests/verbatim_exact/`
