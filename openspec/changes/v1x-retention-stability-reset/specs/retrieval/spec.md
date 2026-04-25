# 检索基础设施

## Why

用户需要混合检索能力（关键词 + 向量），但当前只有 SQLite FTS。需要在不破坏 local-first 前提下引入向量检索。

## ADDED Requirements

### Requirement: HybridSearchLayer

系统 MUST 支持引入本地向量检索层 HybridSearchLayer，支持 mode=auto|fts|hybrid。保持现有 SQLite FTS 路径不变。

接口: `search --mode auto|fts|hybrid`

#### Scenario: auto 模式（embedding 可用）
```
$ harness-mem search "dark mode" --mode auto
[Hybrid Search]
1. obs_456 "User prefers dark mode" (score: 0.94, fts: 0.8, vector: 0.95)
2. obs_123 "Dark theme for IDE" (score: 0.87, fts: 0.9, vector: 0.82)
```

#### Scenario: auto 模式（embedding 不可用）
```
$ harness-mem search "dark mode" --mode auto
[FTS Search] (embedding not available, using full-text search)
1. obs_456 "User prefers dark mode" (fts_score: 0.8)
2. obs_123 "Dark theme for IDE" (fts_score: 0.9)
```

#### Scenario: 强制 FTS 模式
```
$ harness-mem search "dark mode" --mode fts
[FTS Search]
1. obs_456 "User prefers dark mode" (fts_score: 0.8)
```

#### Scenario: 强制 hybrid 模式
```
$ harness-mem search "dark mode" --mode hybrid
[Hybrid Search] (embedding required)
1. obs_456 "User prefers dark mode" (score: 0.94)
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

## REMOVED Requirements

### Requirement: 外部向量数据库

系统 SHALL NOT 引入外部向量数据库（Pinecone、Milvus、Weaviate 等），保持 local-first。
