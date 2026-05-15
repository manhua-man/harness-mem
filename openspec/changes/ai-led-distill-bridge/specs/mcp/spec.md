# mcp

## ADDED Requirements

### Requirement: AI-suggested memory candidates

The MCP server MUST allow AI agents to suggest `MemoryEntry` and `RelationFact` candidates without making them immediately active runtime memory.

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

The response contains a created entry id and `status: "pending"`.

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

The response contains a created relation fact id and `status: "pending"`.

### Requirement: Candidate memory is not consumed before confirmation

`search_memory` and `wake` MUST consume accepted structured memory by default and MUST NOT surface pending or rejected `MemoryEntry` or `RelationFact` candidates.

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

The response omits pending memory entries and pending relation facts that match the query.

#### Scenario: Confirmed memory entry becomes searchable
```json
{
  "name": "confirm_memory_entry",
  "arguments": {
    "entry_id": "entry_123"
  }
}
```

After confirmation, `search_memory` may return the matching memory entry.

#### Scenario: Rejected relation fact remains hidden
```json
{
  "name": "reject_relation_fact",
  "arguments": {
    "fact_id": "fact_123"
  }
}
```

After rejection, `search_memory` does not return the matching relation fact.
