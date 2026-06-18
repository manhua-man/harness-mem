# Maintainer：功能面精简审阅（Gstack 正式审阅）

> **Maintainer working note — not user-facing.**
>
> 审阅模式：**gstack `/plan-ceo-review` — SCOPE REDUCTION** + **`/plan-eng-review` Step 0**
> + **CCGS `scope-check` 口径**。
>
> 核对日期：**2026-06-18** · 当前 package **`5.8.0`** · MCP 工具数：**60** full / **28** minimal（`python -c "from harness_mem.mcp.server import TOOLS; len(TOOLS)"` 核实）。
>
> **目的**：在 **不删实现** 前提下，减少 Agent `tools/list` 噪音与文档叙事重叠；**不是**删除代码清单。

---

## GSTACK REVIEW REPORT

| Review | Mode | Status | Findings |
|--------|------|--------|----------|
| CEO Review | **SCOPE REDUCTION** | **CLEARED** | 核心问题 = 暴露面过宽，非功能无用；禁止删 truth 环 |
| Eng Review | **Step 0 only** | **CLEARED** | `tools/list` 过滤可行；8+ 文件 smell 可控；无新子系统 |
| Scope-check | — | **CONCERNS → PASS if Tier 1 shipped** | 净 scope 变化应限于「藏」+ 文档，不删 handler |

**VERDICT：CLEARED for Tier 1 plan — 实施 `minimal` profile + 文档分工；不合并 confirm/reject；不删 reflection 实现。**

---

## Step 0：前提挑战（CEO）

| 问题 | 结论 |
|------|------|
| 这是真问题吗？ | **是。** `tools/list` 返回 60 个 schema；Agent 易误调 maintainer / governance 工具。不是「代码多余」，是 **proxy 问题**（工具数 ≠ 产品价值）。 |
| 用户 outcome？ | Agent **更快选对工具**、更少 maintainer 误调用；用户无感的子系统 **不应占 list 前排**。 |
| 不做会怎样？ | v5.6 仍可用；context 税与误调用持续；已在 v5.8 通过 profile 收口。 |
| 12 个月理想态？ | 同一 runtime：**full 能力在代码里，minimal 暴露在 list 里**；truth / SearchBackend 不变。 |

**Focus as subtraction（默认少做）：**

- **减**：`tools/list` 默认认知负担、文档重复叙事。
- **不减**：handler 实现、OpenSpec 契约、truth confirm/reject 显式动作、host opt-in 面。

---

## What already exists（Eng Step 0）

| 子问题 | 已有代码 | 重建？ |
|--------|----------|--------|
| 60 工具注册 | `tool_specs._SCHEMAS` + `server.TOOLS = build_tools({...})` | **否** — 在 `tools/list` 过滤 |
| list 全量返回 | `server.py` `tools/list` 遍历 `TOOLS.items()` | **改这里** |
| call 任意已注册工具 | `tools/call` 查 `TOOLS` 全集 | profile 策略需定义（见决议） |
| reflection 只读 | `list_reflection_jobs`, `get_reflection_job` | 保留；minimal 不 list |
| skill 治理 | `detect_skill_*` + 8 个 confirm/reject + suggest/promotion | 保留；minimal 不 list |
| dream 组合维护 | `dream_run` 等已组合 metabolism/reflection | 用户路径走 **dream / v5.8 profile**，非 reflection MCP |
| 文档 non-goals | `roadmap-status.md` Tier 3 | 继续遵守 |

**创新 token（McKinley）：** v5.x 已花 token 在 Storage v2 / SearchBackend / evidence。**Tier 1 只花 0–1 个 token** — 优先 `list_tools` 过滤，**不**花 token 在 merge 工具 API。

---

## 实现方案对比（Step 0C — 三选一，已拍板）

| 方案 | 摘要 | Effort | Risk | 决议 |
|------|------|--------|------|------|
| **A0 仅文档** | 用户向「主路径工具」表 | S | 无 | **立刻做**（v5.8 文档切片） |
| **A1 `MCP_TOOL_PROFILE`** | `minimal\|full`，`tools/list` 过滤 | M | 低 | **v5.8 已做**；默认 `full` |
| **A2 双 MCP server** | 两套入口 | L | 中 | **NOT IN SCOPE** |
| **B1 合并 detect** | `skill_governance_scan` | M | breaking | **defer 5.9+** |
| **B2 合并 confirm** | 单 `resolve_*` | — | 高 | **否决**（truth 宪法） |
| **B3 minimal 隐藏 governance** | 无 API 变更 | S | 无 | **随 A1** |

**RECOMMENDATION：A0 + A1 + B3；reflection 不合并（B3 only）。Completeness：9/10。**

---

## Tier 分层（SCOPE REDUCTION 产出）

### Tier 0 — 产品宪法（禁止删、禁止 merge confirm/reject）

- candidate → review → **显式** confirm/reject
- `search_memory` + `wake` + SearchBackend 主链
- `prepare_session_distill` + `suggest_*`（学习入口）
- `temporal_query` + supersede 链
- canonical SQLite + migration/export

### Tier 1 — 藏深一点（本审阅主交付）

| 面 | 证据 | 决议 |
|----|------|------|
| 60 tools 全 list | `tools/list` 无 filter | **A1** minimal profile |
| reflection ×2 | host 默认 off；dream 已组合 | **不合并**；minimal 不 list |
| skill governance ×12 | 无 procedural 用户无感 | **不 merge confirm**；minimal 不 list；**可选** 5.8 profile 内调 detect |
| `trace_relations` vs `temporal_query` | 能力不同、叙事重叠 | **文档分工**（v5.7 后）；minimal：保留 temporal，藏 trace |
| `search_raw` vs `search_memory` | spec 分工明确 | minimal 藏 search_raw |
| benchmark/cost 报告 ×3 | 发版 gate | minimal 不 list；roadmap-status 维护者材料 |
| `record_context_outcome` | 默认关 | minimal 不 list；标 experimental |
| dream/metabolism ×6 | opt-in | **minimal 不 list**（见决议 2） |

### Tier 2 — 兼容层（非「多余」）

- `read_api.search_memory` facade → v6+ 再谈 deprecate
- legacy JSON → 迁移路径保留

### Tier 3 — 已否决（勿复活）

REST 日常 API、CLI wake/search、daemon、wiki-as-truth、`deep_memory_search`。

---

## `minimal` 工具清单（Eng 核实，非「瞎猜 8 个」）

**说明：** 对外可说「**8 个主入口**」（search、wake、status、distill、candidates、auto_review、suggest、confirm 类）；**minimal profile 实际 28 个工具** —— 因 truth 环 **不能** 合并 confirm/reject。

### minimal 包含（28，含 `create_task_handoff`）

| 簇 | 工具 |
|----|------|
| 检索 / 上下文 (7) | `search_memory`, `wake`, `timeline`, `temporal_query`, `file_context`, `get_observations`, `get_confirmed_rules` |
| 项目 (3) | `get_project_status`, `get_project_profile`, `set_active_project` |
| 学习 (2) | `prepare_session_distill`, `ingest_sessions` |
| 候选 (2) | `list_candidates`, `auto_review_candidates` |
| suggest (5) | `suggest_memory_entry`, `suggest_rule`, `suggest_relation_fact`, `suggest_supersede`, `suggest_correction` |
| confirm/reject 主环 (8) | `confirm_memory_entry`, `reject_memory_entry`, `confirm_rule`, `reject_rule`, `confirm_relation_fact`, `reject_relation_fact`, `confirm_supersede`, `reject_supersede` |
| 协作 (1) | `create_task_handoff` |

（7+3+2+2+5+8+1 = **28**；60−28 = **32** 仅在 full profile 的 `tools/list` 中出现。）

### 用户向「主入口 8」（A0 文档用，≠ minimal 注册数）

1. `get_project_status`  
2. `search_memory`  
3. `wake`  
4. `prepare_session_distill`  
5. `list_candidates`  
6. `auto_review_candidates`  
7. `suggest_*`（族）  
8. `confirm_*` / `reject_*`（族）  

---

## 行为契约（Eng — 须写入 v5.8.3 spec）

| 项 | gstack 推荐 | Completeness |
|----|-------------|--------------|
| 默认 profile | **`full`** | 10/10 |
| `tools/list` | 按 profile 过滤 | 10/10 |
| `tools/call` 调 hidden 工具 | **结构化错误**（含 `profile=minimal` + 提示用 full 或工具名） | 9/10 |
| 配置来源 | env `HARNESS_MEM_MCP_TOOL_PROFILE` + 可选 `ProjectProfile.mcp_tool_profile` | 8/10 |
| 跨客户端 | v5.6 field-test packet + v5.8 profile smoke 记录 profile 口径 | 8/10 |

### 决议 2：minimal 里 dream/metabolism

**RECOMMENDATION：全部不进 minimal**；`get_project_status` / `next_actions` 可提示「维护请用 full profile 或 `/hm:dream`」。

理由（CEO subtraction）：dream 是 **opt-in 维护**，不是日常 read/search 环；放进 minimal 会复活「默认维护」叙事。

---

## NOT IN SCOPE（本审阅明确不做）

| 项 | 理由 |
|----|------|
| 删除任何 MCP handler | 无 telemetry；breaking |
| 合并 confirm/reject 系 | truth 宪法 |
| 合并 reflection list/get | 收益 1 工具，breaking，不值得 |
| `skill_governance_scan` merge detect | defer 5.9+；优先 A1 |
| 双 MCP server | 安装与文档翻倍 |
| 默认 `minimal` | 破坏现有集成假设 |
| 删 REST/CLI 残留以外的「代码考古」 | 非本审阅目标 |

---

## Scope-check 判决

| 指标 | 值 |
|------|-----|
| 原「删功能」冲动 | 0 项批准 |
| 暴露面缩减 | list 60 → **28**（minimal，**−53%** schema 体积） |
| 代码删除 | 0 |
| **Verdict** | **PASS**（A0+A1+B3 范围）；代码已实现，v5.8 release gate 已补 |

---

## Roadmap 挂接（已对齐 `roadmap-v58.md`）

| 切片 | 内容 |
|------|------|
| v5.8.0–5.8.1 | 养库（已定） |
| v5.8.2 | maintenance regression（可选） |
| **v5.8.3** | `MCP_TOOL_PROFILE` — **已实现并写入** [`roadmap-v58.md`](./roadmap-v58.md) |
| **A0 文档** | **已写入** [`how-it-works-visual-guide.md`](./how-it-works-visual-guide.md) 主入口 8 表 |
| v5.9+ | `skill_governance_scan`（仅当 full 仍吵且要 API 整理） |

---

## 已决议（2026-06-18，用户确认）

| # | 项 | 决议 |
|---|-----|------|
| 1 | 默认 profile + hidden call | **`full` 默认**；minimal 下 `tools/call` 调 hidden 工具 → **结构化错误** |
| 2 | dream/metabolism in minimal | **全部不包含**；维护走 full profile 或 `/hm:dream` |
| 3 | task_handoff / update_profile | **`create_task_handoff` 纳入 minimal（28 工具）**；`update_project_profile` 留 full — 已写入 `roadmap-v58.md` v5.8.3 |

---

## 相关文档

| 文档 | 用途 |
|------|------|
| [`roadmap-v58.md`](./roadmap-v58.md) | v5.8 实现挂接 |
| [`roadmap-status.md`](./roadmap-status.md) | non-goals |
| [`how-it-works-visual-guide.md`](./how-it-works-visual-guide.md) | A0 主入口表（已写） |
