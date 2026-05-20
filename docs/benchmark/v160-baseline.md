# v1.6.0 LongMemEval Baseline

> 启动当日 baseline，作为 v1.6.x 三切片"不回退"承诺的锚点。
>
> 文档与 benchmark 默认以 `all-MiniLM-L6-v2` 作为 embedding 基线模型；除非单独的 shootout 报告另有说明，否则这里的 `hybrid (real)` 就是后续对比锚点。
>
> 数据集: `longmemeval_s_cleaned.json` (500 questions across 6 question types)
> 跑测时间: 2026-05-17
> 命令: `python -m harness_mem.tools.longmemeval <dataset> --mode <mode> --top-k 5 [--use-real-hybrid]`
> 原始 JSON 报告: `benchmarks/results/v160-baseline-{fts,hybrid-synthetic,hybrid-real}.json`

---

## 总览

| Mode | Avg R@5 | Time (s) | Per-Q (s) | Perfect | Partial | Zero |
|------|---------|----------|-----------|---------|---------|------|
| `fts` (raw FTS5) | **0.879** | 202.2 | 0.40 | 79.6% | 15.8% | 4.6% |
| `hybrid` synthetic (FTS + boosting heuristics) | **0.869** | 207.0 | 0.41 | 78.0% | 17.0% | 5.0% |
| `hybrid` real (`HybridSearchLayer`, FTS + vector RRF + Porter stem fallback) | **0.953** | 489.2 | 0.98 | 90.2% | 8.4% | 1.4% |

`hybrid-real` 数字**精确复现**了 v1.5.2 收尾时的 `0.953`（见 `CHANGELOG.md` 1.5.2 条目）。该模式 = 生产 `HybridSearchLayer` + Porter stem fallback + sentence-transformers `all-MiniLM-L6-v2`。

---

## 五维 R@5 baseline

| Question Type | n | fts | hybrid (synthetic) | hybrid (real) |
|---------------|---|-----|--------------------|---------------|
| `knowledge-update` | 78 | 0.962 | 0.942 | **1.000** |
| `multi-session` | 133 | 0.792 | 0.781 | **0.923** |
| `single-session-assistant` | 56 | 1.000 | 1.000 | 0.982 |
| `single-session-preference` | 30 | 0.800 | 0.800 | **0.967** |
| `single-session-user` | 70 | 0.986 | 0.986 | **1.000** |
| `temporal-reasoning` | 133 | 0.828 | 0.812 | **0.915** |

**作为后续切片不回退锚点的列**：`hybrid (real)` 列。任何 v1.6.1 / v1.6.2 改动后跑出的五维数字都必须与这一列对照评估。

---

## 该 baseline 的几个观察（不是优化结论，仅用于后续归因）

### 1. 合成 hybrid 相对 raw FTS 实际**轻微回退**

`synthetic hybrid` (0.869) < `fts` (0.879)。说明 `_session_doc_for_query` 的关键词/人名/引用增强启发式在当前数据上**没有净收益**。这与 v1.5.2 留下的源码注释一致：合成 hybrid 是 mempalace 时代的遗物，主路径已经迁到 `hybrid-real`。

**v1.6.x 行动**：合成 hybrid 不是产品路径，但仍保留作为诊断工具；不投入优化资源。

### 2. `single-session-assistant` 在 real hybrid 上略低于 raw FTS

`fts` 1.000 vs `hybrid-real` 0.982。这是**唯一**一个维度上 real hybrid 输给 raw FTS 的 case。

**可能原因（待 v1.6.1 复盘前不下结论）**：该维度问题大量包含 `our previous conversation` 这种 meta-talk，FTS 的字面 token 命中率天然就高；vector embedding 对短上下文的 meta-reference 反而引入噪声。

**v1.6.x 行动**：把这个维度放进 v1.6.2 embedding shootout 的关注列表——如果换 bge-small / nomic-embed 后这个维度仍然回退，就是 RRF 融合权重的问题，而不是模型问题。

### 3. `single-session-preference` 的 hybrid 相对 fts 提升最多（+16.7 pp）

0.800 → 0.967。这个维度题目通常包含主观偏好表述（"my favorite", "I prefer"），vector 抓得比 FTS 准。

**v1.6.x 行动**：v1.6.1 wake-up 分桶预算把 semantic（confirmed preferences） 提到 50% 配额是对的方向。

### 4. `multi-session` 与 `temporal-reasoning` 仍然是最弱的两个维度

real hybrid 上分别 0.923 / 0.915，是六维里唯二低于 0.95 的。

**v1.6.x 行动**：

- `temporal-reasoning` 弱在 v1.7 bi-temporal 字段引入前结构性无解，v1.6.x 不强求改善
- `multi-session` 是 v1.6.2 embedding 升级的主要目标——更大 embedding 模型对跨 session 主题相关性应有结构性收益

---

## v1.6.x 不回退判定规则

每个切片合并到 main 之前，跑一次 `hybrid (real)` mode 与本 baseline 对比：

| 切片 | 合规判定 |
|------|---------|
| **v1.6.0** | 完全不回退（schema 改动不应影响 retrieval） |
| **v1.6.1** | 总 R@5 与至少 4 个维度不回退；允许至多 1 个维度小幅波动 ≤ 2 pp（分桶预算可能轻微改变 wake-up 训练分布，但不直接进入 LongMemEval corpus，理论上应该 0 影响——若实测有影响必须解释清楚） |
| **v1.6.2** | 决策规则按 `roadmap-v16x.md` 的"已决策 3"段执行；`all-MiniLM-L6-v2` 留底基线 = 本表 hybrid (real) 列 |

---

## 跑测环境

| 项 | 值 |
|----|---|
| Python | 3.13 |
| sentence-transformers | 5.4.1 |
| Embedding model | `all-MiniLM-L6-v2` (22MB, 384d, Apache 2.0) |
| OS | Windows |
| CPU encoding | yes (no GPU) |

环境差异对 R@5 没有影响（数字是确定的）；只对 `Time / Per-Q` 列有影响，参考时记得对齐到自己机器再比较 latency。
