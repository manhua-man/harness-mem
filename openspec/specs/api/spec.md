# api Specification

## Purpose
TBD - created by archiving change v1x-internal-dogfood-hardening. Update Purpose after archive.
## Requirements
### Requirement: REST API backend lifecycle

系统 MUST 为 REST API 提供 async-safe 的 backend 初始化路径，并且在请求处理阶段不得在运行中的 event loop 内调用 `asyncio.run()`。

#### Scenario: API 请求在已运行的 event loop 中工作
```bash
$ harness-mem api
INFO:     Application startup complete.
```

### Requirement: project-scoped search contract

当 `/search` 使用 `scope=project` 时，系统 MUST 要求调用方显式传入 `project_name`，避免 project 过滤语义退化成隐式全局查询。

#### Scenario: project scope 缺少 project_name
```http
GET /search?q=dark%20mode&scope=project
```

```json
{
  "detail": "project_name is required when scope=project"
}
```

### Requirement: search mode transparency

`/search` MUST 返回 `requested_mode`、`effective_mode` 和 `fallback_reason`，让 API 调用方知道查询实际上使用了哪种检索模式。

#### Scenario: embedding 不可用时 API 明确回退到 FTS
```json
{
  "requested_mode": "auto",
  "effective_mode": "fts",
  "fallback_reason": "embedding not available"
}
```

