# retrieval Specification

## Purpose
Define local-first retrieval behavior, including FTS/hybrid mode selection, vector fallback semantics, and dependency boundaries.
## Requirements
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

接口: `harness-mem search`

#### Scenario: search 默认使用 auto 模式
```
$ harness-mem search "dark mode"  # 默认为 auto
[Hybrid Search] (auto-detected embedding available)
1. obs_456 "User prefers dark mode" (score: 0.94)
```

### Requirement: 外部向量数据库

系统 SHALL NOT 引入外部向量数据库（Pinecone、Milvus、Weaviate 等），保持 local-first。

#### Scenario: hybrid 检索不依赖外部向量服务
```
$ harness-mem search "dark mode" --mode hybrid
[Hybrid Search] using local vector index
```

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

