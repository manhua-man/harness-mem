# v160-eval-and-typing

## Why

`v1.5.x` 把 baseline 做扎实之后，`v1.6.x` 的 vision（[`docs/roadmap-vision-v16-v18.md`](../../../docs/roadmap-vision-v16-v18.md) 与 [`docs/roadmap-v16x.md`](../../../docs/roadmap-v16x.md)）确认了三件事必须做：

1. 持久化向量索引（sqlite-vec），降 P95 latency
2. wake-up 按记忆类型分桶预算 + distill 只读安全边界
3. embedding 模型评估并升级

这三件事一次落地的失败概率太高——`v1.5.2` 已经因为没有按维度评估，差点把"调 RRF 权重"当主线。所以本次 change 是 v1.6.x 的**第一切片**，主题是**先做测量地基与类型化 schema，不动行为**：

- 把 LongMemEval `per_type` 输出晋升为一等公民，给 v1.6.1 / v1.6.2 提供可归因的五维评分
- `MemoryEntry` 加 `memory_type: episodic|semantic|procedural` 显式字段，并给老数据写一次幂等 backfill
- 把 `memory_type` 在 search payload 里**只读暴露**，不消费、不 filter——任何行为变化留给 v1.6.1

这次 change 的边界判定原则：**只动 schema 与 measurement，不动 retrieval / wake-up / distill 路径行为**。

## What Changes

- `MemoryEntry` 增加 `memory_type: Literal["episodic", "semantic", "procedural"]`，默认 `semantic`，`from_dict` 兼容老数据并按 `category` 自动派生
- 新增 `harness-mem maintenance assign-memory-types --dry-run / --apply`，对现有 `MemoryEntry` 一次性 backfill `memory_type`，幂等
- `MemoryEntry.memory_type` 在 MCP `search_memory` / REST `/search` / CLI search 输出里**只读暴露**
- `harness_mem.tools.longmemeval` 的 `per_type` 字段晋升为一等公民：CLI 输出对齐打印 + JSON 报告必须包含 `per_type`
- 登记 `LONGMEMEVAL_QUESTION_TYPES` 常量，未知维度产生 warning 而不是被静默吞
- 新增 `docs/benchmark/longmemeval-five-dimensions.md`，记录五维含义与当前 baseline；新增 `docs/benchmark/v160-baseline.md` 写入 v1.6.0 启动当日的五维基线

## Out of Scope

- **wake-up 按 `memory_type` 分桶**——v1.6.1
- **distill 只读边界**——v1.6.1
- **search 按 `memory_type` filter**——v1.6.1
- **持久化向量索引（sqlite-vec）**——v1.6.2
- **embedding 模型升级**——v1.6.2
- **`procedural` 类型的实际产生路径**——v1.8（vision 文档已划界）
- **bi-temporal / supersede / valid_from / valid_to**——v1.7
- **修改 `category` 字段**——`memory_type` 是新维度，不替换 `category`
- **跨项目维度的 `memory_type` 统计**——v1.6.0 不引入
