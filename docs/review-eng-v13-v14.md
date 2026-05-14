# 工程架构评审：harness-mem v1.3 / v1.4 技术方案

> 基于 README、CHANGELOG、benchmark_v1.md、pyproject.toml 及 storage/*.py 代码分析。

---

## 1. 当前代码底座对 V2 目标的准备程度

### 优点

- **接口隔离良好。** `VerbatimStore`、`StructuredStore`、`MemoryBackend` 都是 Protocol（`core/interfaces/`），替换或扩展实现只需要满足接口签名，不侵入核心逻辑。
- **数据分离清晰。** JSON blobs 是 ground truth，SQLite 是索引缓存 — 这种 "blob-as-source-of-truth" 设计使得索引格式可以灵活迭代（加向量索引、加 graph 索引都不会破坏已有数据）。
- **SQLiteIndex 的 `_tokenize_query` 已对 FTS5 做 stop words 处理**（`sqlite_index.py:346-361`），这是 V1 benchmark 中踩过的坑。
- **双层 schema 已落定。** Observation / MemoryEntry / TaskHandoff / RuleCandidate / ConfirmedRule 五个实体分别在 schema 目录中定义，Pydantic v2 建模。

### 当前的问题

1. **SQLiteIndex.search() 对 FTS5 强耦合。** 当前 `_tokenize_query` 产生 FTS5 match 语法（eg. `foo*` 后缀），无法直接「扩展」为向量检索。要引入向量需要：
   - 要么在 `SQLiteIndex` 之外加一层 `HybridSearch` 编排层
   - 要么在 `search()` 方法上加一个 `mode="fts"|"vector"|"hybrid"` 参数
   - 不应改动现有 `search()` 的 FTS 行为（向后兼容）

2. **storage 层无 abstraction interface。** `LocalVerbatimStore`、`LocalStructuredStore` 虽然是 protocol 的实现，但它们自己并未继承/注册 interface —— `VerbatimStore` 和 `StructuredStore` 是 duck-typed Protocol，IDE 对 interface 检查较弱。

3. **`where` 过滤仅支持 `LIKE` 字符串匹配。** `local_verbatim_store.py:98-99` 中 project_name 过滤通过 `metadata LIKE ?` 实现，本质是 JSON 文本搜索。随着数据量增长，这一模式耦合了 JSON 序列化细节。

4. **无 compaction/purging 机制。** 老的 observations 和 entries 只增不删，wake-up token 预算全量累计。v1.2.0 只加了提示文字，未实现实际清理。

5. **异步接口但不全是异步。** `to_thread` 包装 SQLite 操作是好做法，但 `save_task_handoff` 中的 blob 写入是同步的（`local_structured_store.py:176`），不过对 CLI 工具影响不大。

---

## 2. v1.3 和 v1.4 的建议实施顺序

### 推荐方案

| 版本 | 范围 | 工作量 | 理由 |
|------|------|--------|------|
| **v1.3** | 向量嵌入 + Hybrid Search + 索引可扩展性改造 | Medium | benchmark 报告明确核心瓶颈是语义鸿沟（-9.3pp at R@5），向量嵌入对 multi-session 和 temporal-reasoning 提升最大 |
| **v1.4** | compaction/purging + relation facts + ~~temporal bias~~ (已移除) | Medium | temporal bias 经 benchmark 验证无价值已移除；其余功能依赖度低、风险小 |

### v1.3 详细步骤

1. **新增 `HarnessVectorIndex` 类（`storage/vector_index.py`）**
   - 依赖：`sentence-transformers` + `numpy`（可选 `chromadb` 或手写 numpy 内积）
   - 接口：`encode(texts) → np.ndarray`、`search(query, top_k) → list[ids]`
   - 向量存储：推荐 `numpy` 文件 + JSON 索引存储（对标 JSON blob 风格），不引入外部向量数据库，保持 local-first

2. **重构 `SQLiteIndex.search()` 或者创建 `HybridSearchLayer`（`storage/hybrid_search.py`）**
   - 输入：原始 query 字符串
   - 输出：`BM25Score(vector_score * w1 + fts_score * w2)` 合并排序
   - 保持 `SQLiteIndex.search()` 不变，上层加编排层

3. **接口扩展**
   - `VerbatimStore.search()` 和 `StructuredStore.search_memory_entries()` 增加 `mode` 参数
   - 默认 `mode="auto"`：当 query 命中精确 token 时走 FTS，否则回退 hybrid

4. **配置化权重**
   - `pyproject.toml` 或 `~/.harness-mem/config.json` 中声明 `hybrid_weights.fts` 和 `hybrid_weights.vector`
   - 默认 `fts: 0.4, vector: 0.6`，benchmark 调优后固化默认值

### v1.4 详细步骤

1. **compaction 机制**
   - `harness-mem compact` 命令
   - 策略：按时间窗口（保留最近 N 天）+ category 过滤保留 key observations
   - 被 compact 的 observation 标记 `compacted: true` 而非物理删除，FTS 索引中排除

2. **relation facts**
   - 新增 `RelationFact` schema（`source_entity`, `target_entity`, `relation_type`, `confidence`）
   - 存储：JSON blob + SQLite 索引（simple key-value）
   - 不引入 graph DB，不做图遍历，只做 entity 级别的关联检索增强

3. **~~temporal bias~~** (已移除)
   - 经 benchmark 验证无价值：初始实现 500/500 问题完全无效，修复后降低召回率
   - 功能已于 2026-05-12 完全移除，分析证据见 `docs/temporal-bias-analysis.md`

---

## 3. 技术风险最大的点

### 风险 1：向量嵌入的模型选择与延迟

- **风险描述**：all-MiniLM-L6-v2（384 维）首次加载 ~100MB RAM，对 CLI 工具不是小代价。每次 search 都要编码 query（~50ms），如果每 ingest 一条 observation 都要编码一次，增量代价不可忽略。
- **缓解**：
  - Lazy load：`HarnessVectorIndex` 只有在 hybrid search 时才加载模型
  - 可选 fallback：如果 `sentence-transformers` 未安装，自动退化为纯 FTS

### 风险 2：混合检索权重难调优

- benchmark 报告中的 Hybrid 模式（纯 FTS5 加成）反而低于 raw FTS，说明「加信号不一定提升」。向量 + FTS 的线性加权如果没有 benchmark 验证，同样可能降级。
- **缓解**：
  - v1.3 合入后必须跑一遍 LongMemEval benchmark
  - 默认权重保守（`vector: 0.3, fts: 0.7`），用户可覆盖

### 风险 3：过度工程

- 最容易做错的地方：在 v1.3 引入向量时同时引入以下任何一个：
  - 第三层 storage（graph DB、redis 缓存、外部向量数据库）
  - ReRanker cross-encoder（不符合 local-first，且依赖 ~500MB 模型）
  - 实时 embedding 增量同步（使用简单 cron-like batch 就够）

---

## 4. 新增依赖与 pyproject.toml 影响

| 依赖 | 用途 | 对 pyproject.toml 的影响 |
|------|------|------------------------|
| `sentence-transformers>=3.0` | 文本嵌入 | 新增 `dependencies`（~100MB wheel） |
| `numpy>=1.24` | 向量计算（内积、L2 归一化） | 新增 `dependencies`（大概率已被 sentence-transformers 拉入） |
| `chromadb`（可选） | 向量存储 vs 手写 numpy 文件 | 不推荐，除非用户明确需要持久化向量管理 |

**建议**：将 `sentence-transformers` 和 `numpy` 设为 hard dependency（已评估 ~100MB 额外磁盘，对 local CLI 可接受）。将 `chromadb` 留作 optional 扩展。

```toml
dependencies = [
    "pydantic>=2.0",
    "sqlite-utils>=3.35",
    "sentence-transformers>=3.0",
    "numpy>=1.24",
]
[project.optional-dependencies]
chroma = ["chromadb>=0.5"]
benchmark = ["pandas", "scikit-learn"]
```

---

## 5. 工作量估算

| Feature | 工作量 | 涉及文件数 | 核心改动 |
|---------|--------|-----------|---------|
| 向量嵌入 + `HarnessVectorIndex` | **Small-Medium**（2-3d） | 2-3 新增 | `storage/vector_index.py`, `storage/__init__.py` |
| Hybrid Search 编排层 | **Small**（1-2d） | 1-2 新增 | `storage/hybrid_search.py`, 接口扩展 |
| ReRanker（cross-encoder） | **Medium**（2-3d） | 1-2 | `storage/reranker.py` + 模型懒加载 |
| compaction/purging | **Small**（1d） | 3-4 改动 | `cli.py` 新命令 + `storage/` 新增方法 |
| relation facts | **Small**（1-2d） | 3-4 | `core/schemas/relation_fact.py` + store 扩展 |
| ~~temporal bias~~ | ~~Small（1d）~~ 已移除 | ~~2-3~~ | ~~hybrid search 分数加权 + schema 扩展~~ 经 benchmark 验证无价值，已移除 |

---

## 总结

- **v1.3** 应聚焦 `HarnessVectorIndex` + `HybridSearchLayer`，不做大重构。SQLite FTS5 与向量索引没有冲突——FTS 继续走现有 SQLite 路径，向量走 numpy 路径，在搜索编排层合并。
- **v1.4** 做 compaction、relation facts，~~temporal bias~~（已移除），这些是增量改善而非颠覆性的。
- **最大技术风险**是向量模型加载延迟和混合检索权重调优。两个都有明确的缓解方案（懒加载 + benchmark 验证）。
- 不要让 v1.3 膨胀到包含 ReRanker 或 semantic chunk——那是 V2 的事情，不是 V1.x。
