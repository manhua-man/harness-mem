# Loop Evaluation Harness

> **状态**: scenario 1–5 真跑并产生指标。

## 这个 harness 解决什么问题

`tests/benchmark/test_longmemeval.py` 测的是 **单点检索质量**（"给定 query 和数据库，top-k 命中率"）。

`tests/loop_harness/` 测的是 **4 角色记忆闭环本身的质量**（"suggest → confirm → wake → 命中 → 影响行为"）。两个 harness 互补：

| Harness | 回答的问题 | 一个具体例子 |
|---|---|---|
| LongMemEval | 检索算法好不好 | "embedding 升级后，semantic R@5 从 0.95 涨到 0.96" |
| Loop harness | 闭环各环节有没有偷工减料 | "AI 自动 confirm 的低风险候选，哪些其实应该 reject" |

## 五个 scenario

| # | 文件 | 状态 | 输出指标 |
|---|---|---|---|
| 1 | `test_distill_precision_recall.py` | ✅ 真跑 | `precision`, `recall`, `f1` |
| 2 | `test_auto_confirm_calibration.py` | ✅ 真跑 | `false_positive_rate`, `false_negative_rate`, `auto_confirmed`, `auto_rejected`, `kept_pending` |
| 3 | `test_wake_actually_surfaces.py` | ✅ 真跑 | `confirmed_rule_surfaced` (bool), `surface_count` |
| 4 | `test_supersede_replaces.py` | ✅ 真跑 | `current_truth_correct` (bool), `history_visible_when_requested` (bool) |
| 5 | `test_rule_surface_count_increments.py` | ✅ 真跑 | `usage_count` (int), `has_last_surfaced_at` (bool) |

## 跨版本对比怎么用

每个 scenario 的核心断言都使用宽松阈值（避免误报），同时把**实际数字**通过 `print()` 写到 stdout。CI 跑完后可以用 `pytest --capture=no` 抓出来，存档对比。

后续可以加一个 `tests/loop_harness/reports/` 目录存 JSON 结果，但当前阶段不引入持久化产物——先让骨架跑通。

## 设计约束

- **真实风格 fixture，非合成数据**: `fixtures/sessions/*.jsonl` 是从真实 Claude Code session 脱敏改写过的样本，不是 lorem ipsum。
- **数据隔离**: 每个 scenario 用 `tmp_path` 起独立 backend，绝不写 `~/.harness-mem/`。
- **不依赖 LLM**: 整个 harness 只用本地启发式 distill + 本地 SQLite，CI 可重现。LLM 路径有自己的 `session-distill` skill 验证，不在这里。

## 下一步（不在本切片）

- **scenario 6**: relation graph 是否真的被 distill 自动喂数据（当前预期：**否**，所以 v1.7.2 的 graph traversal 是死功能）
- **scenario 7**: 三个月没被命中的 ConfirmedRule，doctor 是否提示删除（scenario 5 已经把"事实"打通——usage_count + last_surfaced_at——剩下是产品决策：保留期阈值 / doctor 文案）
- **scenario 8**: 跨项目复用通用 rule 的产品语义（依赖 `global_rule` schema，目前缺）

这三个对应"周明远"角色卡里的 P1 / P2 痛点，等相关 schema 改造或产品决策落地后再补。
