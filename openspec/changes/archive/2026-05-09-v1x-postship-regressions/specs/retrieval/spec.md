# 检索基础设施

## Why

`HybridSearchLayer` 已经存在，但如果运行时查询路径没有真正接到 store / CLI / MCP，上层用户看到的仍然只是纯 FTS。

## MODIFIED Requirements

### Requirement: HybridSearchLayer

系统 MUST 让 verbatim store 和 structured store 通过 `HybridSearchLayer` 执行 `mode=auto|fts|hybrid` 查询，而不是继续直接绕过到 `SQLiteIndex.search()`。

#### Scenario: CLI search 使用 auto 模式
```bash
$ harness-mem search "dark mode" --mode auto
[Hybrid Search]
- [preference] prefers dark theme  (score: 0.940, mode: hybrid)  -> structured
```

#### Scenario: embedding 不可用时回退到 FTS
```bash
$ harness-mem search "dark mode" --mode auto
[FTS Search] (embedding not available, using full-text search)
```

## ADDED Requirements

### Requirement: 搜索结果展示实际模式

CLI 和 MCP MUST 暴露 requested mode、effective mode 以及 fallback reason，避免用户误以为自己正在使用 hybrid 结果。

#### Scenario: MCP 返回 effective_mode
```json
{
  "requested_mode": "auto",
  "effective_mode": "fts",
  "fallback_reason": "embedding not available"
}
```
