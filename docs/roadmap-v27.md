# Roadmap: harness-mem v2.7

> 状态：规划中。
>
> 主题：Cross-Project Skills and Controlled Activation。让可复用 procedural knowledge 跨项目流动，但必须显式、带边界、可审核。

---

## 目标

v2.7 处理原先放在 v2.4 的跨项目 Skill 方向。它被后移的原因是：没有 v2.5 的 context assembly 和 v2.6 的 compact index，跨项目 Skill 只会变成一批可搜索对象，还不是真正可控的 agent memory 能力。

这一版只做显式复用，不做静默跨项目注入。

---

## 技术来源

- harness-mem v1.8：`ProceduralCandidate`、confirmed `Skill`、`search_skills`、`record_skill_result`。
- harness-mem v2.3：skill result signals。
- harness-mem v2.5：context assembly / skill hint budget。
- harness-mem v2.6：source / provenance / compact index。

---

## Scope

| 领域 | v2.7 决策 |
|---|---|
| Skill Scope | project / workspace / global |
| Promotion | project skill 只能通过 candidate 提升 |
| Activation | 默认只给 compact hints，完整 skill 需显式请求 |
| Conflict | project-specific 胜过 shared |
| Provenance | shared skill 必须显示 origin project 和 evidence |

---

## v2.7.0：Cross-Project Skill Library

**用户故事**：一个 repo 学到的 release hygiene skill 可以被另一个 repo 借用，但不会把项目特定细节乱套过去。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | skill scope model | `scope = project | workspace | global`，带 origin project |
| P0 | promotion candidate | project skill 提升为 shared skill 必须经过 review |
| P0 | portability notes | shared skill 带适用条件、禁用假设、迁移说明 |
| P1 | cross-project search | 只有 Agent workflow 显式请求时才包含 shared skills |
| P1 | provenance display | 输出 origin project、source ids、confirm history |

## v2.7.1：Controlled Skill Activation

**用户故事**：任务开始时，Agent 可以知道“可能有一个有用 skill”，但不会把完整步骤塞进每次 wake。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | compact skill hints | wake 只给 id/title/reason，不给完整 skill body |
| P0 | opt-in activation | hints 由 config / tool parameter / agent command 控制 |
| P0 | conflict handling | project-specific skill 与 shared skill 冲突时默认 project-specific 胜出 |
| P1 | usage feedback | `record_skill_result` 记录 hinted skill 是否被使用、是否有帮助 |
| P1 | budget isolation | skill hints 有独立预算，不挤占 essential rules |

## v2.7.2：Skill Improvement Suggestions

**用户故事**：低成功率或重复失败的 skill 可以提出改进建议，但不能自动改写已确认 skill。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | low-success skill detector | 基于 success/failure signals 生成 revision candidate |
| P0 | revision provenance | 改进建议带失败案例和反例 |
| P0 | no auto-rewrite | confirmed skill 不被静默覆盖 |
| P1 | deprecation suggestion | 长期不用或冲突的 shared skill 生成 deactivate candidate |

---

## Non-Goals

- 不默认跨项目搜索 skill。
- 不把完整 skill body 放进默认 wake。
- 不无审核提升 project skill。
- 不无审核改写 confirmed skill。
- 不做 always-on skill learner。

