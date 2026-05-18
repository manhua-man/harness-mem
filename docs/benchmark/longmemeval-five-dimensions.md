# LongMemEval 五维评分含义

> 配合 [`v160-baseline.md`](./v160-baseline.md) 阅读。本文档解释 LongMemEval `question_type` 字段的六个维度（命名"五维"是延续 vision 文档表述；实际数据集中是 6 个维度），以及 v1.6.x 路线如何按维度归因优化收益。
>
> 来源：[LongMemEval (arxiv:2410.10813)](https://arxiv.org/abs/2410.10813)

---

## 六个登记维度

`harness_mem.tools.longmemeval` 在 v1.6.0 起把以下六个 `question_type` 登记为 `LONGMEMEVAL_QUESTION_TYPES` 常量。任何数据集中出现的未登记维度会触发 `warnings.warn(...)`，但不阻断评测。

| Question Type | 含义 | 典型问法 | n (LongMemEval-S) |
|---------------|------|---------|-------------------|
| `single-session-user` | 单 session 内可直接命中用户事实 | "Where did I attend my cousin's wedding?" | 70 |
| `single-session-preference` | 单 session 内可直接命中用户偏好 | "What is my preferred gin-to-vermouth ratio?" | 30 |
| `single-session-assistant` | 单 session 内 assistant 给出过的建议 / 内容 | "I'm looking back at our previous conversation about music theory..." | 56 |
| `multi-session` | 需要跨多个 session 推理的问题 | "What did I do with Rachel on the Wednesday two months ago?" | 133 |
| `temporal-reasoning` | 需要时间推理（"两周前"、"上个月"等相对时间） | "I mentioned cooking something for my friend a couple of days ago" | 133 |
| `knowledge-update` | 用户事实在多 session 间发生过更新 | （e.g.：之前说住在 SF，后来搬到 NY，问"你住哪儿？"） | 78 |

---

## v1.6.x 各切片对每个维度的预期

| 维度 | v1.6.0 | v1.6.1 | v1.6.2 |
|------|--------|--------|--------|
| `single-session-user` | 不变 | 不变 | 持平或小升 |
| `single-session-preference` | 不变 | **可能上升**（semantic 桶 50% 配额给 confirmed preference 提供保留预算） | 持平或小升 |
| `single-session-assistant` | 不变 | 不变 | **重点观察**（baseline 1.000 → real-hybrid 0.982 已小回退） |
| `multi-session` | 不变 | 不变 | **重点目标**（v1.6.0 baseline 0.923；新 embedding 模型对跨 session 相关性应有结构性收益） |
| `temporal-reasoning` | 不变 | 不变 | 不强求改善（结构性瓶颈在 v1.7 的 bi-temporal 字段） |
| `knowledge-update` | 不变 | 不变 | 持平（baseline 已 1.000） |

---

## 为什么单一总分会误导

v1.5.2 一度想用调 RRF 权重把总分从 0.94 推到 0.96，但 `v152-recall-failure-analysis*.md` 系列分析表明：

- 在 `multi-session` 维度调高 vector 权重，会把 `single-session-*` 维度的精确 token 命中挤掉
- 在 `single-session-*` 维度调高 FTS 权重，会让 `multi-session` 跨 session 主题相似性失分
- 单一总分的"提升"经常是某些维度的提升被另一些维度的回退**部分抵消**后的净效果，反而失去归因能力

v1.6.x 起的所有 retrieval 改动**必须**贴出五维对比表，不接受单一总分作为成功证据。

---

## 跑五维基线的一行命令

```bash
# Real hybrid (主线路径)
python -m harness_mem.tools.longmemeval <dataset> --mode hybrid --top-k 5 --use-real-hybrid \
  --out benchmarks/results/<your-run-name>.json

# 对照路径 (用于诊断 hybrid 收益是否真的来自 vector)
python -m harness_mem.tools.longmemeval <dataset> --mode raw --top-k 5 \
  --out benchmarks/results/<your-run-name>-fts.json
```

输出含 `PER-TYPE RECALL` 段；JSON 含 `per_type` 字段。

---

## 数据集取得

- LongMemEval 项目：<https://github.com/xiaowu0162/LongMemEval>
- 我们使用的清洗版：`longmemeval_s_cleaned.json`（500 questions）
- 清洗逻辑见 `tests/benchmark/` 下的相关脚本（去除非英文 noise、规整 timestamp 格式）
