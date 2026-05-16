# mcp

## ADDED Requirements

### Requirement: AI-suggested memory candidates

MCP server MUST 允许 AI agent 建议 `MemoryEntry` 和 `RelationFact` 候选，但不得让它们立即成为已生效运行时记忆。

#### Scenario: Suggest memory entry remains pending
```json
{
  "name": "suggest_memory_entry",
  "arguments": {
    "project_name": "demo",
    "category": "decision",
    "content": "Use AI-led distillation for long sessions.",
    "source": "session_123"
  }
}
```

响应包含新建的 entry id 和 `status: "pending"`。

#### Scenario: Suggest relation fact remains pending
```json
{
  "name": "suggest_relation_fact",
  "arguments": {
    "project_name": "demo",
    "source_entity": "session-distill",
    "target_entity": "harness-mem",
    "relation_type": "feeds_candidate_layer",
    "evidence": "Skill outputs are imported for human review.",
    "source": "session_123"
  }
}
```

响应包含新建的 relation fact id 和 `status: "pending"`。

### Requirement: Candidate memory is not consumed before confirmation

`search_memory` 和 `wake` MUST 默认只消费 accepted structured memory，并且 MUST NOT 展示 pending 或 rejected 的 `MemoryEntry` / `RelationFact` 候选。

#### Scenario: Pending candidate is hidden from search
```json
{
  "name": "search_memory",
  "arguments": {
    "project_name": "demo",
    "query": "AI-led distillation"
  }
}
```

响应不包含匹配该查询的 pending memory entries 或 pending relation facts。

#### Scenario: Confirmed memory entry becomes searchable
```json
{
  "name": "confirm_memory_entry",
  "arguments": {
    "entry_id": "entry_123"
  }
}
```

确认后，`search_memory` 可以返回匹配的 memory entry。

#### Scenario: Rejected relation fact remains hidden
```json
{
  "name": "reject_relation_fact",
  "arguments": {
    "fact_id": "fact_123"
  }
}
```

拒绝后，`search_memory` 不返回匹配的 relation fact。
