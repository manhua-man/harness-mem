# retrieval Specification

## Purpose

定义 local-first 检索行为，包括 FTS / hybrid 模式选择、vector fallback 语义、以及依赖边界。检索的用户入口 v2.1 起是 IDE 命令 / Skill / Agent 自然语言（例如 `/hm:search`），背后通过 MCP `search_memory` / `search_raw` / `search_skills` 工具调用 runtime；CLI 不再暴露 search 子命令。Spec scenario 描述的是 **MCP 接口与 search payload** 的契约。

## Requirements

### Requirement: HybridSearchLayer

系统 MUST 让 verbatim store 和 structured store 通过 `HybridSearchLayer` 执行 `mode=auto|fts|hybrid` 查询，而不是继续直接绕过到 `SQLiteIndex.search()`。

#### Scenario: search_memory 在 auto 模式下优先 hybrid

```text
Agent 调 search_memory(project_name="demo", query="dark mode", mode="auto")
→ 返回包含: requested_mode="auto", effective_mode="hybrid",
            results=[{id: "mem_123", category: "preference", score: 0.940, mode: "hybrid"}]
```

#### Scenario: embedding 不可用时回退到 FTS

```text
Agent 调 search_memory(project_name="demo", query="dark mode", mode="auto")
（本机未安装 embedding extras）
→ 返回: requested_mode="auto", effective_mode="fts",
        fallback_reason="embedding model not available"
```

### Requirement: 向量模型懒加载

系统 SHALL 实现向量模型懒加载，在首次使用时加载，不在模块导入时加载。未安装 embedding 依赖时自动退化为纯 FTS。

#### Scenario: embedding 依赖缺失

```python
>>> from harness_mem.search import HybridSearchLayer
>>> layer = HybridSearchLayer()
>>> layer.search("test", mode="auto")
[FTS fallback] embedding model not available
```

### Requirement: search 默认值

系统 SHALL 设置 search 默认 mode 为 auto。

#### Scenario: search_memory 不显式传 mode 时默认 auto

```text
Agent 调 search_memory(project_name="demo", query="dark mode")
→ 返回: requested_mode="auto"
        effective_mode="hybrid"（embedding 可用）或 "fts"（fallback）
```

### Requirement: 外部向量数据库

系统 SHALL NOT 引入外部向量数据库（Pinecone、Milvus、Weaviate 等），保持 local-first。

#### Scenario: hybrid 检索不依赖外部向量服务

```text
Agent 调 search_memory(project_name="demo", query="dark mode", mode="hybrid")
→ 内部 layer 仅使用本地 vec_embeddings 表与 SQLite FTS5；不发起外部网络请求。
```

### Requirement: 搜索结果展示实际模式

MCP MUST 在 payload 暴露 requested mode、effective mode 以及 fallback reason，避免用户误以为自己正在使用 hybrid 结果。

#### Scenario: MCP search_memory 返回 effective_mode

```json
{
  "requested_mode": "auto",
  "effective_mode": "fts",
  "fallback_reason": "embedding not available"
}
```

### Requirement: 搜索结果只读暴露 memory_type

MCP `search_memory` MUST 在每条 memory entry 结果 row 里包含 `memory_type` 字段。该字段 MUST 与底层 `MemoryEntry.memory_type` 取值一致；当结果对象非 `MemoryEntry`（例如 observation 行）时，MUST 输出 `null` 或省略，但保持字段存在性可被消费方安全读取。

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

### Requirement: 搜索 v1.6.0 不接受 memory_type filter

MCP `search_memory` 在 v1.6.0 MUST NOT 接受 `memory_type` 作为 filter 参数。任何尝试传入该参数的请求 SHALL 表现为忽略（向前兼容空策略），让 v1.6.1 引入 filter 时不会破坏老调用方。

#### Scenario: v1.6.0 阶段传入 memory_type 参数被忽略

```text
Agent 调 search_memory(project_name="demo", query="jwt", memory_type=["semantic"])
→ v1.6.0 返回包含 episodic 行（filter 未生效），v1.6.1 起才会真过滤。
```
