# retrieval

## Why

`MemoryEntry` 在 v1.6.0 引入 `memory_type` 字段。检索层必须把这个字段在结果 payload 里**只读暴露**给消费方（CLI / MCP / REST），但**不消费、不 filter**——任何按类型分桶或过滤的行为变化留给 v1.6.1。

## ADDED Requirements

### Requirement: 搜索结果只读暴露 memory_type

CLI `search`、MCP `search_memory`、REST `/search` MUST 在每条结果 row 里包含 `memory_type` 字段。该字段 MUST 与底层 `MemoryEntry.memory_type` 取值一致；当结果对象非 `MemoryEntry`（例如 observation 行）时，MUST 输出 `null` 或省略，但保持字段存在性可被消费方安全读取。

#### Scenario: MCP search_memory 结果含 memory_type
```json
{
  "results": [
    {
      "id": "mem_123",
      "category": "convention",
      "memory_type": "semantic",
      "content": "use single quote",
      "score": 0.92
    }
  ]
}
```

#### Scenario: REST /search 结果含 memory_type
```json
{
  "rows": [
    {
      "id": "mem_456",
      "category": "bug",
      "memory_type": "semantic",
      "content": "JWT expiry must be validated"
    }
  ]
}
```

### Requirement: 搜索 v1.6.0 不接受 memory_type filter

CLI / MCP / REST 的 search 接口在 v1.6.0 MUST NOT 接受 `memory_type` 作为 filter 参数。任何尝试传入该参数的请求 SHALL 表现为忽略（向前兼容空策略），让 v1.6.1 引入 filter 时不会破坏老调用方。

#### Scenario: v1.6.0 阶段传入 memory_type 参数被忽略
```http
GET /search?q=jwt&memory_type=semantic
```

```json
{
  "rows": [
    {"id": "mem_456", "memory_type": "semantic", "score": 0.91},
    {"id": "mem_789", "memory_type": "episodic", "score": 0.83}
  ]
}
```
（注：episodic 行仍然返回，证明 filter 未生效——v1.6.1 才会让此参数真正过滤。）
