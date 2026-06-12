# Roadmap: harness-mem v3.7

> 状态：已完成。
>
> 主题：Skill Evolution Governance。让 skill 能被评估、修订、废弃和推广，但仍然走候选、
> evidence、review 和显式 activation。

---

## 目标

v3.7 不做默认 skill 自进化，也不把 shared skill 默认塞进 wake。它强化的是已存在
procedural memory 的治理闭环：

```text
confirmed skill
-> execution result / signal ledger
-> revision / deprecation / promotion candidate
-> review / confirm / reject
-> explicit search / compact hint / get_skill drilldown
```

参考线：

- `OpenSpace`：skill 生命周期、质量监控、token benchmark 和版本链。
- `Memento-Skills`：Read -> Execute -> Reflect -> Write 的学习循环。
- `evo`：run ledger、version drift、长任务状态。
- `claude-mem`：失败不阻断主任务，health 可诊断。

## 边界

- 不默认把 procedural skill 注入 wake。
- 不让 skill 自己改写 confirmed skill body。
- 不跨项目默认消费 shared skill；必须显式 `search_skills`、hint 或 drilldown。
- 不把一次失败直接等价为废弃；需要 evidence 和 review。
- 不绕过 `ProceduralCandidate`、`SkillPromotionCandidate`、revision/deprecation candidate。

## v3.7.0：Skill Outcome Ledger

**用户故事**：系统知道一个 skill 是否真的帮到了任务。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | result event detail | `record_skill_result` 记录 success/failure、surface、source ids、optional reason |
| P0 | health rollup | status 显示低成功率、长期未用、反复失败的 skill |
| P0 | non-blocking writes | 记录失败不阻断主任务 |
| P1 | privacy guard | result event 不保存 raw task content |

**实现说明**：MCP `record_skill_result` 支持 optional `surface`、`source_ids`、
`reason`，写入本地 `RetrievalSignal.context`；写失败仍不阻断主任务，且不保存 raw
task content。

## v3.7.1：Revision Candidate Quality

**用户故事**：skill 变差时，Agent 只能提出修订候选，不能静默改掉稳定 skill。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | revision suggestion evidence | suggestion 带 usage_count、success_rate、failure signal ids |
| P0 | no direct rewrite | confirm revision 不直接替换 skill body；必须进入 review / candidate surface |
| P0 | conflict explanation | 重叠或冲突 skill 给出 reason 和 source ids |
| P1 | human-readable diff | 修订建议能展示旧步骤、建议步骤和风险 |

**实现说明**：`detect_skill_improvements` 读取 skill outcome signals，生成
`skill_revision_suggestion` candidate；`confirm_skill_revision` 只接受 candidate 状态，
不直接替换 confirmed skill body。

## v3.7.2：Promotion and Portability Gate

**用户故事**：跨项目 skill 复用前，必须知道适用条件和禁用假设。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | portability metadata | promotion candidate 必填 portability notes / disabled assumptions |
| P0 | shared search explicitness | 默认项目 skill search 排除 shared scope；include/only 才返回 shared |
| P0 | wake boundary guard | skill hints 保持 opt-in compact，不渲染完整步骤 |
| P1 | origin tracing | shared skill 保留 origin_project、source_skill_id、source ids |

**实现说明**：`suggest_skill_promotion` 要求 portability notes / disabled assumptions；
默认 `search_skills` 排除 shared scope，只有 `shared_scope=include|only` 或显式 hint /
drilldown 才能消费 shared skill。

## v3.7.3：Skill Benchmark and Deprecation

**用户故事**：skill 库增长后，系统能发现没用、冲突或低质量的 skill。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | skill benchmark taxonomy | 按 activation accuracy、task success、token cost、failure rate 分类 |
| P0 | deprecation candidate | stale/conflicting shared skill 只生成 deprecation candidate |
| P0 | undo/restore path | retire 行为保留 ledger 和可恢复信息 |
| P1 | release report | status/report 展示 skill health trend |

**实现说明**：`detect_skill_deprecations` 只生成 `skill_deprecation_suggestion`；
确认后把 shared skill 标记为 `retired`，保留 ledger/source 信息和恢复余地。

## 一句话

v3.7 让 skill evolution 可治理：可以自动发现问题、提出候选和记录结果，但不能默认污染 wake，
也不能静默修改 confirmed skill。
