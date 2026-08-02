# Graphiti

- 定位：时态知识图谱与关系检索的参考实现；不是 harness-mem 的目标存储引擎。
- Upstream：<https://github.com/getzep/graphiti>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\graphiti`
- 已核验 HEAD：`4f62cfe7a2d519e55bfdf2dc4a2fd06649dc00b3`（2026-08-01）。

## 架构与边界

Graphiti 将 episode、entity、relation edge 与 community 分成独立检索对象。顶层
`search()` 同时调度四个对象域；各域可开启 BM25、余弦向量和 BFS 候选通道，再以
RRF、MMR、node-distance、episode-mention 或 cross-encoder 重排。其适合说明
“候选生成、过滤、融合、呈现”必须分层，而不意味着 harness-mem 应引入 Neo4j/FalkorDB
或 LLM 驱动的图谱写入。

数据流为：查询文本 -> 仅在需要时计算 embedding -> 并发对象域/候选通道 -> 每通道
扩大候选池 -> 按稳定 UUID 合并 -> 选择重排器 -> 按 `limit` 返回带分数的 edge/node/
episode/community 集合。edge 的生命周期字段是 `valid_at`（事实发生/参考时间）、
`invalid_at`（事实声称无效的时间）与 `expired_at`（被后续事实取代的系统状态）；
它们可过滤且有数据库索引。回填 episode 仍以 `valid_at` 排序和推进 temporal watermark，
避免把“今天写入的旧事件”误当作最新事件。

## 检索、更新与故障语义

- 检索模型：edge/node 候选池各自由配置指定通道；edge 通道以 `2 * limit` 拉取候选，
  UUID 去重后以 RRF 或 MMR 等策略排序。BFS 查询形状测试明确防止对每个 path hit 再次
  扫全图匹配。
- 更新/删除：新 relation 与旧事实矛盾时维护流程将旧 edge 标为 `expired_at`，而不是
  原地改写或物理删除。因此过去的事实可被带时间条件的查询审计。
- 故障边界：Graphiti 的检索层有 tracing/error phase，但这不是派生索引的原子发布协议。
  harness-mem 不应依赖其图数据库事务或 LLM 判定来处理本地索引失败；本地 SQLite 的
  generation/manifest 仍应是恢复权威。

## 测试与评测启示

`tests/utils/search/test_edge_bfs_query_shape.py` 使用 recording driver 检验实际发出的
Cypher：BFS 直接消费 `relationships(path)`，保留 `RELATES_TO` 类型约束，且不含旧的按
UUID 逐行重新匹配。这是值得复制的性能测试形式：测试查询计划/形状，而不仅是最终命中。
上游也带 LongMemEval temporal-reasoning oracle 数据（`tests/evals/data/longmemeval_data/`），
但该大规模图/LLM 评测不应成为 harness-mem 的默认 CI 前提。

## 对 harness-mem：adopt / adapt / reject

- **Adopt（0.9.7）**：内部 `SearchPlan` 记录 lexical、vec0、relation/causal expansion
  三类候选来源、候选数、稳定 ID 去重和明确的 `as_of`/current-only 过滤 reason code。
- **Adapt（0.9.7）**：默认采用确定性 RRF 或已有轻量排序；先做 project、scope、
  superseded、temporal 过滤，再融合候选。relation expansion 必须受同一过滤器和预算
  约束，不能绕过隔离边界。
- **Reject**：图数据库作为运行时依赖、默认 cross-encoder、LLM 直接裁决矛盾 relation。
  它们增加网络/模型不确定性，并偏离本地、可复现的产品边界。

验收建议：新增至少 12 个 golden，覆盖回填旧事实、current/history 冲突、future `as_of`、
跨项目/跨 scope、supersession、relation expansion、候选重复和同分排序；20 次重复运行
必须产生完全相同的 hit ID 顺序与 reason codes，禁止 ID 泄漏。

## 证据表

| 结论 | 本地绝对路径与行号 | 可复核点 |
|---|---|---|
| 顶层并发检索入口 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\search\search.py:98` | `async def search` |
| edge 候选通道并发、2x 候选池 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\search\search.py:283-324`、`:321` | 建立 `search_tasks`，以 `semaphore_gather` 执行，记录 `candidate_limit: 2 * limit` |
| UUID 合并和 RRF/MMR | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\search\search.py:355-389`、`:374` | `edge_uuid_map`、`rrf`、`maximal_marginal_relevance` |
| 配置与带分数结果合同 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\search\search_config.py:80-128` | `EdgeSearchConfig`、`SearchConfig`、`SearchResults` |
| 三个时间字段 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\edges.py:271-277` | `expired_at`、`valid_at`、`invalid_at` |
| 时间字段索引 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\graph_queries.py:79-81` | 三个 edge 时间索引 |
| 回填按事件时间排序 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\graphiti.py:450,560-563,1424-1431` | temporal watermark 与 `sorted_episodes` |
| 矛盾使旧 edge 失效 | `F:\AIInfra\upstreams\harness-mem\graphiti\graphiti_core\utils\maintenance\edge_operations.py:538,570,822-847` | `resolve_edge_contradictions` 与 `expired_at` |
| BFS 查询计划回归测试 | `F:\AIInfra\upstreams\harness-mem\graphiti\tests\utils\search\test_edge_bfs_query_shape.py:35-84` | 断言无 per-hit UUID re-match |
