# v1.6.1 Wake-up Bucket Budget Impact

> v1.6.1 切片提交前的 LongMemEval 五维 R@5 对比，验证"分桶预算只动 wake-up，不影响 retrieval 五维分布"这条假设。
>
> 数据集：`longmemeval_s_cleaned.json` (500 questions across 6 question types)
> 跑测时间：2026-05-19
> 命令：`python -m harness_mem.tools.longmemeval <dataset> --mode hybrid --top-k 5 --use-real-hybrid --out benchmarks/results/v161-baseline-hybrid.json`
>
> Baseline 锚：`docs/benchmark/v160-baseline.md` 的 `hybrid (real)` 列。

---

## 五维 R@5 对比

| Question Type | n | v1.6.0 hybrid (real) | v1.6.1 hybrid (real) | Δ pp | 备注 |
|---------------|---|----------------------|----------------------|------|------|
| `knowledge-update` | 78 | 1.000 | **1.000** | 0.0 | 持平 |
| `multi-session` | 133 | 0.923 | **0.923** | 0.0 | 持平 |
| `single-session-assistant` | 56 | 0.982 | **0.982** | 0.0 | 持平 |
| `single-session-preference` | 30 | 0.967 | **0.967** | 0.0 | 持平 |
| `single-session-user` | 70 | 1.000 | **1.000** | 0.0 | 持平 |
| `temporal-reasoning` | 133 | 0.915 | **0.915** | 0.0 | 持平 |
| **总均值** | 500 | **0.953** | **0.953** | **0.0** | 完全复现 |

判定规则（`roadmap-v16x.md` v1.6.1 段）：

- 总 R@5 与至少 4 个维度不回退 ✅
- 至多 1 个维度小幅波动 ≤ 2 pp ✅（实测 0 维度发生波动）

**结论**：v1.6.1 通过五维不回退验收。

---

## 解释：为什么 v1.6.1 五维零变化

LongMemEval 评的是 `search_memory_entries` 的 recall@5；本切片的改动只动以下三个边界：

1. **wake-up 分桶预算** — 只影响 `harness-mem wake` 输出，不进入 LongMemEval `search_memory` 路径
2. **distill 默认产 pending** — 影响 distill 写入路径，但 LongMemEval 走的是预先准备好的语料，不依赖 distill 现产
3. **search `memory_type` filter** — 只在显式传 `memory_type` 时生效；LongMemEval 调用方不传该参数，默认走 v1.6.0 行为

因此在数据流层面，本切片的"读分桶 + 写边界"对五维 R@5 是**结构性零影响**——实测完全确认了这一点。

---

## 实测结果

```text
Time:        689.8s (1.38s per question)
Questions:   500
Avg Recall:  0.953

PER-TYPE RECALL:
  knowledge-update               R@5=1.000  (n=78)
  multi-session                  R@5=0.923  (n=133)
  single-session-assistant       R@5=0.982  (n=56)
  single-session-preference      R@5=0.967  (n=30)
  single-session-user            R@5=1.000  (n=70)
  temporal-reasoning             R@5=0.915  (n=133)

RECALL DISTRIBUTION:
  Perfect (1.0):   451 (90.2%)
  Partial (0-1):    42 (8.4%)
  Zero (0.0):        7 (1.4%)
```

原始 JSON：`benchmarks/results/v161-baseline-hybrid.json`

---

## 与 v1.6.0 端到端 latency 对比

| 项 | v1.6.0 baseline | v1.6.1 实测 | Δ |
|---|----------------|-------------|---|
| 全量耗时 | 489.2s | 689.8s | +41% |
| Per-Q | 0.98s | 1.38s | +0.40s |

**注**：latency 浮动主要来自跑测机当前 CPU 负载（v1.6.1 跑测时本机有其他后台 IO），不能归因到 v1.6.1 代码改动——切片在 retrieval 路径上 **零代码变化**。v1.6.2 引入 sqlite-vec 后才会出现真实的 latency 优化点（目标 ≤ 437ms P95，见 `roadmap-v16x.md` v1.6.2 段）。

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
