# mcp Specification

## Purpose
Define MCP/CLI semantic alignment for memory lifecycle, search, rule learning, and observable output contracts.
## Requirements
### Requirement: reject_rule_candidate

系统 MUST 支持 reject_rule_candidate，与 confirm_rule_candidate 对称。

接口: MCP tool `reject_rule_candidate`

#### Scenario: 拒绝规则候选
```json
MCP → reject_rule_candidate({
  rule_id: "rule_123",
  reason: "outdated or incorrect"
})
Response: { success: true, message: "Rule rejected" }
```

### Requirement: suggest_rule

系统 MUST 支持 suggest_rule，完成 confirm/reject/suggest 完整闭环。

接口: MCP tool `suggest_rule`

#### Scenario: 建议新规则
```json
MCP → suggest_rule({
  rule_text: "User prefers dark mode",
  context: "User mentioned this in session sess_123"
})
Response: { success: true, suggestion_id: "sug_456" }
```

### Requirement: show -o/--observation-id

系统 SHALL 支持 show 新增 `-o/--observation-id`，保留 `-i/--id` 作为 v1.4 前兼容别名。

接口: `harness-mem show -o <observation-id>`

#### Scenario: 使用新标志
```
$ harness-mem show -o obs_123
=== Observation ===
ID: obs_123
Content: User prefers dark mode...
💡 Source: from session sess_456 (2026-04-20)
```

### Requirement: wake-up 截断标记

系统 SHALL 在 wake-up 输出统一加 `[...truncated]`。

接口: wake 命令输出

#### Scenario: wake 输出截断
```
$ harness-mem wake
Rule: User prefers dark mode for code reviews [...truncated]
💡 Source: obs_123 from session sess_456
```

### Requirement: search score 展示

系统 SHALL 在搜索结果统一展示排序依据或 score。

接口: search 命令输出

#### Scenario: 搜索结果带分数
```
$ harness-mem search "dark mode"
1. obs_456 "User prefers dark mode" (score: 0.94)
2. obs_123 "Dark theme for IDE" (score: 0.87)
```

### Requirement: scope=project|all

系统 SHALL 支持 MCP 查询增加 scope=project|all，支持跨项目检索。project_name 仅在 scope=project 时必填。

接口: MCP 查询 `scope=project|all`

#### Scenario: 跨项目检索
```json
MCP → search_memories({
  query: "dark mode",
  scope: "all"
})
Response: { results: [...], project_count: 3 }
```

#### Scenario: 项目内检索
```json
MCP → search_memories({
  query: "dark mode",
  scope: "project",
  project_name: "my-project"
})
Response: { results: [...], project_count: 1 }
```

### Requirement: search_memory 查询语义

`search_memory` MCP 工具 MUST 支持可选 `mode=auto|fts|hybrid`，并与 CLI 共享同一套 store search 语义。

#### Scenario: MCP search_memory 指定 hybrid mode
```json
{
  "name": "search_memory",
  "arguments": {
    "project_name": "demo",
    "query": "dark mode",
    "mode": "hybrid"
  }
}
```

#### Scenario: MCP 返回一致的模式信息
```json
{
  "requested_mode": "hybrid",
  "effective_mode": "hybrid",
  "fallback_reason": null
}
```

