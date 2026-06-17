## MODIFIED Requirements

### Requirement: search_memory 查询语义
`search_memory` MCP 工具与 `read_api.search_memory(...)` MUST 通过同一个运行时
`SearchBackend` 契约执行查询，并共享同一套 mode、fallback、budget、truncation
和 source coverage 语义。

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

#### Scenario: task-aware and shared search paths agree on retrieval metadata
- **WHEN** the runtime uses the same query for MCP search, task-aware context assembly, and wake query-aware planning
- **THEN** each path reports the same requested mode, effective mode, and fallback reason
- **AND** budget and truncation metadata come from the authoritative backend response rather than a hand-built compatibility payload
