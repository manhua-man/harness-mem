# Roadmap: harness-mem v2.7

> 状态：v2.7.0 已完成；v2.7.1 第一片已完成。
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

### 当前状态（2026-06-02）

- 已创建 `openspec/changes/v270-cross-project-skill-library/`。
- 已定义 scope model、promotion candidate、explicit shared search、
  project-specific precedence 与 provenance 边界。
- 已实现第一片 scope model：confirmed Skill 支持
  `scope=project|workspace|global`、`origin_project`、`source_ids`、
  portability metadata；旧 Skill 自动按 `scope=project` 迁移。
- 已实现 promotion candidate review loop：project skill 可以经由 reviewed
  `skill_promotion` candidate 提升为 workspace/global shared skill，且 review surface、
  confirm/reject 流程与 provenance metadata 已接通。
- 已实现 explicit shared search：MCP `search_skills` 支持显式
  `include_shared` / `shared_scope=include|only`，并保持默认 project-scoped 行为。
- shared-inclusive 搜索会让 project skill 排在 shared skill 前面，并继续返回
  scope/origin/source ids/portability metadata。
- shared skill 搜索结果现在会显式返回 `activation_warnings`，在 activation 前暴露
  portability notes 和 disabled assumptions。
- `record_skill_result` 对 project/shared skill 维持独立 usage feedback，不会互相污染。
- 默认 wake / skill search 仍不消费 shared skills。

### 首片实现验收：scope model

第一片 runtime slice 只建立 scope model 与兼容迁移边界，不启用跨项目消费：

- 新建 confirmed Skill 默认仍为 `scope=project`，并保留现有 project ownership、usage counters 与 search 行为。
- 旧 confirmed Skill 迁移后必须等价于 project-scoped skill；默认 wake 和默认 `search_skills` 不应出现 workspace/global skill。
- scope/provenance/portability 字段可以先落 schema/storage，但 promotion candidate 与 explicit shared search 仍按后续任务验收，不在本片隐式开启。

## v2.7.1：Controlled Skill Activation

**用户故事**：任务开始时，Agent 可以知道“可能有一个有用 skill”，但不会把完整步骤塞进每次 wake。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | compact skill hints | wake 只给 id/title/reason，不给完整 skill body |
| P0 | opt-in activation | hints 由 config / tool parameter / agent command 控制 |
| P0 | conflict handling | project-specific skill 与 shared skill 冲突时默认 project-specific 胜出 |
| P1 | usage feedback | `record_skill_result` 记录 hinted skill 是否被使用、是否有帮助 |
| P1 | budget isolation | skill hints 有独立预算，不挤占 essential rules |

### 当前状态（2026-06-02）

- 已创建 `openspec/changes/v271-controlled-skill-activation/`。
- 已实现 opt-in compact skill hints：MCP `wake` 支持
  `include_skill_hints` / `skill_hint_limit`，默认 wake 不变。
- hint 输出只包含 id/title/reason，不会内联 procedural steps。
- 已新增 MCP `get_skill`，让 agent 可以按 id 显式展开完整 skill body。
- skill hints 采用独立小预算，并单独显示 token 估算，不挤占 L0/L1/L2。

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
