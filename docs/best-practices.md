# harness-mem 最佳实践 (v1.4+)

## 1. 核心架构：AI-led Candidate Loop

harness-mem 不仅仅是一个工具，它定义了一套 AI 参与的记忆生命周期。

| 角色 | 职责 | 主要交互方式 |
|------|------|-------------|
| **User (用户)** | 提出目标，复核最终摘要并纠错。 | 自然语言 / Slash |
| **Executor (执行者)** | 完成具体的编码或研究任务。 | Slash / Skill / Agent 自然语言入口 |
| **Gardener (园丁)** | 维护记忆健康：ingest、distill、auto-review、purge、关联条目。 | `/hm:distill` / Skill；CLI 仅排障 |
| **Memory Expert (专家)** | 判断候选价值，自动确认低风险事实、拒绝噪声，把高风险项留给用户。 | MCP (`list_candidates` / `confirm_*` / `reject_*`) |

---

## 2. 候选层 (Candidate Layer) 机制

**核心原则：AI 先建议，AI 再处理大部分，人类只做最终复核与纠错。**

为了保证记忆库的信噪比，所有由 AI 产生的结构化知识（MemoryEntry, Rule, Relation）都应先进入“候选层”（状态为 `pending`）。

- **Executor 行为**：在用户明确要求记录、或 `/hm:distill` / Skill 流程中发现关键决策时，使用 `suggest_memory_entry` 或 `create_task_handoff`。
- **Gardener 行为**：`/hm:distill` 应在同一轮通过 MCP `list_candidates` 读取候选，自动确认低风险长期事实，拒绝工具噪声、跨项目 workflow、泛泛原则、重复项或证据不足项。
- **User 行为**：查看 `/hm:distill` 的最终摘要，指出处理不对的编号。`/hm:review` 只用于复查旧 pending、纠错或 MCP 异常后的手动补救，不是日常必经步骤。

---

## 3. Runtime 工具全集 (Agent 视角)

Executor 应根据场景自主选择工具：

| 类别 | 工具名 | 最佳使用场景 |
|------|--------|------------|
| **读取** | `wake` | 拉取当前项目的一等 wake-up 上下文；默认优先于手工拼低层读工具。 |
| | `search_memory` | 寻找特定知识、代码约定或过往 bug 记录。 |
| | `timeline` | 回溯当前项目的开发脉络。 |
| | `get_task_handoffs` | 在开始新任务前，恢复上一个 Session 的断点。 |
| | `get_confirmed_rules` | 检查本项目必须遵守的硬性约束。 |
| **写入** | `suggest_memory_entry` | 记录新发现的事实、架构决策或 API 变动。 |
| | `create_task_handoff` | Session 结束前，记录进度、下一步计划和阻塞点。 |
| | `suggest_rule` | 发现需要长期遵守的模式（如：禁止使用某库）。 |
| | `suggest_relation_fact` | 建立实体间的关联（如：A 模块依赖 B 配置）。 |
| **管理** | `list_candidates` | `/hm:distill` 自动审核候选前读取 pending 列表。 |
| | `confirm_rule` / `reject_rule` | AI 自动处理低风险规则；高风险项才留给 User 最终确认。 |

---

## 4. 日常流 (Workflow)

### 4.1 开启新 Session (Wake-up)
AI 应在启动时通过客户端集成或 MCP `wake(project_name=<project>)` 工具调用一等 wake-up surface。只有在用户明确要求 generated compact summary 或 procedural hint 时，才分别开启 `renderer="compact"` 或 `include_skill_hints=true`。不要把终端命令当成用户日常入口；CLI 只用于本地排障兜底。
**目标**：将 Profile、Rules 和最近的 Task Handoffs 注入 Context。

### 4.2 任务切换与交接
在 Executor 完成阶段性工作后，应主动调用：
AI 应通过 MCP `create_task_handoff` 记录任务交接；不要把终端 handoff 命令作为日常入口。

### 4.3 记忆维护 (Gardener 职责)
建议定期进行一次"园艺工作"：
1. **提炼与自动审核**：运行 `/hm:distill`。它应使用 `session-distill` Skill 做 AI 长程理解，并在同一轮自动确认低风险候选、拒绝噪声，最后给用户复核摘要。v2.0 后没有启发式兜底——distill 只接受 LLM agent。
2. **清理**：需要 cleanup 时先走显式 dry-run，由 Agent 解释范围后再执行。
3. **诊断**：需要本地排障时再运行 doctor；日常状态由 Agent 在背后读取 runtime status。

---

## 5. 搜索与检索优化

- **自动模式 (`--mode auto`)**：优先尝试 Hybrid Search（向量+全文），若环境不支持则无缝回退至 FTS。
- **代码符号搜索**：对于类名、函数名，建议强制使用 `fts` 模式。
- **意图/概念搜索**：对于“如何处理认证”等模糊查询，建议使用 `hybrid` 模式。

---

## 6. 高级技巧

- **跨项目搜索**：使用 `scope="all"` 可以在所有已知项目中检索通用知识。
- **溯源 (Provenance)**：每条记忆条目都带有 `source` 标记，应优先通过 MCP `get_observations` / `timeline` 查看其产生的原始语境。
- **自定义 Profile**：通过 MCP `update_project_profile` 维护 `key_files` 和 `conventions`，这是 `wake-up` 时最重要的静态权重。

---

## 7. 历史记忆激活 (Legacy Activation)

如果你拥有大量的 agent 历史归档或跨客户端会话记录，默认也只能把“当前项目路径相关”的会话注入新项目。agent 历史可能是用户级全局数据源，不能在项目目录里无脑全扫。

- **批量导入**：
  ```bash
  /hm:distill <project> 20
  ```
- **显式全局导入**：
  仅在开发者排障或用户明确要求跨项目历史时，让 Agent 执行跨项目 ingest，并在最终摘要里说明范围。
- **工作流建议**：
  1. 用户日常运行 `/hm:distill`；Agent 在背后一次性完成项目范围 ingest 并拿到 evidence packet。
  2. 需要高质量结构化记忆时，使用 `session-distill` Skill 读取 packet，再通过 `suggest_*` / `create_task_handoff` 写入候选层。
  3. 需要关闭、巡检或清理蒸馏资产时，用 `/hm:mark`、`/hm:prune`、`/hm:review-kb`、`/hm:prune-kb`、`/hm:verify-entry` 这些 Slash 管理入口；不要把底层脚本当作用户工作流。
  3. 写入候选后，`/hm:distill` 同一轮读取 `list_candidates`，自动确认低风险事实、拒绝噪声，只把真正高风险或证据不足项放进最终摘要。
  4. 历史记忆会带有 `archive` 标签，方便在搜索时识别溯源。

---

## 总结：AI 原生记忆法则

1. **先搜索，再行动**：利用 `search_memory` 避免重复犯错。
2. **事毕必有交接**：`create_task_handoff` 是防止上下文丢失的唯一防线。
3. **拥抱候选层**：不要害怕生成 `pending` 条目；`/hm:distill` 会自动处理大部分，用户只看最终摘要。


---

## 4. 接口纯净度（Interface Purity）

> 这是 harness-mem 作为"未来可被独立 UI 产品复用的底座"留下的隐性纪律。当前所有用例都是开发者编程记忆，不需要立即抽离；但每次写新代码时都应遵守，避免日后抽离成本积累。

### 原则

`harness_mem/core/interfaces/` 下的 Protocol（`MemoryBackend` / `VerbatimStore` / `StructuredStore` / `ProjectProfileStore`）是**底座对所有上层调用方的契约**。修改时问自己一个问题：

> **这个方法是"任何上层应用都需要的最小集"，还是"当前 CLI / MCP 应用的便利封装"？**

如果是后者，放到 `commands/`、`mcp/` 或 `tools/`，**不要污染 interface**。

### 判断准则

| 应放进 interface | 应放在 commands/ 或 mcp/ |
|-----------------|-------------------------------|
| `save_memory_entry(entry)` | `cmd_correct(...)`（先建 candidate 再调 save） |
| `search_memory_entries(query, scope)` | `cmd_search(...)`（含 UI 输出格式化） |
| `list_rule_candidates(project, status)` | `cmd_list_candidates(...)`（含 phase 行打印） |
| `update_rule_status(rule_id, status)` | `cmd_confirm_rule(...)`（含交互提示） |

### 反例：不该出现在 interface 的方法

- `format_memory_for_wake_output(...)` — 这是 wake 命令的 UI 逻辑，不是底座能力
- `print_status_summary(...)` — 任何含 `print` 的方法
- `get_default_project_name_from_cwd()` — 这是 CLI 便利封装，应放在 `commands/support.py`
- `wake_with_phase_label(...)` — phase 标签是 CLI 渐进披露 UX，不是底座契约

### 何时可以扩 interface

加 Protocol 方法的标准是"**任意一个未来 UI 产品都会需要这个能力**"。比如：

- ✅ 给 `MemoryEntry` 加时间字段（v1.7 bi-temporal）→ 任何 UI 都需要查 valid_from/valid_to
- ✅ 给 `StructuredStore` 加 `count_entries(project)` → UI 仪表盘必需
- ❌ 给 `MemoryBackend` 加 `quickstart_walkthrough()` → 这是 CLI onboarding 体验，UI 自有自己的引导流程

### 与"扩展性"的关系

**接口纯净度 ≠ 接口最小化**。该加的能力要加，避免每次都让上层自己拼装基础动作。但每加一个方法都要过"任意未来 UI 都用得上"这一关。如果只有当前 CLI 用得上，就放在调用方。
