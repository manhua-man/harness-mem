# Loop Evaluation Harness

> **状态**: scenario 2/3/4/5/7/8 真跑（v2.0 砍除 1 和 6——见下表脚注）。

## 这个 harness 解决什么问题

`tests/benchmark/test_longmemeval.py` 测的是 **单点检索质量**（"给定 query 和数据库，top-k 命中率"）。

`tests/loop_harness/` 测的是 **4 角色记忆闭环本身的质量**（"suggest → confirm → wake → 命中 → 影响行为"）。两个 harness 互补：

| Harness | 回答的问题 | 一个具体例子 |
|---|---|---|
| LongMemEval | 检索算法好不好 | "embedding 升级后，semantic R@5 从 0.95 涨到 0.96" |
| Loop harness | 闭环各环节有没有偷工减料 | "AI 自动 confirm 的低风险候选，哪些其实应该 reject" |

## 六个 scenario

| # | 文件 | 状态 | 输出指标 |
|---|---|---|---|
| 2 | `test_auto_confirm_calibration.py` | ✅ 真跑 | `false_positive_rate`, `false_negative_rate`, `auto_confirmed`, `auto_rejected`, `kept_pending` |
| 3 | `test_wake_actually_surfaces.py` | ✅ 真跑 | `confirmed_rule_surfaced` (bool), `surface_count` |
| 4 | `test_supersede_replaces.py` | ✅ 真跑 | `current_truth_correct` (bool), `history_visible_when_requested` (bool) |
| 5 | `test_rule_surface_count_increments.py` | ✅ 真跑 | `usage_count` (int), `has_last_surfaced_at` (bool) |
| 7 | `test_doctor_flags_unused_rules.py` | ✅ 真跑 | `hm_401_emitted` (bool), `rule_quality_line_present`, `stale_count_visible` |
| 8 | `test_correction_supersede_one_shot.py` | ✅ 真跑 | `old_rule_marked_historical` (bool), `supersede_chain_returned` (bool) |

**Scenario 1 (distill precision/recall)** 和 **scenario 6 (relation graph data pipeline)** 在 v2.0 移除——它们测的是启发式 distill，已在 v2.0 砍除。LLM-driven distill 的输出非确定性，不能在 CI 中以静态 fixture 跑出 baseline；agent 端的评估应放在 skill prompt 测试或 manual eval 报告里，不挤进 loop_harness。

## 跨版本对比怎么用

每个 scenario 的核心断言都使用宽松阈值（避免误报），同时把**实际数字**通过 `print()` 写到 stdout。CI 跑完后可以用 `pytest --capture=no` 抓出来，存档对比。

后续可以加一个 `tests/loop_harness/reports/` 目录存 JSON 结果，但当前阶段不引入持久化产物——先让骨架跑通。

## 设计约束

- **真实风格 fixture，非合成数据**: `fixtures/sessions/*.jsonl` 是从真实 Claude Code session 脱敏改写过的样本，不是 lorem ipsum。
- **数据隔离**: 每个 scenario 用 `tmp_path` 起独立 backend，绝不写 `~/.harness-mem/`。
- **不依赖 LLM**: 整个 harness 只用本地启发式 distill + 本地 SQLite，CI 可重现。LLM 路径有自己的 `session-distill` skill 验证，不在这里。

## 下一步（不在本切片）

- **scenario 9**: 跨项目复用通用 rule 的产品语义（依赖 `global_rule` schema，目前缺；优先级 P2，等真实多项目用户反馈再做）

scenario 6 实证：自然 session 提取 0 relation facts / 5 memory entries，
ratio = 0.0。要让 v1.7.2 graph traversal 真正可用，必须有 LLM-driven distill
能从普通 prose 里提炼实体关系，或者把 `suggest_relation_fact` 提升为 distill
管线里的明确步骤——这是产品决策，不是工程问题。

scenario 7 实证：doctor 现在有 HM-401 提示用户处理久未命中或从未命中的规则。
保留期默认 90 天，写在 `harness_mem/commands/doctor.py::UNUSED_RULE_DAYS`，
等到有真实使用数据再调整。doctor 只提示，不删——删除继续是 reject /
supersede 的明确人工动作。

scenario 8 实证：周明远场景里"Tauri v1 → v2 升级，老 IPC 规则现在错了"的
一步纠错路径已打通。CLI `harness-mem correct ... --supersedes <id> --reason ...`
和 MCP `suggest_correction(...)` 走同一份 Python 逻辑，老规则 valid_to 设置 +
supersede 链建立 + 默认 list_confirmed_rules 不再返回老规则，include_history
仍可审计。
