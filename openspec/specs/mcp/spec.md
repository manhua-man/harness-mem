# mcp Specification

## Purpose

定义 MCP 工具语义与生命周期契约。v2.1 起，MCP 是 harness-mem 唯一的日常运行时入口——用户通过 IDE 命令（`/hm:distill`、`/hm:wake`、`/hm:search`）或自然语言驱动 Agent，Agent 在背后调 MCP 工具完成 ingest、distill、search、timeline、candidate review、wake 等流程。CLI 不再承载日常 memory 操作，仅保留 `init` / `quickstart` / `doctor` / `import` / `purge` / `maintenance` 这类安装与维护命令。
## Requirements
### Requirement: MCP owns the daily user workflow

MCP MUST expose status, ingest, distill, search, timeline, and candidate-review tools so slash/agent workflows do not require users to manually drive CLI commands. CLI MAY remain available for installation, diagnostics, and explicit cleanup, but MUST NOT be the normal user-facing control path.

`/hm:distill` MUST be the daily closed-loop flow: prepare current-project evidence, let the AI generate candidates, let the AI auto-confirm or auto-reject low-risk candidates, and return a final human review summary. `/hm:review` MAY exist only as a repair/recheck path for old pending candidates, high-risk leftovers, or user corrections; it MUST NOT be required after every distill run.

#### Scenario: Agent ingests current project sessions without asking for CLI

```json
MCP -> ingest_sessions({
  "project_name": "demo-project",
  "client": "auto",
  "limit": 5,
  "scope": "project"
})
Response: {
  "success": true,
  "project_name": "demo-project",
  "output": "Auto-detected ingest client: codex-archive\n..."
}
```

#### Scenario: Agent prepares a session-distill evidence packet in one call

```json
MCP -> prepare_session_distill({
  "project_name": "demo-project",
  "client": "auto",
  "limit": 5,
  "scope": "project",
  "project_root": "F:/demo-project",
  "observation_limit": 5
})
Response: {
  "success": true,
  "project_name": "demo-project",
  "ingest": {"success": true},
  "observations": [
    {
      "source": "observation:obs_123",
      "session_id": "sess_123",
      "raw_content": "..."
    }
  ],
  "distill_instructions": [
    "Do not call Bash, cmem, cat, ls, find, timeline, or get_observations for this slash flow unless this packet is empty."
  ]
}
```

#### Scenario: Agent finishes distill with auto-review instead of asking for `/hm:review`

```json
MCP -> list_candidates({
  "project_name": "demo-project",
  "status": "pending",
  "limit": 100
})
MCP -> confirm_memory_entry({"entry_id": "mem_safe_fact"})
MCP -> reject_rule({"rule_id": "rule_tool_noise", "reason": "tool orchestration noise, not a project rule"})
Response summary: {
  "new_candidates": 2,
  "auto_confirmed": 1,
  "auto_rejected": 1,
  "kept_pending": 0,
  "needs_user_confirmation": 0,
  "next_user_action": "review the summary and mention any incorrect item id"
}
```

#### Scenario: Agent checks project status without CLI

```json
MCP -> get_project_status({
  "project_name": "demo-project"
})
Response: {
  "success": true,
  "project_name": "demo-project",
  "observation_count": 3,
  "pending_candidate_count": 1
}
```

### Requirement: list_candidates 审核入口

MCP MUST 提供 `list_candidates` 工具，用于按项目和状态列出待审结构化记忆候选，覆盖 rule candidate、memory entry、relation fact、supersede candidate、procedural candidate 五类。`search_memory` 仍 MUST 默认只返回 accepted 记忆，不得被用作 pending 审核列表来源。

#### Scenario: 列出 pending 候选

```json
MCP -> list_candidates({
  "project_name": "demo-project",
  "status": "pending",
  "limit": 100
})
Response: {
  "success": true,
  "project_name": "demo-project",
  "status": "pending",
  "candidates": [
    {
      "type": "memory_entry",
      "id": "mem_123",
      "confirm_tool": "confirm_memory_entry",
      "reject_tool": "reject_memory_entry"
    }
  ],
  "count": 1,
  "total_count": 1
}
```

### Requirement: reject_rule

系统 MUST 支持 reject_rule，与 confirm_rule 对称。

#### Scenario: 拒绝规则候选

```json
MCP -> reject_rule({
  "rule_id": "rule_123",
  "reason": "outdated or incorrect"
})
Response: { "success": true, "message": "Rule rejected" }
```

### Requirement: suggest_rule

系统 MUST 支持 suggest_rule，完成 confirm/reject/suggest 完整闭环。

#### Scenario: 建议新规则

```json
MCP -> suggest_rule({
  "project_name": "demo-project",
  "pattern": "User prefers dark mode",
  "trigger": "When discussing UI defaults",
  "session_id": "sess_123"
})
Response: { "success": true, "rule_id": "rule_456", "status": "pending" }
```

### Requirement: get_observations 暴露原始证据

MCP MUST 提供 `get_observations` 工具，按项目 + session id 取原始 Observation。该工具替代历史 CLI `harness-mem show -o <id>` 的语义。

#### Scenario: Agent 取一条原始观察

```json
MCP -> get_observations({
  "project_name": "demo-project",
  "session_id": "sess_456"
})
Response: {
  "observations": [
    {
      "id": "obs_123",
      "content": "User prefers dark mode...",
      "source_session": "sess_456",
      "timestamp": "2026-04-20T10:00:00Z"
    }
  ]
}
```

### Requirement: wake-up 截断标记

`wake` MCP 工具 MUST 在输出文本里对超长的 rule pattern / memory content 加 `[...truncated]` 后缀，避免 Agent 把截断后的字符串当成完整事实。

#### Scenario: wake 输出截断

```text
Agent 调 wake(project_name="demo-project")
→ 返回 output 含: "Rule: User prefers dark mode for code reviews [...truncated]"
       "  📍 obs_123 from session sess_456"
```

### Requirement: search score 展示

`search_memory` MCP 工具 MUST 在每条结果上返回 score 字段，让客户端能展示排序依据。

#### Scenario: 搜索结果带分数

```text
Agent 调 search_memory(project_name="demo-project", query="dark mode")
→ 返回 results 包含:
  [{id: "obs_456", content: "User prefers dark mode", score: 0.94},
   {id: "obs_123", content: "Dark theme for IDE", score: 0.87}]
```

### Requirement: scope=project|all

MCP `search_memory` MUST 支持 `scope=project|all`。`project_name` 仅在 `scope=project` 时必填。

#### Scenario: 跨项目检索

```json
MCP -> search_memory({
  "query": "dark mode",
  "scope": "all"
})
Response: { "results": [...], "project_count": 3 }
```

#### Scenario: 项目内检索

```json
MCP -> search_memory({
  "query": "dark mode",
  "scope": "project",
  "project_name": "my-project"
})
Response: { "results": [...], "project_count": 1 }
```

### Requirement: search_memory 查询语义

`search_memory` MCP 工具 MUST 支持可选 `mode=auto|fts|hybrid`，并与 runtime 共享同一套 store search 语义。

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

### Requirement: MCP supersede review tools

The MCP server SHALL expose `suggest_supersede`, `confirm_supersede`, and `reject_supersede`.

#### Scenario: Suggest supersede

- **WHEN** `suggest_supersede` is called with target and replacement truth ids
- **THEN** the server returns `success=true`
- **AND** a pending supersede candidate id

#### Scenario: Confirm supersede

- **GIVEN** a pending supersede candidate
- **WHEN** `confirm_supersede` is called
- **THEN** the server returns `success=true`
- **AND** the candidate status becomes `accepted`
- **AND** the target truth becomes historical

#### Scenario: Reject supersede

- **GIVEN** a pending supersede candidate
- **WHEN** `reject_supersede` is called
- **THEN** the server returns `success=true`
- **AND** the candidate status becomes `rejected`
- **AND** target and replacement truth remain current

### Requirement: MCP candidate listing includes supersede candidates

`list_candidates` SHALL include supersede candidates and return `supersede_count`.

#### Scenario: Mixed candidate list

- **GIVEN** one rule candidate, one memory entry candidate, one relation fact candidate, and one supersede candidate
- **WHEN** `list_candidates` is called
- **THEN** the response count is 4
- **AND** the supersede candidate has `confirm_tool=confirm_supersede`

### Requirement: Trace Relations Tool

The MCP server SHALL expose a `trace_relations` tool.

#### Scenario: Bounded trace payload

- **WHEN** a client calls `trace_relations`
- **THEN** the payload includes serialized paths with entities, depth, confidence, and edge evidence

### Requirement: Search Memory Time Window Metadata

The MCP `search_memory` tool SHALL return parsed time-window metadata when a supported phrase is present.

#### Scenario: Relative time search

- **WHEN** `search_memory` receives a query containing `two months ago`
- **THEN** the response includes the original query, cleaned effective query, and UTC window metadata

### Requirement: Search Raw Tool

The MCP server SHALL expose `search_raw`.

#### Scenario: Exact evidence payload

- **WHEN** a client calls `search_raw` with a regex pattern
- **THEN** the response includes exact observation matches, snippets, match spans, and candidate counts

#### Scenario: Invalid regex payload

- **WHEN** a client calls `search_raw` with an invalid regex
- **THEN** the tool returns `success=false` with a regex error message
