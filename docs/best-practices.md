# harness-mem 最佳实践 (v1.4+)

## 1. 核心架构：4 角色协作

harness-mem 不仅仅是一个工具，它定义了一套 AI 参与的记忆生命周期。

| 角色 | 职责 | 主要交互方式 |
|------|------|-------------|
| **User (用户)** | 提出目标，进行最终决策。 | 自然语言 / CLI |
| **Executor (执行者)** | 完成具体的编码或研究任务。 | MCP 工具调用 |
| **Gardener (园丁)** | 维护记忆健康：distill、purge、关联条目。 | CLI (`distill`/`purge`) |
| **Memory Expert (专家)** | 决定哪些知识应固化为长期规则。 | MCP / CLI (`rules`) |

---

## 2. 候选层 (Candidate Layer) 机制

**核心原则：AI 建议，人类（或 Gardener）确认。**

为了保证记忆库的信噪比，所有由 AI 产生的结构化知识（MemoryEntry, Rule, Relation）都应先进入“候选层”（状态为 `pending`）。

- **Executor 行为**：在任务结束或发现关键决策时，使用 `suggest_memory_entry` 或 `create_task_handoff`。
- **Gardener/User 行为**：定期运行 `harness-mem candidates` 或在对话中使用 `confirm_rule` 将知识固化。

---

## 3. MCP 工具全集 (AI 视角)

Executor 应根据场景自主选择工具：

| 类别 | 工具名 | 最佳使用场景 |
|------|--------|------------|
| **读取** | `search_memory` | 寻找特定知识、代码约定或过往 bug 记录。 |
| | `timeline` | 回溯当前项目的开发脉络。 |
| | `get_task_handoffs` | 在开始新任务前，恢复上一个 Session 的断点。 |
| | `get_confirmed_rules` | 检查本项目必须遵守的硬性约束。 |
| **写入** | `suggest_memory_entry` | 记录新发现的事实、架构决策或 API 变动。 |
| | `create_task_handoff` | Session 结束前，记录进度、下一步计划和阻塞点。 |
| | `suggest_rule` | 发现需要长期遵守的模式（如：禁止使用某库）。 |
| | `suggest_relation_fact` | 建立实体间的关联（如：A 模块依赖 B 配置）。 |
| **管理** | `confirm_rule` / `reject_rule` | 在 User 明确要求后，操作候选规则的状态。 |

---

## 4. 日常流 (Workflow)

### 4.1 开启新 Session (Wake-up)
AI 应在启动时自动调用 `wake-up` 逻辑（通常由客户端集成完成），或由 User 运行：
```bash
harness-mem wake
```
**目标**：将 Profile、Rules 和最近的 Task Handoffs 注入 Context。

### 4.2 任务切换与交接
在 Executor 完成阶段性工作后，应主动调用：
```bash
# AI 通过 MCP 调用 create_task_handoff
# 或用户手动：
harness-mem handoff
```

### 4.3 记忆维护 (Gardener 职责)
建议每周进行一次“园艺工作”：
1. **蒸馏**：`harness-mem distill` — 将 verbatim observations 转化为结构化条目。
2. **清理**：`harness-mem purge --dry-run` — 发现并压缩陈旧、低频的记忆。
3. **诊断**：`harness-mem doctor` — 检查项目健康度。

---

## 5. 搜索与检索优化

- **自动模式 (`--mode auto`)**：优先尝试 Hybrid Search（向量+全文），若环境不支持则无缝回退至 FTS。
- **代码符号搜索**：对于类名、函数名，建议强制使用 `fts` 模式。
- **意图/概念搜索**：对于“如何处理认证”等模糊查询，建议使用 `hybrid` 模式。

---

## 6. 高级技巧

- **跨项目搜索**：使用 `scope="all"` 可以在所有已知项目中检索通用知识。
- **溯源 (Provenance)**：每条记忆条目都带有 `source` 标记，可以通过 `harness-mem show <obs-id>` 查看其产生的原始语境。
- **自定义 Profile**：通过 `harness-mem profile --edit` 维护 `key_files` 和 `conventions`，这是 `wake-up` 时最重要的静态权重。

---

## 7. 历史记忆激活 (Legacy Activation)

如果你拥有大量的 Codex 历史归档（`rollout-*.jsonl`），可以将它们作为“冷启动”知识库注入新项目。

- **批量导入**：
  ```bash
  harness-mem ingest codex-archive -n 20
  ```
- **工作流建议**：
  1. 导入后，运行 `harness-mem status` 确认观察记录已入库。
  2. 运行 `harness-mem distill`，AI 会自动从历史 Transcript 中提取 `MemoryEntry`。
  3. 历史记忆会带有 `archive` 标签，方便在搜索时识别溯源。

---

## 总结：AI 原生记忆法则

1. **先搜索，再行动**：利用 `search_memory` 避免重复犯错。
2. **事毕必有交接**：`create_task_handoff` 是防止上下文丢失的唯一防线。
3. **拥抱候选层**：不要害怕生成太多的 `pending` 条目，Gardener 会处理它们。
