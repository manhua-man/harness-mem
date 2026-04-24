# mcp

## Why

如果 CLI 已支持 hybrid search 和完整 rule lifecycle，但 MCP 查询路径没有同步语义，上层聊天流仍会得到不一致的行为。

## MODIFIED Requirements

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
