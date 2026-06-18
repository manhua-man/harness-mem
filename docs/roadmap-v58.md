# Roadmap: harness-mem v5.8

> 状态：**已发布**（当前 package v5.8.0；基线版本 v5.6.0；v5.8.0 的 `ProjectProfile.maintenance_profile`
> + `get_project_status` dry-run 摘要已接线，v5.8.1 的 source-hash incremental
> skip 已接线，v5.8.2 maintenance regression smoke 已补，v5.8.3 MCP tool profile 已接线）。
>
> 主题：**Guided Opt-in Maintenance + Generated Incremental Compile + MCP Tool Profile**。
> 养库（opt-in profile、增量 compile）+ 降低 Agent `tools/list` 噪音（gstack Tier 1 审阅）；
> 不引入常驻 daemon、不删 MCP handler、不做 truth 自治改写。

---

## 一句话

v5.8 解决 **「库长大了怎么养」** —— 在 v5.4 `maintenance_summary` 和 v3.1 Auto Dream 之上，
提供可复制的维护预设与增量 generated 编译，降低长库 opt-in 维护成本。

```text
v5.6–5.7 重点：查得对、钻得深（主路径 + 时序）
v5.8 重点：养得起（opt-in 维护 + 增量 compile）+ 列表不吵（minimal MCP profile）
```

## 为什么现在做

| 痛点 | v5.6 现状 | v5.8 目标 |
|---|---|---|
| 维护入口散 | dream / metabolism / undo 有 summary，但用户不知「该开哪套」 | named profile 一键说明会动什么、可 undo 什么 |
| generated 全量重编慢 | `rebuild-wiki-bridge` 可显式重建，大库成本高 | source hash 变更才重编相关 claims |
| 十维 ⑨ 差距 | guided maintenance 有摘要，弱于 ai-harness「一键每周」体验 | 用 **opt-in 预设** 补齐，不上 daemon |
| 证据纪律 | v5.6 field-test 偏日常 flow | 增加「开 profile → dream → undo」回归切片 |

gstack 审阅：**5.8 用户体感强、创新 token 低**；与 v5.7 无硬依赖，但建议 v5.7 先发以免维护与主路径 drilldown 形状不一致。

## 产品原则

1. **Opt-in only**：scheduler / host hook / Auto Dream 仍默认 off；profile 只改变「用户显式开启后」的行为组合。
2. **Truth governance 不变**：profile 触发的变更仍走 candidate / review / supersede / ledger；dream undo 仍可用。
3. **Generated ≠ truth**：增量 compile 只更新 generated layer；不进默认 wake truth surface。
4. **Explain before run**：每个 profile 在 `maintenance_summary` 或 `get_project_status` 中预告 `candidate_counts`、`risk_level`、`undo_available`。
5. **Artifact-backed**：新行为登记 benchmark matrix slice，不写成公开性能 claim。

## 边界（明确不做）

| 不做 | 理由 |
|---|---|
| always-on daemon / 默认 scheduler on | roadmap-v24 / v5.4 纪律 |
| outcome-aware decay / 自动 archive | v5.5 signal-only 边界 |
| wiki 产品化 / meta-kb 级 ingest | reference-projects.md |
| 独立 maintenance CLI 日常入口 | v2.1 已收口到 MCP + `/hm:*` |
| 扩写十维对比文档 | 非用户价值 |

## v5.8.0：Guided Maintenance Profiles

**用户故事**：我想每周做一次低风险维护，但不想自己拼 config.toml + dream + metabolism 参数。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | profile 注册表 | **已发布**：内置 `weekly-dream`、`post-distill-metabolism`；每项含 enabled 门控、触发的 MCP/维护面对、风险说明 |
| P0 | profile 应用入口 | **已发布（config 路径）**：`ProjectProfile.maintenance_profile` 可由 `update_project_profile` 设置；`get_project_status` 返回应用前 dry-run 摘要；不新增 MCP tool，避免破坏 v5.8.3 的 60/28 工具数 |
| P0 | `maintenance_summary` 对齐 | dream / metabolism / undo 在 profile 运行后返回统一 summary（复用 v5.4 形状） |
| P1 | `get_project_status` hint | **已发布**：返回 available / active / suggested profiles 与 dry-run `maintenance_summary`（非自动执行） |
| P1 | host 模板注释 | `triggers.*` 文档示例：「若开启 cron，推荐绑定 weekly-dream」 |

**实现锚点**：`maintenance_summary`（v5.4）、`tool_dream_run` / `tool_metabolism_run`（v3.1 / v2.3）、`ProjectProfile`、host_entry 模板。

## v5.8.1：Generated Incremental Compile

**用户故事**：distill 或 truth 小改后，不想全量 `rebuild-wiki-bridge` 等几分钟。

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | incremental compile 路径 | **已发布**：`rebuild_wiki_bridge(incremental=True)` / `maintenance rebuild-wiki-bridge --incremental` 在 source hash 未变时跳过 generated 输出重写 |
| P0 | metrics 可见 | **已发布**：`knowledge_cache_health` / `get_project_status` 暴露 `last_compile_at`、`incremental_compile`、`skipped_source_count`；不写性能收益 claim |
| P1 | profile 钩子 | `post-distill-metabolism` profile 可在 metabolism 后触发 incremental compile（仍 opt-in） |
| P1 | v5.7 drilldown 对齐 | stale claim drilldown 形状与 v5.7 contract 一致（若 v5.7 已发） |

**实现锚点**：`knowledge_cache.py` source hash、`rebuild_wiki_bridge`（v2.6 / v3.2）。

## v5.8.2：Maintenance Regression Slice（可选，不阻塞 5.8.0）

| 优先级 | 任务 | 验收 |
|---|---|---|
| P1 | benchmark 登记 | `guided_maintenance_profiles` 或等价 collection 进入 benchmark suite |
| P1 | smoke 扩展 | **已补**：`tests/loop_harness/test_guided_maintenance_profiles.py` 覆盖 profile dry-run summary 字段与 truth/candidate/signal 不变量 |
| P2 | field-test 附录 | v5.6 packet 增一节「opt-in weekly-dream」脚本（maintainer 材料） |

## v5.8.3：MCP Tool Profile（gstack Tier 1）

**用户故事**：Agent 连接 MCP 时不必读 60 个工具 schema；日常会话用 **minimal** 列表即可；
维护 / governance / 发版报告留在 **full**。

**审阅依据**：[`maintainer-feature-surface-trim.md`](./maintainer-feature-surface-trim.md)（gstack SCOPE REDUCTION，2026-06-18）。

**已决议（用户确认）**

| 项 | 决议 |
|---|---|
| 默认 profile | **`full`**（不破坏现有集成） |
| minimal 下 `tools/call` 调 hidden 工具 | **结构化错误**（含 profile 名 + 提示切换 full） |
| dream / metabolism | **不进** minimal；`get_project_status` 可 hint 用 full 或 `/hm:dream` |

| 优先级 | 任务 | 验收 |
|---|---|---|
| P0 | profile 配置 | `HARNESS_MEM_MCP_TOOL_PROFILE=minimal\|full`；可选 `ProjectProfile.mcp_tool_profile` 覆盖 |
| P0 | `tools/list` 过滤 | minimal 仅返回下表 **28** 个工具；full 返回全部 **60** |
| P0 | hidden call 错误体 | 稳定 JSON/`HM-xxx` 形状；测试覆盖至少 2 个 hidden 工具 |
| P0 | cluster 元数据 | `tool_specs` 登记 cluster：`core_read`, `truth_loop`, `maintenance`, `governance`, `maintainer`, `advanced` |
| P1 | 用户文档 A0 | [`how-it-works-visual-guide.md`](./how-it-works-visual-guide.md)「主入口 8」表（可与 5.8.3 代码并行先发） |
| P1 | field-test 记一笔 | v5.6 packet 注明测试时使用的 profile |
| P2 | `create_task_handoff` | 纳入 minimal（见下表）；若实现前发现冗余可退回 full only |

### minimal profile 工具清单（28）

| 簇 | 工具 |
|---|---|
| 检索 / 上下文 (7) | `search_memory`, `wake`, `timeline`, `temporal_query`, `file_context`, `get_observations`, `get_confirmed_rules` |
| 项目 (3) | `get_project_status`, `get_project_profile`, `set_active_project` |
| 学习 (2) | `prepare_session_distill`, `ingest_sessions` |
| 候选 (2) | `list_candidates`, `auto_review_candidates` |
| suggest (5) | `suggest_memory_entry`, `suggest_rule`, `suggest_relation_fact`, `suggest_supersede`, `suggest_correction` |
| confirm/reject 主环 (8) | `confirm_memory_entry`, `reject_memory_entry`, `confirm_rule`, `reject_rule`, `confirm_relation_fact`, `reject_relation_fact`, `confirm_supersede`, `reject_supersede` |
| 协作 (1) | `create_task_handoff` |

**full only（32，不在 minimal list）**：含 `search_raw`, `trace_relations`, 全部 skill governance、
dream/metabolism、`list_reflection_jobs` / `get_reflection_job`、
`health_summary`, `surface_cost_report`, `benchmark_matrix_report`、
`record_context_outcome`, `update_project_profile`, `get_task_handoffs` 等。

**明确不做（v5.8.3）**：合并 confirm/reject API；合并 reflection；删除 handler；默认 minimal；
双 MCP server；`skill_governance_scan`（defer 5.9+）。

**实现锚点**：`server.py` `tools/list` / `tools/call` profile gate、`build_tools` / `tool_specs` 的 minimal 清单与 cluster metadata。

## Release Gate

- `python -m pytest -q`
- `python -m ruff check .`
- `python -m mypy harness_mem`
- Focused tests：profile dry-run、incremental compile 正确性、undo 不变量、maintenance_summary 形状、**minimal/full list_tools 与 hidden call 错误**
- 文档：`roadmap-status.md`、`CHANGELOG.md` v5.8.0 段（5.8.3 已随同一 train 收口）

## 与相邻版本

| 版本 | 关系 |
|---|---|
| v5.7 | 建议先发；5.8.1 drilldown 与 5.7 contract 对齐 |
| v5.9 | 独立线（成本/检索证据）；不阻塞 5.8 |
| v6.0 | **暂定**（可搬运 + 多项目）；5.8 不依赖 6.0 |

## 参考文档

| 文档 | 用途 |
|---|---|
| [`roadmap-v31.md`](./roadmap-v31.md) | Auto Dream |
| [`roadmap-v32.md`](./roadmap-v32.md) | Generated compiler |
| [`roadmap-v57.md`](./roadmap-v57.md) | Temporal drilldown（上游可选） |
| [`maintainer-feature-surface-trim.md`](./maintainer-feature-surface-trim.md) | gstack Tier 1 审阅与 minimal 清单 |
| [`roadmap-status.md`](./roadmap-status.md) | non-goals |
