# retrieval Specification

## Purpose

定义 local-first 检索行为，包括 FTS / hybrid 模式选择、vector fallback 语义、
memory_type filter、exact evidence search，以及依赖边界。v2.1 起检索的用户入口是
IDE 命令 / Skill / Agent 自然语言（例如 `/hm:search`），背后通过 MCP
`search_memory` / `search_raw` / `search_skills` 或 shared read API 调用 runtime。
CLI 不暴露日常 `search` 子命令；REST API 已移除。

## Requirements

### Requirement: HybridSearchLayer

系统 MUST 让 verbatim store 和 structured store 通过 `HybridSearchLayer` 执行
`mode=auto|fts|hybrid` 查询。hybrid 模式 MUST 使用持久化向量，而不是对候选池调用
`model.encode`。

#### Scenario: MCP search_memory 使用 auto 模式

```text
Agent calls search_memory(project_name="demo", query="dark mode", mode="auto")
-> requested_mode="auto"
-> effective_mode="hybrid" or "fts"
```

#### Scenario: hybrid 模式使用持久化向量

- **WHEN** `search_memory` is called with `mode="hybrid"`
- **THEN** system performs SQL lookup on `vec_embeddings`
- **THEN** `model.encode` is called exactly once for query text
- **THEN** candidate pool vectors are read from database, not computed

### Requirement: 向量模型懒加载

系统 SHALL 实现向量模型懒加载，在首次使用时加载，不在模块导入时加载。未安装 embedding
依赖时自动退化为纯 FTS。当 `vec_embeddings` 表不存在时，系统 MUST 回退到 FTS 模式而不是尝试实时 encode 候选池。

#### Scenario: vec_embeddings 表缺失时回退 FTS

- **WHEN** `search_memory` is called with `mode="hybrid"` but `vec_embeddings` table does not exist
- **THEN** system records fallback reason "vec_embeddings table not found"
- **THEN** search completes using FTS mode without error

### Requirement: search 默认值

系统 SHALL 设置 search 默认 mode 为 `auto`。

#### Scenario: search_memory 不显式传 mode 时默认 auto

```text
Agent calls search_memory(project_name="demo", query="dark mode")
-> requested_mode="auto"
```

### Requirement: 外部向量数据库

系统 SHALL NOT 引入外部向量数据库（Pinecone、Milvus、Weaviate 等），保持 local-first。

#### Scenario: hybrid 检索不依赖外部向量服务

```text
Agent calls search_memory(project_name="demo", query="dark mode", mode="hybrid")
-> runtime uses only local vec_embeddings table and SQLite FTS5
-> no external network request is made
```

### Requirement: 搜索结果展示实际模式

MCP MUST 在 payload 暴露 requested mode、effective mode 以及 fallback reason，避免
Agent 或用户误以为自己正在使用 hybrid 结果。

#### Scenario: MCP search_memory 返回 effective_mode

```json
{
  "requested_mode": "auto",
  "effective_mode": "fts",
  "fallback_reason": "embedding not available"
}
```

### Requirement: 搜索结果只读暴露 memory_type

MCP `search_memory` MUST 在每条 memory entry 结果 row 里包含 `memory_type` 字段。
该字段 MUST 与底层 `MemoryEntry.memory_type` 取值一致。

#### Scenario: MCP search_memory 结果含 memory_type

```json
{
  "memory_entries": [
    {
      "id": "mem_123",
      "category": "convention",
      "memory_type": "semantic",
      "content": "use single quote"
    }
  ]
}
```

### Requirement: search_memory 接受 memory_type filter

MCP `search_memory` / `read_api.search_memory(...)` MUST 接受可选参数
`memory_type: list[str] | None`，取值范围 `episodic | semantic | procedural`。
REST API 与 CLI search 不属于当前 surface。

- `memory_type=None` 或 `[]`：不过滤
- `memory_type=["semantic"]`：仅返回 `memory_type == "semantic"` 的 `MemoryEntry`
- `memory_type=["semantic", "episodic"]`：返回该集合内的 entry，多值 OR
- 非法值：MCP MUST 返回错误 payload，message 包含 `unknown memory_type`

#### Scenario: MCP 仅过滤 semantic 规则

```json
{"name": "search_memory", "arguments": {"project_name": "demo", "query": "auth", "memory_type": ["semantic"]}}
```

返回 payload 仅含 `memory_type=="semantic"` 的 memory entries。

### Requirement: exact evidence search through MCP

Exact / regex evidence search MUST be exposed through MCP `search_raw`, returning
observation id, session id, snippet, span, and candidate count. It is not a CLI
daily command.

#### Scenario: MCP search_raw returns exact snippet

```json
{"name": "search_raw", "arguments": {"project_name": "demo", "pattern": "ERROR-\\d+", "regex": true}}
```

The result includes matching observation ids and snippets with provenance.

### Requirement: search_memory backend contract is authoritative

`search_memory` MCP 工具与 `read_api.search_memory(...)` MUST 通过同一个运行时
`SearchBackend` 契约执行查询，并共享同一套 mode、fallback、budget、truncation
和 source coverage 语义。

#### Scenario: task-aware and shared search paths agree on retrieval metadata

- **WHEN** the runtime uses the same query for MCP search, task-aware context assembly, and wake query-aware planning
- **THEN** each path reports the same requested mode, effective mode, and fallback reason
- **AND** budget and truncation metadata come from the authoritative backend response rather than a hand-built compatibility payload

### Requirement: Context outcome signals are explainable opt-in ranking hints

SearchBackend MAY read recent `RetrievalSignal(context_outcome)` records as a
small ranking hint only when the project explicitly enables
`ProjectProfile.weak_link_signals`. The hint SHALL be bounded, explainable in
result metadata, and reversible by disabling the flag. It SHALL NOT decay,
archive, delete, or otherwise mutate confirmed truth.

#### Scenario: Outcome hint disabled by default

- **GIVEN** a project has `context_outcome` signals
- **AND** no profile enables `weak_link_signals`
- **WHEN** `search_memory` runs
- **THEN** ranking is unchanged by those signals
- **AND** result metadata exposes no positive or negative outcome score

#### Scenario: Outcome hint explains score delta

- **GIVEN** a project has `weak_link_signals=true`
- **AND** source `mem-a` has a recent `used` outcome
- **AND** source `mem-b` has a recent `misleading` outcome
- **WHEN** `search_memory` runs
- **THEN** `mem-a` receives a bounded positive `context_outcome_score`
- **AND** `mem-b` receives a bounded negative `context_outcome_score`
- **AND** each affected row includes `ranking_explanation(kind="context_outcome")`
- **AND** confirmed truth records remain unchanged
