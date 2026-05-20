## Context

当前 harness-mem hybrid search 在查询热路径对 FTS 候选池（50-200 条）实时调用 `model.encode`，导致 P95 latency = 625.17ms。向量不持久化，每次重启需重新 encode 全库。embedding 模型锁死在 all-MiniLM-L6-v2，无法升级到更优模型。

v1.6.0 已落地五维测量地基（LongMemEval per-type R@5），v1.6.1 已落地 wake-up 分桶预算与 distill 只读边界。现在架构与安全护栏到位，可以引入持久化向量层。

约束：
- local-first：不引入外部向量数据库（Pinecone/Milvus/Weaviate）
- 体积上限：embedding 模型 ≤ 130MB（small/base 级别）
- Windows 兼容：sqlite-vec 扩展加载需要 `enable_load_extension(True)`
- 零回退：v1.6.2 在五维 R@5 上至少 3 个维度不回退

## Goals / Non-Goals

**Goals:**
- 把 encode 从查询热路径移到写入路径，P95 latency 目标 ≤437ms（-30%）
- 持久化向量到 sqlite-vec，重启后直接读取不重新 encode
- 支持三模型切换（all-MiniLM-L6-v2 / bge-small-en-v1.5 / nomic-embed-text-v1.5）
- 通过 shootout 数据驱动决策默认模型
- 提供 schema 升级路径（缺向量时 fallback FTS + doctor 提示 + rebuild 命令）

**Non-Goals:**
- 远程 embedding API（违反 local-first）
- bge-large / 1.3GB 级别模型（体积超限）
- 向量索引优化（HNSW/IVF）—— sqlite-vec 0.1.x 只支持 brute-force，优化留给 v1.7+
- 动态模型切换（运行时热切）—— 切模型需 rebuild，不支持同时查询多模型向量

## Decisions

### Decision 1: sqlite-vec 作为强制依赖

**选择**：`pyproject.toml` 的 `[hybrid]` extra 强制包含 `sqlite-vec>=0.1.0`，不保留 optional 路径。

**理由**：
- sqlite-vec 是 C 库 + SQLite 扩展（单 .so/.dll 文件），不引入服务端依赖，符合 local-first
- 保留 optional 会让 hybrid 默认路径在缺扩展时降级到 FTS，模糊产品定位
- 扩大测试矩阵（with/without sqlite-vec 两条路径）
- 产生"为什么我的 hybrid 不工作"类支持成本

**替代方案**：optional 依赖 + 运行时检测 → 拒绝，理由同上。

**例外**：极少数 hardened SQLite 构建不支持扩展加载，`harness-mem doctor` 给出 HM-202 错误码与降级到 v1.5.x FTS-only 的指引。

### Decision 2: vec_embeddings 表 schema

**选择**：
```sql
CREATE TABLE vec_embeddings (
    entry_id TEXT PRIMARY KEY,
    model_id TEXT NOT NULL,
    model_version TEXT NOT NULL,
    embedding BLOB NOT NULL,
    created_at INTEGER NOT NULL
);
```

**理由**：
- `entry_id` 作为 PK 保证一对一关系（一个 entry 只有一个当前模型的向量）
- `model_id` / `model_version` 支持模型切换后过滤老向量
- `embedding BLOB` 存序列化 numpy array（`np.array.tobytes()`）
- `created_at` 用于 debug 与未来可能的向量过期策略

**替代方案**：
- 用 sqlite-vec 的 `vec0` 虚拟表 → 拒绝，0.1.x 版本 vec0 不支持元数据列（model_id/model_version），需要额外 JOIN 表，复杂度高
- 多模型共存（不用 PK 约束）→ 拒绝，查询时需显式 filter model_id，且无法保证"当前模型的向量一定存在"

### Decision 3: 写入路径在 ingest/save 时持久化

**选择**：在 `LocalVerbatimStore.save_observation` / `LocalStructuredStore.save_memory_entry` 中调用 `_persist_embedding(entry_id, text, model_id, model_version)`。

**理由**：
- 写入路径是一次性成本，用户可接受 ingest 耗时增加
- 避免查询时阻塞（encode 是 CPU 密集操作）
- 保证"写入即可查"语义

**替代方案**：
- 后台异步 encode → 拒绝，增加复杂度（需队列/worker），且"写入后立即查询"会 miss 向量
- 延迟到首次查询时 encode → 拒绝，首次查询会很慢，用户体验差

### Decision 4: 查询路径走 SQL JOIN

**选择**：`HybridSearchLayer._search_hybrid` 改为：
1. FTS 查询得到 `entry_id` 列表
2. SQL JOIN `vec_embeddings` 表，filter `model_id = current_model`
3. 读取 `embedding BLOB`，反序列化为 numpy array
4. 对 query 调用 `model.encode`（1 次）
5. 计算 cosine similarity，RRF 融合

**理由**：
- 候选池不再调用 `model.encode`，latency 下降
- SQL JOIN 是 SQLite 优化路径，比 Python 循环快
- `model_id` filter 保证只用当前模型的向量

**替代方案**：
- 全库向量扫描（不走 FTS 候选池）→ 拒绝，500+ entries 时 brute-force 太慢
- 内存缓存向量 → 拒绝，增加内存占用，且重启后仍需从 DB 加载

### Decision 5: embedding shootout 决策规则

**选择**：按 roadmap-v16x.md "已决策 3" 的三条规则顺序匹配：
1. 全 5 维不回退 + ≥2 维 +1pp → 选它
2. ≥4 维不回退 + ≥1 维 +2pp → 选它
3. 否则保持 all-MiniLM-L6-v2 不变

**理由**：
- 数据驱动决策，避免"哪个模型更好"的主观讨论
- 规则 1 保证全面提升，规则 2 允许单维度显著提升
- 规则 3 是保守 fallback，避免强行换模型

**替代方案**：
- 只看总 R@5 → 拒绝，可能牺牲某个维度换取总分（v1.5.2 教训）
- 人工决策 → 拒绝，缺乏可复现性

### Decision 6: 模型切换后的向量过滤

**选择**：查询时 SQL `WHERE model_id = ?` 过滤，不匹配的向量不参与计算。

**理由**：
- 不同模型的向量空间不兼容（384-dim vs 768-dim，或同维度但语义空间不同）
- 混用会导致 similarity 计算无意义

**替代方案**：
- 自动 rebuild → 拒绝，用户可能不想立即 rebuild（耗时长）
- 报错阻止查询 → 拒绝，过于严格，应允许 fallback FTS

**实现**：`harness-mem doctor` 检测 model_id 不匹配时提示 rebuild，但不强制。

## Risks / Trade-offs

### Risk 1: Windows 上 sqlite-vec 扩展加载失败

**风险**：部分 Windows SQLite 构建禁用 `enable_load_extension`，导致 `OperationalError`。

**缓解**：
- `sqlite_index.py` 在 `_init_connection` 中 try/except 捕获 `OperationalError`
- 抛出 `HM-202: SQLite extension loading disabled` 错误码
- 错误消息包含降级指引（使用 FTS mode 或重新编译 sqlite）
- `harness-mem doctor` 检测并报告

### Risk 2: 首次 ingest 耗时显著增加

**风险**：每个 entry 需 encode（~10-50ms per entry），1000 条 entry 可能增加 10-50 秒。

**缓解**：
- 在 CLI 输出中显示进度（"Encoding embeddings: 123/1000"）
- 文档中说明首次 ingest 耗时增加是一次性成本
- 后续查询受益（P95 latency -30%）

**不缓解**：批量 encode（sentence-transformers 支持 batch）→ 留给 v1.6.3 优化，v1.6.2 先验证架构可行性。

### Risk 3: shootout 耗时过长（≥30 分钟）

**风险**：三模型各跑 500 题 LongMemEval，每次 ~10 分钟，总计 30+ 分钟。

**缓解**：
- shootout 工具输出进度（"Running bge-small: 123/500"）
- 支持 `--models` 参数只跑部分模型（debug 用）
- 结果缓存到 JSON，支持断点续跑

**接受**：shootout 是一次性决策流程，30 分钟可接受。

### Risk 4: 向量维度不匹配导致查询失败

**风险**：用户切换 384-dim → 768-dim 模型后，老向量维度不匹配。

**缓解**：
- 查询时检测维度不匹配，log warning 并跳过该向量
- `harness-mem doctor` 检测维度不匹配并提示 rebuild
- 如果所有向量都不匹配，fallback FTS

### Risk 5: LongMemEval 五维 R@5 回退

**风险**：持久化向量路径可能引入 bug，导致 R@5 下降。

**缓解**：
- v1.6.2 提交前必须跑 LongMemEval，验证至少 3 个维度不回退
- 如果回退，rollback 到 v1.6.1 并 debug
- 单测覆盖：持久化向量与实时 encode 结果一致

## Migration Plan

### Phase 1: 开发与单测（Week 1）
1. 实现 `vec_embeddings` 表 schema 与迁移逻辑
2. 实现写入路径（ingest/save 时持久化）
3. 实现查询路径（SQL JOIN）
4. 单测覆盖：写入即可查、二次启动不重新 encode、model_id 过滤

### Phase 2: shootout 与决策（Week 1-2）
1. 实现 `harness_mem.tools.embedding_shootout`
2. 跑三模型 LongMemEval
3. 应用决策规则，生成 `docs/benchmark/v162-embedding-shootout.md`
4. 更新 `pyproject.toml` 默认模型（如果需要）

### Phase 3: 升级路径与错误处理（Week 2）
1. 实现 `harness-mem maintenance rebuild-vector-index`
2. 实现 `harness-mem doctor` 检测（HM-201/HM-202/HM-203）
3. 实现 fallback FTS 逻辑（缺 vec_embeddings 表）
4. 单测覆盖：升级路径、错误码、fallback

### Phase 4: 集成测试与验收（Week 2）
1. 跑 LongMemEval 验证五维 R@5 不回退
2. 实测 P95 latency ≤437ms
3. 更新 CHANGELOG.md 与 docs/roadmap-v16x.md
4. 提交 PR，走 OpenSpec archive 流程

### Rollback 策略
- 如果 v1.6.2 引入严重 bug，用户可降级到 v1.6.1
- `vec_embeddings` 表不影响 v1.6.1 运行（v1.6.1 不读该表）
- 用户可删除 `vec_embeddings` 表回到纯 FTS 模式

## Open Questions

1. **sqlite-vec 版本锁定**：0.1.x 系列 API 稳定吗？需要锁定到 0.1.0 还是 >=0.1.0,<0.2.0？
   - **决策**：先用 `>=0.1.0`，如果 0.1.x 有 breaking change 再锁定
2. **批量 encode 优化**：sentence-transformers 支持 batch encode，是否在 v1.6.2 实现？
   - **决策**：v1.6.2 先单条 encode 验证架构，批量优化留给 v1.6.3
3. **向量压缩**：384/768 维 float32 占用 1.5KB/3KB per entry，是否需要量化（int8/binary）？
   - **决策**：v1.6.2 不做压缩，留给 v1.7+ 性能优化阶段
