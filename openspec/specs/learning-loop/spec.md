# learning-loop Specification

## Purpose

定义"correct → suggest_rule → 候选层 → confirm/reject → wake 命中"这条 learning loop 的 MCP 工具契约。学习闭环的用户入口是 IDE 命令 / Skill / Agent 自然语言；spec scenario 描述的是 MCP 工具间的协作语义。

## Requirements

### Requirement: suggest_rule

系统 MUST 支持 `suggest_rule`，让 Agent 在显式 distill 流程或用户明确要求记录规则时把候选写入 pending 层。

#### Scenario: 建议规则

```json
MCP -> suggest_rule({
  "project_name": "demo",
  "pattern": "User prefers dark mode for code reviews",
  "trigger": "When discussing UI defaults",
  "session_id": "sess_123"
})
Response: { "success": true, "rule_id": "rule_456", "status": "pending" }
```

### Requirement: confirm/reject/suggest 完整闭环

系统 MUST 支持 `confirm_rule` + `reject_rule` + `suggest_rule` 形成完整闭环。

#### Scenario: 完整闭环

```text
1. Agent 调 suggest_rule(project_name=..., pattern=..., trigger=...)
   -> {rule_id: "rule_001", status: "pending"}

2. Agent / auto-review 决定确认
   MCP -> confirm_rule({rule_id: "rule_001"})
   -> {success: true, confirmed_rule_id: "rule_001"}

   或拒绝
   MCP -> reject_rule({rule_id: "rule_001", reason: "duplicate"})
   -> {success: true}
```

### Requirement: scope=project|all

`search_memory` / `search_skills` MUST 支持 `scope=project|all`，让 Agent 跨项目检索 confirmed 记忆。`project_name` 仅在 `scope=project` 时必填。

#### Scenario: 跨项目检索 learning

```json
MCP -> search_memory({
  "query": "dark mode preference",
  "scope": "all"
})
Response: {
  "results": [...],
  "project_count": 3,
  "projects": ["project-a", "project-b", "project-c"]
}
```

### Requirement: 同聊天流完成

Agent SHOULD 让 correct -> review -> confirm/reject 尽量在同一聊天流里完成，不把候选审核工作甩给独立 review 入口。学习闭环命中后，下次 `wake` MUST 在 wake-up 输出里反映该规则。

#### Scenario: 同一会话完成闭环

```text
User: "我们项目的事实是 X，刚才 Agent 的 Y 是错的，记一条 X 的规则。"
Agent:
  1. suggest_rule(project_name=..., pattern="X", trigger="when ...")
  2. confirm_rule(rule_id=...)
Agent 回复:
  Confirmed rule rule_001. Run /hm:wake (or 让我用 harness-mem 唤醒) 即可在新对话看到这条规则。
```
