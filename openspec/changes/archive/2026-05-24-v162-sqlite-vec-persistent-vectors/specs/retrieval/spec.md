# retrieval Specification (Delta)

## MODIFIED Requirements

### Requirement: HybridSearchLayer

系统 MUST 让 verbatim store 和 structured store 通过 `HybridSearchLayer` 执行 `mode=auto|fts|hybrid` 查询。在 v1.6.2 中，hybrid 模式 MUST 使用 SQL JOIN 查询持久化向量，而不是对候选池调用 `model.encode`。

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

#### Scenario: hybrid 模式使用持久化向量
- **WHEN** user runs `harness-mem search "test" --mode hybrid`
- **THEN** system performs SQL JOIN on `vec_embeddings` table
- **THEN** `model.encode` is called exactly once (for query text only)
- **THEN** candidate pool vectors are read from database, not computed

### Requirement: 向量模型懒加载

系统 SHALL 实现向量模型懒加载，在首次使用时加载，不在模块导入时加载。未安装 embedding 依赖时自动退化为纯 FTS。在 v1.6.2 中，当 `vec_embeddings` 表不存在时，系统 MUST 回退到 FTS 模式而不是尝试实时 encode 候选池。

#### Scenario: embedding 依赖缺失
```python
>>> from harness_mem.search import HybridSearchLayer
>>> layer = HybridSearchLayer()
>>> layer.search("test", mode="auto")
[FTS fallback] embedding model not available
```

#### Scenario: vec_embeddings 表缺失时回退 FTS
- **WHEN** user searches with `mode=hybrid` but `vec_embeddings` table does not exist
- **THEN** system logs "vec_embeddings table not found, falling back to FTS"
- **THEN** search completes using FTS mode without error
