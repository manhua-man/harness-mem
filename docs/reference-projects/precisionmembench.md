# PrecisionMemBench

- 定位：可替换 memory-provider 的检索正确性、会话突变和性能报告基准；不是
  harness-mem 的在线运行时。
- Upstream：<https://github.com/tenurehq/precisionMemBench>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\precisionMemBench`
- 已核验 HEAD：`b95d6abb471c0d591c440172283dd74e7af000df`（2026-08-01）。

## 架构与数据流

benchmark 将不同 provider 放在统一 adapter 后：reset -> fixture seed -> 等待 provider
index ready（如需要）-> `buildContext` -> fixture assertions -> JSON report。`BaseAdapter`
把 persona、pinned facts、open questions 并行读取；query retrieval 后，relation belief
还能扩展 participant，并在相同 scope/budget 下拼装 context。每条 seed operation 记录
应用侧 latency；provider 可以报告并扣除自身数据库 overhead。

它的核心不是“某一种向量数据库分数较高”，而是将 fixture 中的 belief ID 当成可审计
oracle：包含项、禁止项、精确集合、pinned/question 路由和 session noise 都可独立失败。
session eval 进一步在执行中 create/update belief，并等待向量/BM25 索引确认可见后继续下一
turn，因而能暴露更新后检索旧内容或索引滞后的问题。

## 检索、更新、删除与故障语义

- 检索模型：adapter 的 context 结构区分 persona、pinned facts、relevant beliefs、open
  questions；relation expansion 是显式阶段而非不透明 reranker 副作用。
- 更新/删除：session fixture 能在中途新增或更新 belief，评测等待 index sync 后才断言。
  这适合转化为 harness-mem 本地事务提交后的“新 generation 立即可见”合同，而不是无限
  polling。
- 故障边界：外部 provider 的 index readiness 有 timeout/retry；报告不把超时伪装成空集。
  harness-mem 应保持本地测试默认无 Docker、无网络和无 embedding 服务。

## 测试与评测模型

静态与 session suite 同时支持 `mustInclude`、`mustExclude`、`shouldOnlyInclude`；session
suite 另有 `noiseCheck.mustNotSurface`。precision/recall 从实际 surfaced IDs 与 golden
ID 集合计算，report 将 active retrieval、structural pass 和 trivially empty 分开，并输出
mean、p50、p95 latency 与可选 ingestion 明细。fixture 覆盖 scope disambiguation、
supersession、budget、ranking、type routing 和 relation expansion，而不是只测简单 query。

## 对 harness-mem：adopt / adapt / reject

- **Adopt（0.9.9）**：在既有 retrieval golden 之外增加版本化 fixture schema、每类别
  precision/recall、P50/P95、active/structural/empty pass 分类和 JSON baseline artifact。
- **Adapt（0.9.9）**：加入多轮 create/supersede/temporal conflict/rebuild cases，以及
  cross-project、historical/current-only、abstention reason 的负例；记录 corpus size、模型、
  index generation 和 warm/cold 条件，才可比较性能。
- **Reject**：让 Docker Mongo、外部 embedding 或 provider polling 成为主 CI 依赖；也不要
  将 empty expected result 计作有效检索成功。

验收建议：critical golden 100% 通过、cross-project/forbidden hit 为零；每类至少一条
`mustExclude`，每个 session mutation 都验证提交后可见性。固定同一 runner 下，热身后
1k/10k profile 的 P95 或 build latency 相对 checked-in baseline 回退不超过 10%；quality
golden 不允许回退。

## 证据表

| 结论 | 本地绝对路径与行号 | 可复核点 |
|---|---|---|
| adapter 的 seed/延迟/可选等待 | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\adapters\baseAdapter.ts:106-171` | `ingestionReport`、overhead 扣除、`waitAfterSeed` |
| context 组装和 relation expansion | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\adapters\baseAdapter.ts:185-239,280-307` | `Promise.all`、search、participant expansion、budget |
| 检索 adapter 入口 | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\adapters\baseAdapter.ts:241-278` | `searchText` 和 ID 去重/排除 |
| 静态 golden 的正/负/精确集断言 | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\retrieval.vector.eval.test.ts:480-614` | include/exclude/only、precision/recall |
| session 噪声与 precision/recall | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\session-retrieval.vector.eval.test.ts:511-613` | `noiseCheck`、drift、metrics |
| session index ready / mutation sync | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\session-retrieval.vector.eval.test.ts:358,396,416,652-666,743-757` | index/BM25/vector readiness 与 update 可见性 |
| 报告分类与 P95 | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\src\utils\buildRetrievalReport.ts:78-88,131-198` | `classifyPass`、pass types、P95、active passes |
| 覆盖面 fixture | `F:\AIInfra\upstreams\harness-mem\precisionMemBench\fixtures\retrieval.cases.json:283-916` | scope、ranking、budget、relation、supersession cases |
