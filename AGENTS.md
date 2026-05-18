---
description: AI Agent 指南 - 记忆系统架构、职责与协作真值
alwaysApply: true
---

# AGENTS.md（事 · Facts）

> 本文件定义 **harness-mem** 记忆系统的核心运行逻辑。
> 不同于传统搜索工具，本项目是一个 **AI 主导的记忆运行时**。

## 核心架构：AI 为中心的工作流

| 角色 | 最佳做法 |
| :--- | :--- |
| **AI（操作者 / 后端）** | 用 `tools/session-distill` 这类 **Skill** 批量读取旧 Session，做高质量提炼。 |
| **AI（操作者 / 随手）** | 用 **MCP** `suggest_rule` / `suggest_memory_entry` 记录即时规则和知识候选。 |
| **人（复核者）** | 日常只看 `/hm:distill` 的最终处理摘要并纠错；不负责逐条判断候选。CLI `candidates` / `confirm` / `reject` 只作为本地排障兜底。 |
| **AI（消费者）** | 用 **MCP** `search_memory` / `wake` 读取已确认记忆。 |

关键原则：**Skill 负责重脑力批处理，MCP 负责运行时读写和审核闭环，CLI 负责本地管理员兜底。** AI 提炼或随手记录的内容应先进入候选区；`/hm:distill` 同一轮应由 AI 自动确认低风险事实、拒绝噪声，把高风险或证据不足项留给人类最终复核。只有 confirmed 记忆会进入 `search_memory` / `wake` 可消费的稳定层。

---

## AI 协作协议

### 1. 记忆提炼（Distillation）
- **触发逻辑**：当一个开发阶段结束，或有大量原始 Session / Observations 累积时，应启动 `tools/session-distill` 这类专职 Skill，而不是让日常编码 Agent 临时兼职长程提炼。
- **AI 任务**：专职操作者应完整阅读原始日志，判断哪些是真正影响后续开发的技术决策、协作规则、任务状态和 rationale，而不是死板匹配关键词。
- **提炼边界**：长程提炼主路径是 `session-distill -> packet-memory-export -> memory-drafts review -> candidate layer`。Skill 负责理解和筛选，`harness-mem` 负责结构化落盘与后续消费。
- **落盘方式**：提炼结果应先进入候选区，例如 `RuleCandidate`、pending `MemoryEntry` 或 pending `RelationFact`。只有经过 `confirm` 后，才能成为稳定结构化记忆。

### 2. 运行时读写（Runtime Access）
- **主动搜索**：执行任务前，如果历史上下文可能影响当前判断，Agent 应使用 MCP `search_memory`。
- **随手记录**：当日常工作中出现新的约定、事实或纠正，Agent 应使用 MCP `suggest_rule` / `suggest_memory_entry`，而不是等待后续批量提炼。
- **消费边界**：`search_memory` / `wake` 默认只消费已确认记忆；pending 候选用于审核，不应污染唤醒上下文。

### 3. 自动审核与人类复核（Auto-review + Human Final Review）
- 未确认记忆保持候选状态。Agent 创建候选后，应通过 MCP `list_candidates` 自行读取候选，并直接调用 `confirm_*` / `reject_*` 处理低风险项：明确长期事实可确认，工具噪声、跨项目 workflow、泛泛原则、证据不足项可拒绝。
- Agent 不应把逐条分类工作交给用户，也不应把 `/hm:review` 作为日常必经下一步。用户看到的默认形态是 `/hm:distill` 的最终摘要：自动确认了什么、自动拒绝了什么、哪些保留待定、哪些确实需要用户确认。
- 只有 MCP 不可用、需要本地排障，或用户主动要求复查旧 pending 候选时，才退回 `/hm:review` 或 `harness-mem candidates` / `harness-mem confirm <id>` / `harness-mem reject <id>`。

### 4. 正则 Distill 的定位
- `harness-mem distill` / `harness-mem ds` 是启发式 fallback，适合快速 smoke、离线低成本扫描，或没有 AI Skill 可用的环境。
- 不要把正则提取当成长期主提炼引擎。高质量记忆应由 AI Skill 产生，并通过候选审核链路进入结构化存储。

---

## 仓库地图

| 路径 | 说明 | 优先级 |
|------|------|--------|
| `harness_mem/` | Python runtime：schemas、storage、search、MCP server、CLI commands。 | 核心实现 |
| `harness_mem/core/interfaces/` | **底座接口契约**（MemoryBackend / VerbatimStore / StructuredStore / ProjectProfileStore）。修改时遵守"接口纯净度"原则——见下文。 | 底座契约 |
| `tools/session-distill/` | 长程提炼 Skill：raw session -> packet -> memory drafts。 | 核心流程 |
| `tools/mem-distill/` | 既有 memory / observations 的清理、去重、归并。 | 整理 |
| `tools/grill-me/` / `tools/answer-me/` / `tools/ask-me/` | review 阶段可选协作者，不是主链硬依赖。 | 可选 |
| `plugins/harness-mem/` | repo-local 插件封装：安装、MCP 配置、技能入口。 | 集成 |
| `docs/` | 文档索引、设计说明、评审记录、最佳实践。 | 参考 |
| `openspec/` | 规格与变更记录；能力边界或行为变化应记录在这里。 | 设计真值 |
| `tests/` | 产品测试：CLI、MCP、storage、search、integration。 | 验证 |
| `benchmarks/` | 产品 benchmark 脚本与结果。 | 性能验证 |

---

## 常用命令

```bash
# 诊断与状态
harness-mem doctor
harness-mem status
harness-mem quickstart

# 用户日常入口优先 Slash/MCP/Skill；CLI 只作为本地排障兜底
# /hm:distill 默认读取 tools/session-distill，并完成 ingest -> suggest_* -> list_candidates -> AI auto-review

# 候选查看/修正（CLI 兜底；日常由 /hm:distill 自动处理低风险项）
harness-mem candidates
harness-mem confirm <id>
harness-mem reject <id>

# CLI 启发式 fallback，不是高质量提炼主路径
harness-mem ds

# 运行时消费检查
harness-mem wake
harness-mem search "auth logic"
```

## Key Technologies

- **Runtime**: Python 3.13+
- **Database**: SQLite FTS5 verbatim index + JSON blobs / JSONL-style structured memory
- **Integration**: MCP (Model Context Protocol) + GStack / Codex / Claude Skills
- **Primary workflow**: Skill-driven distillation, Slash/MCP AI auto-review with human final review, MCP runtime consumption
