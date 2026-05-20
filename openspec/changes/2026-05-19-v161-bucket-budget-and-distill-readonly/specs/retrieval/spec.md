# retrieval

## Why

v1.6.0 在 search payload 里**只读暴露**了 `memory_type`；本切片把"按类型 filter"补齐，让 AI 能在 wake-up 之外的查询场景明确表达"我只要 semantic 规则 / 我只要 episodic 事件"。

## ADDED Requirements

### Requirement: search_memory 接受 memory_type filter

MCP `search_memory` / REST `POST /search` / `read_api.search_memory(...)` MUST 接受可选参数 `memory_type: list[str] | None`，取值范围 `episodic | semantic | procedural`。

- `memory_type=None` 或 `[]`：不过滤，行为与 v1.6.0 一致
- `memory_type=["semantic"]`：仅返回 `memory_type == "semantic"` 的 `MemoryEntry`
- `memory_type=["semantic", "episodic"]`：返回该集合内的 entry，多值用 OR 关系
- 非法值：MCP / REST MUST 返回 422-class 错误（带 message `unknown memory_type: <value>`）；CLI MUST 在 stderr 提示有效集合并以非零退出码失败

filter MUST 只作用于 `MemoryEntry`，不影响 `Observation` 或 `RelationFact` 的返回（它们没有 `memory_type` 字段）。

#### Scenario: 仅过滤 semantic 规则
```bash
$ harness-mem search "single quote" --memory-type semantic
[Hybrid Search]
- mem_123 [convention/semantic] use single quote (score: 0.92)
```

#### Scenario: 多值 OR 关系
```bash
$ harness-mem search "auth" --memory-type semantic --memory-type episodic
- mem_001 [bug/semantic] Validate JWT expiry (score: 0.71)
- obs_456 [observation/episodic] auth failure trace (score: 0.65)
```

#### Scenario: 非法值显式拒绝
```bash
$ harness-mem search "x" --memory-type unknown
Error: unknown memory_type: unknown. Valid: episodic | semantic | procedural.
```

### Requirement: MCP search_memory tool input schema 反映 memory_type

MCP 工具 `search_memory` 的 `input_schema` MUST 在 `properties` 增加：

```json
"memory_type": {
  "type": "array",
  "items": {"type": "string", "enum": ["episodic", "semantic", "procedural"]},
  "description": "Optional filter on MemoryEntry.memory_type. Multiple values are OR-ed."
}
```

`memory_type` 不出现在 `required` 列表；缺省即不过滤。

#### Scenario: MCP 客户端按 input_schema 传 memory_type
```json
{"name": "search_memory", "arguments": {"query": "auth", "memory_type": ["semantic"]}}
```
返回 payload 仅含 `memory_type=="semantic"` 的 entry。
