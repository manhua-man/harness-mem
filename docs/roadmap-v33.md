# Roadmap: harness-mem v3.3

> 状态：已发布，当前版本 3.3.3。
> 下方 `v3.3.1` 等小节是早期切片规划名；最终 temporal 能力已合并到
> v3.3.0 发布，公开 patch v3.3.1 / v3.3.2 / v3.3.3 用于 release CI compatibility fix。
>
> 主题：Temporal Query and Supersede Explainability。把 v1.7 temporal truth
> 从 schema 和 supersede 推进到可查询、可解释、可评测的时间事实读模型；多跳图只做后置验证，不作为主线门槛。

---

## 目标

v3.3 的目标是让 Agent 能回答“现在什么是真的、什么时候变的、为什么变的、历史上曾经怎样”。
必要功能是 temporal query 和 supersede explainability，不是完整知识图谱产品。

```text
confirmed truth + relation facts + supersede history
-> temporal read model
-> current / history / as_of query
-> supersede chain + timeline renderer
-> evidence-backed answer / abstention
```

参考线：

- `hypatia`：本地 triples、temporal ranges、FTS/vector hybrid。
- `Graphiti`：bi-temporal KG 和 update 语义。
- `mempalace`：SQLite temporal KG primitives。

### 当前实现（2026-06-07）

- MCP 新增 `temporal_query`：支持 `current`、`history`、`as_of`、valid-time /
  recorded-time range、truth_type、subject、predicate 和 substring query 过滤。
- `read_api` 新增 temporal read model：按需从 MemoryEntry、RelationFact、
  ConfirmedRule 重建统一 records，输出 valid_from、valid_to、recorded_at、
  source_ids、provenance、supersedes / superseded_by。
- current query 默认只返回当前有效 records；history query 返回 expired truth；
  as_of query 使用 `valid_from <= as_of < valid_to(or infinity)`。
- 查询结果返回同一 subject/predicate 的 timeline、supersede_chain 和
  explanation；无证据或调用方要求唯一当前事实但存在冲突时返回 abstention。
- Minimal relationship recall proof 继续复用 `trace_relations` 的 bounded depth
  语义；完整多跳图和完整 temporal LongMemEval 报告仍后置。

## 边界

- 不引入 Neo4j 或完整图数据库。
- 不自动学习 ontology。
- 不让 AI 自动改写 confirmed truth。
- 不把 generated wiki claim 直接并入 graph truth。
- 不把多跳 traversal 作为 v3.3 P0；先做 subject/predicate/time 维度的可解释查询。
- 若做关系扩展，只做 bounded proof，默认深度不超过 2，硬上限不超过 3。

## v3.3.0：Temporal Read Model and Query Contract

**用户故事**：当前 confirmed truth 能投影成可查询、可重建、可追溯的 temporal read model。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | temporal projection | MemoryEntry、RelationFact、ConfirmedRule 可投影成 read-model records |
| P0 | valid/recorded time fields | 查询结果明确 valid_from、valid_to、recorded_at |
| P0 | source provenance | 每条 record 指回 memory/rule/relation/evidence |
| P0 | rebuild read model | 维护命令可重建 temporal read model，且不改 truth |

## v3.3.1：Current vs History Query

**用户故事**：Agent 能显式区分当前事实和历史事实。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | current query | 默认只返回 currently-valid facts |
| P0 | history query | 显式 history 参数返回失效事实和 supersede chain |
| P0 | time-window filter | 支持 as_of / valid_range / recorded_range 查询 |
| P1 | abstention | 证据不足或时间冲突时返回不知道，而不是编造当前状态 |

## v3.3.2：Supersede Timeline Explainability

**用户故事**：当事实发生变化，Agent 能解释旧事实何时失效、新事实为什么生效。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | supersede chain query | 能从新事实找到旧事实，反向也能查 |
| P0 | timeline renderer | 以时间线展示同一 subject/predicate 的演进 |
| P0 | explanation renderer | 输出 old/current/evidence/policy reason |
| P0 | contradiction remains candidate-only | contradiction 只生成候选或 dream action，不直接改 truth |

## v3.3.3：Minimal Relationship Recall Proof

**用户故事**：Agent 可以沿关系链做有限召回实验，但不会让上下文或 schema 复杂度失控。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P1 | bounded relation recall | subject / predicate / object / time filter 可组合，默认 depth ≤1 |
| P1 | budgeted result | 输出带 why-included、source ids、truncation notice |
| P1 | cycle guard | 图中有环时不会重复展开 |
| P2 | multi-hop graph query | depth 2-3 仅作为 proof / benchmark 线，不阻塞 v3.3 主发布 |

## v3.3.4：Temporal Evaluation

**用户故事**：temporal query 改动能用任务维度评估，不只看总 recall。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | temporal fixtures | 覆盖 knowledge update、as_of、supersede、abstention |
| P0 | LongMemEval dimension report | 单独报告 temporal-reasoning / knowledge-update |
| P0 | regression gate | 当前事实错误、历史事实丢失、该 abstain 不 abstain 都算失败 |
| P1 | query traces | 评测输出包含 temporal query path 和 source evidence |

---

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- Focused tests:
  - current vs history query
  - valid_from / valid_to semantics
  - supersede chain explainability
  - timeline renderer
  - temporal abstention
  - LongMemEval dimension report

---

## 一句话

v3.3 让 temporal truth 真正可查询：当前事实、历史事实、as_of 和 supersede timeline 都能带时间、证据和预算返回；完整多跳图不是必要功能，先后置为 proof。
