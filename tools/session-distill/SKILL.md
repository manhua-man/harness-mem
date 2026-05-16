---
name: session-distill
version: 1.4.0
description: |
  利用 harness-mem 核心能力，将原始会话提炼为结构化记忆。
  当用户要求“整理对话”、“提取经验”或“固化项目规则”时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# Session Distiller (harness-mem 版)

## 1. 定位

`session-distill` 是从原始 transcript 到长期记忆的桥梁。在 v1.4.0 架构下，它不再依赖本地 packet 文件交换，而是直接驱动 `harness-mem` 的核心逻辑。

**核心职责：**
1. **接入**：通过 `harness-mem ingest` 发现并记录新的 Session。
2. **蒸馏**：通过 `harness-mem distill` 将非结构化对话转化为 `MemoryEntry`、`RuleCandidate` 和 `TaskHandoff`。
3. **审阅**：作为 **Gardener** 角色，利用 MCP 接口或 CLI 命令审阅候选条目。

---

## 2. 核心工作流

### 2.1 主链 (The Main Chain)
```text
Raw Sessions -> Ingest -> Observation Store -> Distill -> Candidate Layer (Pending) -> Review -> Confirmed Memory
```

### 2.2 AI 动作序列
1. **扫描新 Session**：
   ```bash
   harness-mem ingest claude-code -n 5
   ```
2. **触发结构化提取**：
   ```bash
   harness-mem distill
   ```
   *注意：此步骤会将知识存入本地数据库的候选层。*
3. **审阅候选规则**：
   使用 MCP 工具 `get_confirmed_rules` 或 CLI `harness-mem candidates` 查看待确认项。
4. **固化知识**：
   使用 MCP 工具 `confirm_rule` 或 `harness-mem confirm <id>`。

---

## 3. 协作工具 (Sibling Tools)

既然你在 `harness-mem/tools/` 目录下，可以根据场景调用兄弟工具：

| 工具 | 协作场景 |
|------|----------|
| `grill-me` | 对 `pending` 状态的候选规则进行压力测试（模拟对抗）。 |
| `answer-me` | 当蒸馏出的条目缺乏代码证据或配置示例时，进行补全。 |
| `mem-distill` | 处理已有的长期记忆，进行聚类、去重或合并。 |

---

## 4. 场景路由

| 场景 | 命令/入口 |
|------|----------|
| 刚结束一段复杂的对话 | `harness-mem ingest` + `harness-mem distill` |
| 发现记忆库太乱，有重复 | `harness-mem doctor` 或调用 `mem-distill` |
| 想要恢复之前的开发状态 | `harness-mem wake` -> 查看 `get_task_handoffs` |
| 需要清理陈旧记忆 | `harness-mem purge --dry-run` |

---

## 5. 最佳实践

- **增量蒸馏**：不要一次性处理所有历史 Session，建议每次 `ingest -n 5` 以保持上下文精准。
- **拥抱 Pending**：AI 在蒸馏时应多产生 `MemoryEntry(status="pending")`，留给 Gardener（人类或专项 AI）后续确认。
- **重视溯源**：在利用 `suggest_memory_entry` 时，务必填入正确的 `source` (Observation ID)，方便后续 `show` 追溯。

## 6. 环境依赖

- **数据中心**：`~/.harness-mem/data/`
- **核心包**：`pip install -e harness-mem`
- **MCP 入口**：`python -m harness_mem.mcp.server`
