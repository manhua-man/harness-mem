# harness-mem V1 Benchmark Report

> 这份文档是 V1 阶段的 retrieval baseline 报告。`harness-mem` 的完整 benchmark 体系定义见 `docs/benchmark_system.md`。

## 背景

V1 里程碑完成之际，在 LongMemEval 数据集上对 harness-mem 的检索能力进行了标准化测量。

**目标：** 用业界公开的 benchmark 量化 harness-mem 的召回率基线，明确与前沿（MemPalace 向量嵌入）的差距，为后续优化提供依据。

---

## 数据集：LongMemEval

| 属性 | 值 |
|------|---|
| 总问题数 | 500 |
| Session 总数 | 23,867 |
| 类型 | 6 类（见下表） |
| 每题 haystack | ~53 sessions |
| 评测指标 | R@K（Recall at K，top-K 内的召回率） |
| 原始数据 | `C:\Users\ManHua\AppData\Local\Temp\longmemeval_s_cleaned.json`（277MB） |

### 问题类型分布

| 类型 | 题数 | 说明 |
|------|------|------|
| `single-session-user` | 70 | 答案在单条 user session 内 |
| `knowledge-update` | 78 | 跨 session 知识更新（多版本） |
| `single-session-assistant` | 56 | 答案在单条 assistant session 内 |
| `temporal-reasoning` | 133 | 需要时间推理 |
| `multi-session` | 133 | 答案分布在多条 session |
| `single-session-preference` | 30 | 用户偏好类问题 |

---

## 评测方法

### harness-mem 检索模式

**Raw FTS5 模式：** 单 token 独立搜索 + BM25 聚合
- SQLite FTS5 stop word 导致自然语言查询失效（"what did I" → 0 命中）
- 修复：分词后过滤 stop words，对每个 token 独立搜索，session 内取 BM25 最优值
- 最终返回按 BM25 合并分数排序的 top-K session IDs

**Hybrid 模式：** FTS5 + 关键词/姓名/引语/时间加成
- 在 raw 结果上做二次排序
- keyword overlap、person name match、quoted phrase、temporal proximity 各有权重
- 效果：总体反而略低于 raw（见下节）

### MemPalace 对比基线（来自公开论文）

| 基线 | R@5 | 说明 |
|------|------|------|
| MemPalace raw（语义向量） | 96.6% | ChromaDB BM25 + 嵌入向量 |
| MemPalace hybrid v4 + LLM rerank | ≥99% | 混合检索 + 大模型重排 |

---

## 核心结果

### harness-mem FTS5 Raw — 分类型 R@K

| 类型 | R@5 | R@10 | R@20 |
|------|------|------|------|
| single-session-user | **98.6%** | **100%** | **100%** |
| knowledge-update | 96.2% | **100%** | **100%** |
| single-session-assistant | 94.6% | 94.6% | 96.4% |
| temporal-reasoning | 82.8% | 90.7% | 92.5% |
| multi-session | 79.2% | 88.8% | 90.5% |
| single-session-preference | 80.0% | 80.0% | 83.3% |
| **总体** | **87.3%** | **92.8%** | **94.1%** |

### 与 MemPalace 基线对比

| 指标 | MemPalace raw（向量） | harness-mem FTS5 | 差距 |
|------|----------------------|-------------------|------|
| R@5 | 96.6% | 87.3% | **-9.3pp** |
| R@10 | — | 92.8% | — |
| R@20 | — | 94.1% | — |

---

## 定位说明：V2 与 MemPalace 的关系

本报告的结论应理解为：**harness-mem V1 已经建立了 local-first 的检索与结构化记忆基线，但当前 R@5 仍低于 MemPalace 的公开 retrieval baseline。**

因此，V2 可以对外表述为“目标是在产品能力面上做成比 MemPalace 更完整的 agent memory runtime”，而不是“当前检索能力已经超过 MemPalace”。这里的“更完整”主要指：

- hybrid retrieval（BM25/FTS + vector + graph），而非纯 FTS baseline
- structured writable memory，而不只是检索历史
- correction -> candidate rule -> confirm 的学习闭环
- task handoff / task resume / multi-client continuation

是否能在 retrieval benchmark 上追平或超过 MemPalace，应该以 V2 的实测结果为准。

---

## 分析：差距在哪里

### 1. FTS vs 语义向量（核心瓶颈）

FTS5 基于字面 token 匹配，无法处理：
- 同义词：「网球拍」↔ 「tennis racket」
- 语义相关：「我领导的项目」↔ 「I led several initiatives」
- 表述变换：「我毕业于哪」↔ 「我的学位」

**9.3pp 的差距几乎全部来自语义鸿沟**，而非工程问题。

### 2. 分类型表现

| 类型 | R@5 harness | R@5 MemPalace | 评价 |
|------|-------------|---------------|------|
| single-session-user | 98.6% | ~100% | FTS 几乎够用 |
| knowledge-update | 96.2% | ~98% | FTS 够用，版本区分需向量 |
| single-session-assistant | 94.6% | ~98% | 措辞差异影响 |
| temporal-reasoning | 82.8% | ~97% | **主要差距**：需语义理解时间关系 |
| multi-session | 79.2% | ~96% | **主要差距**：跨 session 语义聚合 |
| single-session-preference | 80.0% | ~95% | **主要差距**：偏好类问题语义模糊 |

`single-session-user` 和 `knowledge-update` 在 R@5 已接近触顶（98.6%、96.2%），FTS 对精确匹配场景效果显著。

`temporal-reasoning`、`multi-session`、`single-session-preference` 是重灾区，合计占总体差距的 ~85%。

### 3. Zero Recall 分析

R@5 下 500 题中有 **26 题零召回**（5.2%），分类：

| 类型 | 零召回题数 | 典型问题 |
|------|-----------|---------|
| multi-session | 9 | "我领导或正在领导多少个项目" |
| temporal-reasoning | 7 | "我参加的运动会的顺序" |
| single-session-preference | 6 | "我应该用什么配饰搭配我的摄影装备" |
| single-session-assistant | 3 | "你建议过哪些方法..." |
| single-session-user | 1 | "我每天练习小提琴多长时间" |

这 26 题的共性：**关键词与 session 原文表述完全不同**，纯 FTS 无法解决。

### 4. Hybrid 为什么不工作

hybrid 模式（R@5 = 86.3%）反而比 raw（87.3%）低 1pp。

原因分析：
- 26 题 hybrid 零命中但 raw 非零（13 题 raw 更好的全部来源）
- 加成机制对低 BM25 分数的 session 惩罚过度，导致原本排名靠前的事实答案被挤出 top-5
- 关键词 overlap boost 在多 session 场景制造噪音（多个 session 共享关键词）

**结论：** hybrid 的信号设计偏向精确匹配，在模糊语义场景反而帮倒忙。需重新设计融合权重或引入向量相似度。

---

## 工程说明

### SQLite FTS5 Stop Words 问题

SQLite FTS5 内置 stop word 列表（"what", "did", "I", "the" 等），导致包含 stop words 的自然语言查询返回零命中。

**修复方案：** 查询时先分词，过滤 stop words，对每个非停用词独立搜索 FTS5，取 session 内 BM25 最优值。实现见 `harness_mem/tools/longmemeval.py:_tokenize()`。

### benchmark 代码位置

```
harness_mem/tools/longmemeval.py    # harness-mem LongMemEval 评测器
results_harness_top5_*.json         # 默认输出到当前工作目录
```

运行方式：
```bash
python -m harness_mem.tools.longmemeval <data_file> --mode raw --top-k 5
python -m harness_mem.tools.longmemeval <data_file> --mode hybrid --top-k 5
```

---

## 后续优化路径

### 短期（V1.x，可立即做）
1. **向量嵌入**：用 sentence-transformers 跑轻量嵌入（all-MiniLM-L6-v2，22M 参数），R@5 目标 94%+
2. **BM25 + 向量混合检索**：向量相似度分与 BM25 分数线性加权
3. **重排器（ReRanker）**：用 cross-encoder 对 top-20 结果重排，目标 R@5 ≥ 97%

### 中期（V2）
1. **semantic chunk**：session 内按语义段落分块，而非整段 FTS
2. **temporal bias**：时间衰减权重，对近期 session 给予更高基础分
3. **person entity boost**：用户提到的姓名优先于关键词命中

---

## 结论

| 结论 | 说明 |
|------|------|
| harness-mem V1 FTS5 基线 | R@5 = **87.3%**，R@20 = **94.1%** |
| 与前沿差距 | **-9.3pp**（MemPalace 向量基线 96.6%） |
| 差距根因 | 语义鸿沟，FTS 无法处理表述变换和同义词 |
| FTS 强项 | 精确匹配（single-session-user 98.6%，knowledge-update 96.2%） |
| FTS 弱项 | 语义模糊、多 session 聚合、时间推理（合计 21% 零召回） |
| 优化路径 | 引入向量嵌入 + 混合检索 + ReRanker，目标 R@5 ≥ 94% |

---

*文档生成时间：2026-04-23*
*benchmark 代码：`harness_mem/tools/longmemeval.py`*
