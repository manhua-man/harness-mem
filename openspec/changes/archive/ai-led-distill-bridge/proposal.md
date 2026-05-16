# Proposal: AI-led Distillation Bridge

## Why

AI 主导的长程提炼需要一条安全桥梁，把 Skill 产出的知识接入 harness-mem 的结构化记忆。仅靠正则提取容易漏掉 rationale 和工程决策；但如果允许 AI 直接写入已生效记忆，未经审核或幻觉产生的条目就可能污染 `search_memory` 和 `wake`。

## What Changes

- 为 `MemoryEntry` 和 `RelationFact` 增加候选状态语义：`pending`、`accepted`、`rejected`。
- 增加 MCP 写入工具，让 AI 能建议 memory entry 和 relation fact，但不会立即激活为运行时记忆。
- `search_memory` 和 `wake` 默认只消费已确认的结构化记忆。
- 人类通过现有 CLI 审核链路和 MCP confirm/reject 工具确认或拒绝候选。
- 增加 import bridge，让已审查的 Skill JSON 输出进入同一候选层。

## Impact

- Skill 驱动的提炼可以回流到 harness-mem，不再依赖正则提取作为主路径。
- pending 和 rejected 的 AI 建议不会污染下游运行时上下文。
- CLI 继续作为人类审核仪表盘，MCP 继续作为运行时读写接口。
