# Roadmap: harness-mem v2.5

> 状态：规划中。
>
> 主题：Context Assembly + File Context。把已有记忆材料组装成可解释、可预算、可展开的上下文。

---

## 目标

v2.5 不再把 wake 看成“塞更多记忆”，而是把 raw observations、confirmed truth、rules、handoff、skills、relations 和 topic recall 组装成分层上下文。

这一版吸收 `claude-mem` 的 progressive disclosure 和 MemPalace 的 Memory Stack，但保留 harness-mem 的 accepted-only wake 和 evidence-first 边界。

---

## 技术来源

- `claude-mem`：先给 observation index，再按 ID 拉详情。
- MemPalace：L0/L1/L2/L3 memory stack 和 closet -> drawer 展开方式。
- harness-mem：`wake` bucket、`search_raw`、`timeline`、`get_observations`、`search_skills`、`trace_relations`。

---

## Scope

| 领域 | v2.5 决策 |
|---|---|
| Wake | 分层 context assembly，不追求全文注入 |
| File Context | 显式工具/建议层，不阻断文件读取 |
| Budget | 每层有预算和 why-included |
| Evidence | 每条摘要保留 source id，可按需展开 |
| Skills | 只给 compact hints，完整 skill 仍需显式 search |

---

## v2.5.0：Context Assembly Plan

**用户故事**：Agent 开始任务时，不只是拿到一堆记忆，而是知道每条上下文为什么出现。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `ContextAssemblyPlan` | 输出层级、预算、source ids、why-included |
| P0 | L0 profile / identity | project profile、active project、runtime boundary 常驻小预算 |
| P0 | L1 essential truth | confirmed current rules / high-confidence memory entries |
| P0 | L2 active task | recent handoff、recently surfaced relevant truth |
| P1 | L3 topic recall | 基于 query/task 的 compact search results |
| P1 | L4 raw evidence drilldown | 只返回 source ids 和展开指针，不默认塞全文 |

## v2.5.1：Wake Renderer Hardening

**用户故事**：wake 输出可读、稳定、可追溯，并且不会让历史 observation 淹没当前任务。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | layer-specific budgets | 每层有硬上限和截断说明 |
| P0 | source id display | 每条 memory/rule/relation/handoff 都有可追溯 id |
| P0 | stale exclusion | historical truth 默认不进 wake，只可通过 include_history / drilldown 查看 |
| P1 | relation compact render | 只渲染高置信短链路 |
| P1 | skill hint render | 只给 skill id/title/reason，不注入完整步骤 |

## v2.5.2：File Context

**用户故事**：读大文件前，Agent 可以先问“这个文件历史上有什么重要记忆”，但读取行为不被强行阻断。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `file_context(path)` helper / MCP tool | 返回相关 observations、rules、recent edits、source ids |
| P0 | cost hint | 返回预计展开成本和可选 drilldown |
| P0 | no blocking default | 不拦截 Read；只作为显式建议或工具 |
| P1 | stale file signals | 能提示历史记忆可能过期 |
| P1 | tests with renamed files | 文件路径变化时不产生误导性强断言 |

---

## Non-Goals

- 不做 wiki bridge。
- 不生成 contradiction / stale suggestions。
- 不把 compact render 写回 canonical storage。
- 不默认注入完整 procedural skill。
- 不替代 raw evidence search。

---

## 后续归宿

| 能力 | 后续版本 |
|---|---|
| source cache / generated knowledge cache | `docs/roadmap-v26.md` |
| compact claim index / closet-drawer | `docs/roadmap-v26.md` |
| cross-project skill / controlled activation | `docs/roadmap-v27.md` |

