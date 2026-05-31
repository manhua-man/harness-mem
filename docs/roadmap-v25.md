# Roadmap: harness-mem v2.5

> 状态：进行中。v2.5.0 (Context Assembly Plan) + v2.5.1 (Wake Renderer Hardening) 已完成；v2.5.2 (File Context) 已实现，待版本收口 / 发版。
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

## v2.5.0：Context Assembly Plan ✅

> 状态：已完成 (2026-05-31)。交付物：`ContextAssemblyPlan` schema（`harness_mem/core/schemas/context_assembly_plan.py`）+ side-effect-free `assemble_context_plan(...)`（`harness_mem/context_assembly.py`）。

**用户故事**：Agent 开始任务时，不只是拿到一堆记忆，而是知道每条上下文为什么出现。

| 优先级 | 任务 | 验收 | 状态 |
|---|---|---|---|
| P0 | `ContextAssemblyPlan` | 输出层级、预算、source ids、why-included | ✅ |
| P0 | L0 profile / identity | project profile、active project、runtime boundary 常驻小预算 | ✅ |
| P0 | L1 essential truth | confirmed current rules / high-confidence memory entries | ✅ |
| P0 | L2 active task | recent handoff、recently surfaced relevant truth | ✅ |
| P1 | L3 topic recall | 基于 query/task 的 compact search results | ✅ |
| P1 | L4 raw evidence drilldown | 只返回 source ids 和展开指针，不默认塞全文 | ✅ |

## v2.5.1：Wake Renderer Hardening ✅

> 状态：已完成 (2026-05-31)。交付物：纯函数渲染模块 `harness_mem/commands/wake_render.py` + 计划驱动的 `cmd_wake_up`。`ContextAssemblyPlan` schema 与 Plan_Assembler 选择逻辑未改动。

**用户故事**：wake 输出可读、稳定、可追溯，并且不会让历史 observation 淹没当前任务。

| 优先级 | 任务 | 验收 | 状态 |
|---|---|---|---|
| P0 | layer-specific budgets | 每层有硬上限和截断说明（`TruncationAccounting` 来源的 dropped 计数） | ✅ |
| P0 | source id display | 每条 entry 逐字符显示 source id（`render_source_id_display`）+ `📍` 出处标记 | ✅ |
| P0 | stale exclusion | L1/L2 只渲染 `truth_status == confirmed_current`；historical/pending 排除或醒目标注 | ✅ |
| P1 | relation compact render | relation facts 归 L3（query-driven）；无 query 的 cold-start wake 不渲染（经 `search` 检索） | ✅（按 L3 边界实现） |
| P1 | skill hint render | skill 只在 L3 给 compact hint（id/title/reason），cold-start wake 不注入完整步骤 | ✅ |

**实现说明**：cold-start `wake`（无 query）只渲染 L0/L1/L2，固定顺序。被取代的旧扁平格式（`# Confirmed Rules` / `# Relation Facts` / `# Memory Entries` / bucket-quota 块 / weak-link 子标题 / 使用徽章）改为分层渲染——confirmed rules 与 accepted current-truth entries 在 L1 出现，relation facts 与 skill hints 属 L3 查询驱动层。既有 `wake_surfaced` 信号 + 使用计数 touch、MCP stdout 纯净性完好保留。

## v2.5.2：File Context ✅（实现完成，待发版）

> 状态：代码已实现（2026-05-31），版本号 / 发布说明尚未收口。交付物：`harness_mem/core/schemas/file_context.py`、`harness_mem/file_context.py`、MCP `file_context` tool、focused tests（`tests/test_file_context.py`、`tests/test_file_context_readonly.py`、`tests/mcp/test_file_context_stdout.py` + `tests/mcp/test_smoke.py` 更新）。

**用户故事**：读大文件前，Agent 可以先问“这个文件历史上有什么重要记忆”，但读取行为不被强行阻断。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | `file_context(path)` helper / MCP tool | 返回相关 observations、rules、recent edits、source ids | ✅ |
| P0 | cost hint | 返回预计展开成本和可选 drilldown | ✅ |
| P0 | no blocking default | 不拦截 Read；只作为显式建议或工具 | ✅ |
| P1 | stale file signals | 能提示历史记忆可能过期 | ✅ |
| P1 | tests with renamed files | 文件路径变化时不产生误导性强断言 | ✅ |

**实现说明**：`file_context` 复用现有读面，不新增 search engine 或存储读路径：`ProjectProfile` 通过 `LocalProjectProfileStore` 读取，observation 关联走 `read_api.regex_search_observations(...)`，memory truth 走 `read_api.search_memory(..., record_signals=False, include_history=True)`，skills 走 `read_api.search_skills(...)`，recent edits 走 `get_latest_handoffs(...)`。结果是只读 `FileContextResult`：每条 `FileContextItem` 带 `source_ids`，raw evidence 用 `DrilldownPointer`，skill 只给 compact hint，不注入 full steps。

**边界说明**：v2.5.2 不拦截文件读取、不发 `RetrievalSignal`、不 bump `usage_count` / `last_accessed_at`、不写 compact cache、不生成 stale/contradiction suggestion records，也不改 `ContextAssemblyPlan` / `assemble_context_plan(...)` / v2.5.1 wake renderer。

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
