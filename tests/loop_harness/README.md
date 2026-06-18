# Loop Evaluation Harness

> **状态**: scenario 2/3/4/5/7/8/9/10/11/12 真跑（v2.0 砍除 1 和 6——见下表脚注）。

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
| 9 | `test_mcp_setup_without_cli.py` | ✅ 真跑 | `set_active_project_works`, `update_profile_idempotent`, `wake_surfaces_convention`, `hm_501_emitted` |
| 10 | `test_wake_usage_badge.py` | ✅ 真跑 | `fresh_rule_marked_never_surfaced`, `veteran_rule_shows_count`, `veteran_rule_shows_recency` |
| 11 | `test_context_outcome_loop.py` | ✅ 真跑 | `context_outcome_signals`, `used_score_positive`, `misleading_score_negative`, `explained_result_count`, `truth_mutation_count` |
| 12 | `test_guided_maintenance_profiles.py` | ✅ 真跑 | `profile_update_success`, `dry_run_count`, `summary_fields_present`, `auto_applied_count`, `truth_mutation_count`, `candidate_mutation_count`, `signal_mutation_count` |

**Scenario 1 (distill precision/recall)** 和 **scenario 6 (relation graph data pipeline)** 在 v2.0 移除——它们测的是启发式 distill，已在 v2.0 砍除。LLM-driven distill 的输出非确定性，不能在 CI 中以静态 fixture 跑出 baseline；agent 端的评估应放在 skill prompt 测试或 manual eval 报告里，不挤进 loop_harness。

## 跨版本对比怎么用

每个 scenario 的核心断言都使用宽松阈值（避免误报），同时把**实际数字**通过 `print()` 写到 stdout。CI 跑完后可以用 `pytest --capture=no` 抓出来，存档对比。

后续可以加一个 `tests/loop_harness/reports/` 目录存 JSON 结果，但当前阶段不引入持久化产物——先让骨架跑通。

## 设计约束

- **真实风格 fixture，非合成数据**: `fixtures/sessions/*.jsonl` 是从真实 Claude Code session 脱敏改写过的样本，不是 lorem ipsum。
- **数据隔离**: 每个 scenario 用 `tmp_path` 起独立 backend，绝不写 `~/.harness-mem/`。
- **不依赖 LLM**: 整个 harness 只用本地启发式 distill + 本地 SQLite，CI 可重现。LLM 路径有自己的 `session-distill` skill 验证，不在这里。

## 下一步（不在本切片）

- **scenario 10**: 跨项目复用通用 rule 的产品语义（依赖 `global_rule` schema，目前缺；优先级 P2，等真实多项目用户反馈再做）

scenario 6 实证：自然 session 提取 0 relation facts / 5 memory entries，
ratio = 0.0。要让 v1.7.2 graph traversal 真正可用，必须有 LLM-driven distill
能从普通 prose 里提炼实体关系，或者把 `suggest_relation_fact` 提升为 distill
管线里的明确步骤——这是产品决策，不是工程问题。

scenario 7 实证：doctor 现在有 HM-401 提示用户处理久未命中或从未命中的规则。
保留期默认 90 天，写在 `harness_mem/commands/doctor.py::UNUSED_RULE_DAYS`，
等到有真实使用数据再调整。doctor 只提示，不删——删除继续是 reject /
supersede 的明确人工动作。

scenario 7 现在覆盖四种真实情况：never-surfaced 隔离、stale 隔离、healthy
项目无误报、以及**混合人口**（healthy + stale + never-surfaced 共存）的
实际场景。混合 case 是关键回归——确认了健康规则的存在不会让 doctor 把
HM-401 静默掉，stale / never-surfaced 计数也分开输出而不是合并成单一数字。

实跑验证：在真实开发数据（v0191_recover 项目，0 confirmed rules）下
`python -m harness_mem.cli doctor` 不显示 "Rule quality:" 行——这是
正确行为，零规则的项目无可报告。HM-401 的实际触发要等 v2.0 LLM-driven
distill 在真实使用中产生足够多的 confirmed rules 后才会自然出现。

scenario 8 实证：周明远场景里"Tauri v1 → v2 升级，老 IPC 规则现在错了"的
一步纠错路径已打通。内部 `cmd_correct(..., supersedes_rule_id=...)`
和 MCP `suggest_correction(...)` 走同一份 Python 逻辑，老规则 valid_to 设置 +
supersede 链建立 + 默认 list_confirmed_rules 不再返回老规则，include_history
仍可审计。


scenario 9 实证：在 v2.0 周明远 / Cursor field test 中暴露的"agent 把 CLI
命令丢给用户跑"问题，根因是缺少三个 MCP 工具：`set_active_project`、
`update_project_profile`、`wake`。这一组 scenario 直接通过 JSON-RPC
`handle_request` 走完一遍 agent 该做的 setup（设项目 → 写 profile → 增量再
写一次保 idempotent → wake 验证 convention 出现在输出里），并加一个 HM-501
（cwd 与 active project 不一致）的 doctor 测，覆盖正反两面：cwd 名字命中已
知项目时必须告警，cwd 是无关目录时必须沉默。


scenario 10 实证：v1.7.x 起 ConfirmedRule 已经记 usage_count + last_surfaced_at，
但用户从来没在 wake-up 输出里看到——只在 doctor 的"Rule quality"汇总里有体现。
现在每条 confirmed rule 在 wake 输出末尾带一个紧凑徽章："used 4×, last 2h ago"
或"never surfaced before"。徽章渲染的是 **pre-touch** 快照（这次 wake 之前的累
计值），而 wake 完成后再 touch，所以下次 wake 看到的是已经 +1 的数字——这是徽
章在连续 wake 之间保持诚实的关键。

scenario 11 实证：v5.5 的 `record_context_outcome` 是一个 outcome-aware
context loop，而不是 truth 写入捷径。测试先通过 MCP search 拿到 source id，
再用 MCP `record_context_outcome` 写 `used` / `misleading` signal，随后在
`weak_link_signals=True` 的 opt-in 项目里重新 search，验证两个结果都带
`ranking_explanation(kind=context_outcome)`，且 confirmed memory entry 数量不变。
这证明 outcome signal 能作为小幅、可解释、可关闭的排序提示，同时不静默修改 truth。

scenario 12 实证：v5.8 的 guided maintenance profile 是显式 opt-in 配置和
dry-run 预览，不是后台维护入口。测试通过 MCP `update_project_profile` 设置
`maintenance_profile=post-distill-metabolism`，随后 `get_project_status` 必须返回
active/suggested/available/dry_runs，并且每个 dry-run summary 都有
`candidate_counts` / `risk_level` / `auto_applied` / `needs_human_review` /
`undo_available`。同时 confirmed truth、pending candidates、RetrievalSignal 数量
保持不变，证明 profile dry-run 不会隐式运行 dream/metabolism，也不会写 truth。
