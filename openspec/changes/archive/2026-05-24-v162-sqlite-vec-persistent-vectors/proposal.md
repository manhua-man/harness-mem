## Why

当前 hybrid search 在热路径对每个 FTS 候选池（50-200 条）实时 encode，导致 P95 latency = 625.17ms；向量不持久化，重启后重新 encode 全库；embedding 模型锁死在 all-MiniLM-L6-v2 无法升级。v1.6.2 引入 sqlite-vec 持久化向量层，把 encode 从查询热路径移到写入路径，目标 P95 ≤437ms（-30%），并通过三模型 shootout 数据驱动决策默认 embedding 模型。

## What Changes

- **sqlite-vec 强制依赖**：`pip install "harness-mem[hybrid]"` 强制带 sqlite-vec；verbatim_index.sqlite / structured_index.sqlite 增加 `vec_*` 表存 384/768 维向量
- **写入路径持久化向量**：ingest / save 时落盘 embedding，带 model_id / model_version 元数据
- **查询路径走 SQL JOIN**：`HybridSearchLayer._search_hybrid` 改为 SQL JOIN 已持久化向量，候选池不再调 `model.encode`；query embedding 仍实时算（1 次）
- **向量层 schema 升级路径**：缺 `vec_*` 表时 fallback FTS；`harness-mem doctor` 检测并提示；新增 `harness-mem maintenance rebuild-vector-index` 一键重建
- **embedding 模型可配置**：支持 all-MiniLM-L6-v2 / bge-small-en-v1.5 / nomic-embed-text-v1.5 三选一；换模型后老向量按 model_version 自动过滤
- **embedding shootout 决策流程**：在 v1.6.0 五维 baseline 上跑三模型，按 roadmap-v16x.md "已决策 3" 三条规则匹配，决策文档落盘到 `docs/benchmark/v162-embedding-shootout.md`

## Capabilities

### New Capabilities
- `persistent-vector-storage`: sqlite-vec 集成，vec_* 表 schema，写入/读取/升级路径
- `embedding-model-selection`: 多模型支持，model_id/model_version 元数据，换模型后向量过滤
- `embedding-shootout`: 三模型 LongMemEval 五维评测，决策规则匹配，报告生成

### Modified Capabilities
- `hybrid-search`: 查询路径从"FTS 候选池 + 实时 encode + RRF"改为"FTS 候选池 + SQL JOIN 持久化向量 + RRF"；P95 latency 目标 ≤437ms

## Impact

- **依赖变更**：pyproject.toml `[hybrid]` 新增 `sqlite-vec>=0.1.0`（强制）
- **schema 变更**：verbatim_index.sqlite / structured_index.sqlite 增加 `vec_embeddings` 表（自动迁移）
- **性能变更**：hybrid search P95 latency 预期下降 30%；首次 ingest 耗时增加（一次性 encode 成本）
- **配置变更**：`~/.harness-mem/config.toml` 新增 `[embedding] model_id` 可选配置
- **CLI 变更**：`harness-mem maintenance` 新增 `rebuild-vector-index` 子命令
- **错误码变更**：`docs/error-codes.md` 新增 HM-2xx 系列（向量层错误）
- **测试变更**：新增 `tests/storage/test_vector_storage.py` / `tests/benchmark/test_embedding_shootout.py`
