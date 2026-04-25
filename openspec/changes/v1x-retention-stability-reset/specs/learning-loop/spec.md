# Learning Loop 低切换化

## Why

当前的 correct -> review -> confirm/reject 流程需要用户在多个命令之间切换，容易打断思路。目标是尽量把完整闭环留在同一聊天流里完成。

## ADDED Requirements

### Requirement: suggest_rule

系统 MUST 支持 suggest_rule，完成 confirm/reject/suggest 完整闭环。

接口: MCP tool `suggest_rule`

#### Scenario: 建议规则
```json
MCP → suggest_rule({
  rule_text: "User prefers dark mode for code reviews",
  context: "mentioned during session"
})
Response: { success: true, suggestion_id: "sug_001" }
```

### Requirement: confirm/reject/suggest 完整闭环

系统 MUST 支持 confirm_rule_candidate + reject_rule_candidate + suggest_rule 形成完整闭环。

#### Scenario: 完整闭环
```json
// 1. 用户提出建议
MCP → suggest_rule({ rule_text: "...", context: "..." })

// 2. 系统展示建议
Response: { suggestion_id: "sug_001", status: "pending" }

// 3. 用户确认
MCP → confirm_rule_candidate({ suggestion_id: "sug_001" })

// 或拒绝
MCP → reject_rule_candidate({ suggestion_id: "sug_001", reason: "..." })
```

### Requirement: scope=project|all

系统 SHALL 支持 MCP 查询增加 scope=project|all，支持跨项目检索。project_name 仅在 scope=project 时必填。

接口: MCP 查询 `scope=project|all`

#### Scenario: 跨项目检索 learning
```json
MCP → search_memories({
  query: "dark mode preference",
  scope: "all"
})
Response: {
  results: [...],
  project_count: 3,
  projects: ["project-a", "project-b", "project-c"]
}
```

### Requirement: 同聊天流完成

系统 SHALL 支持 correct -> review -> confirm/reject 尽量在同一聊天流里完成。

#### Scenario: 同一会话完成闭环
```
User: correct "obs_123" "User prefers dark mode"
Assistant: I'll update that. Reviewing changes...

Confirmed: obs_123 now reflects "User prefers dark mode"
💡 This rule is now active. Run 'harness-mem wake' to see it.
```
