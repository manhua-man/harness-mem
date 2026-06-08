# Roadmap: harness-mem v3.8

> 状态：已完成。
>
> 主题：True Hybrid Retrieval Shootout。把检索 benchmark 从 synthetic / smoke
> 推进到真实 FTS、vector、hybrid 对照，覆盖 recall、latency、cost 和 fallback。

---

## 目标

v3.8 不改变默认 embedding 基线，不用单一总分宣布胜利。它要回答的是：

```text
dataset / query set
-> FTS baseline
-> vector baseline
-> hybrid retrieval
-> recall + latency + token/cost + fallback analysis
```

参考线：

- `MemPalace`：LongMemEval / LoCoMo / ConvoMem 等 benchmark 要列指标、样本数和限制。
- `hypatia`：SQLite/DuckDB + embedding benchmark 可作为真实 hybrid/vector shootout 参考。
- `codedb-mcp`：warm-path latency 和 enabled/disabled 对照要有 artifact。
- v1.6.x historical shootout：`all-MiniLM-L6-v2` 是当前默认基线，`bge-small-en-v1.5`
  和 `nomic-embed-text-v1.5` 仍是候选，不默认替换。

## 边界

- 不在 artifact 之前宣称 true vector-hybrid latency 已证明。
- 不因某个模型单项更好就改默认 embedding baseline。
- 不下载或上传用户私有语料到云端 benchmark。
- 不把 retrieval recall 当成端到端回答正确率。
- 不用 synthetic warm-path latency 替代真实 vector/hybrid latency。

## v3.8.0：Dataset and Runner Discipline

**用户故事**：每个 retrieval benchmark 都知道数据从哪来、查询是什么、答案怎么判。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | dataset manifest | 记录 dataset、split、sample count、license note、query type |
| P0 | answer oracle | 每条 query 有 expected source id / answer evidence |
| P0 | runner reproducibility | 命令、cache policy、model path、hardware note 可复现 |
| P1 | fixture subset | 提供小样本本地 smoke，不替代 full benchmark |

**实现说明**：新增 `benchmark-suite/true_hybrid_retrieval_shootout/`，包含
`dataset.manifest.json`、`queries.json` 和 README。fixture subset 只验证 contract，
不解锁 public recall / latency claim。

## v3.8.1：FTS vs Vector vs Hybrid Metrics

**用户故事**：维护者能看出 hybrid 到底提升了 recall，还是只是增加了成本。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | recall metrics | R@1 / R@5 / R@10 或等价 source-hit 指标分模式输出 |
| P0 | latency metrics | cold / warm latency、p50 / p95、index load time 分开记录 |
| P0 | fallback accounting | vector unavailable、cold cache、embedding skip 时有单独计数 |
| P1 | per-type breakdown | temporal、knowledge-update、multi-session 等维度分开看 |

**实现说明**：suite collection 要求 `mode`、`expected_source_ids`、R@1/R@5/R@10、
p50/p95、fallback 和 token/cost estimate；`render_report.py` 为 true-hybrid
collection 生成专用 result table 和 recall readiness section。

## v3.8.2：Embedding Shootout Governance

**用户故事**：embedding 模型变化要有数据，不靠偏好。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | model candidates | `all-MiniLM-L6-v2`、`bge-small-en-v1.5`、`nomic-embed-text-v1.5` 同框比较 |
| P0 | default-change gate | 默认模型变更必须同时满足 recall、latency、disk/cache、install friction |
| P0 | no silent download | interactive write path 不因模型冷缓存被拖死 |
| P1 | model-specific notes | 记录语言、长度、硬件和 cache 限制 |

**实现说明**：matrix 固定 `all-MiniLM-L6-v2` 为默认 baseline，并把
`bge-small-en-v1.5`、`nomic-embed-text-v1.5` 作为候选；默认变更仍需 recall、latency、
disk/cache 和 install friction 同时过 gate。

## v3.8.3：Public Performance Claims

**用户故事**：README 只写已经被 artifact 支撑的性能 claim。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | claim readiness integration | true vector-hybrid latency gate 可由 v3.8 artifacts 推进 |
| P0 | report rendering | RESULTS.md 显示 recall/latency/cost 对照和 limitations |
| P0 | regression threshold | release gate 定义允许波动和 fail-fast 条件 |
| P1 | comparison hygiene | 不把不同项目不同 split 的数字硬拼成不诚实榜单 |

**实现说明**：`claim_readiness.retrieval_recall` 与 `retrieval_shootout` 已进入
release snapshot / package fallback。当前 full artifact blocker 仍存在，所以不能对外宣称
retrieval recall 或 true vector-hybrid latency 已证明。

## 一句话

v3.8 负责把检索性能说清楚：FTS、vector、hybrid 各自强在哪里、慢在哪里、失败在哪里；
没有真实 artifact 前，不把性能口号写成事实。
