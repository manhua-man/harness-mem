# v1x-postship-regressions

## Why

`v1x-retention-stability-reset` 已经把 v1.3 / v1.4 的能力面落地，但 post-ship review 发现 5 个阻断级或高优先级回归：

1. `purge` 在真实持久化时间戳上会因 naive/aware datetime 比较直接崩溃
2. soft-delete 会写入不存在的 `compacted` 列
3. purge 后的数据仍会继续出现在 wake / search / timeline
4. 增量 ingest 只跳过单个 cursor session，导致重复导入旧 session
5. `HybridSearchLayer` 已存在但没有真正接入 CLI / MCP 的运行时查询路径

这次 follow-up change 只修回归和未接线实现，不扩 scope 到 UI、Web、adapter 扩张或更大的路线图讨论。

## What Changes

- 修复 `purge` 的 UTC-aware cutoff、SQLite schema migration、以及 compacted 默认过滤
- 修复 Claude project-scoped incremental ingest，确保不重复导入，并让 `--full-rescan` 真正生效
- 把 hybrid search 打通到 store / CLI / MCP，支持 `mode=auto|fts|hybrid`
- 为以上行为补回归测试，并把相关要求更新进 OpenSpec

## Out of Scope

- 新增 Web UI
- 新增 adapter
- 引入外部向量数据库
- 引入 reranker / graph memory / semantic chunk
- 重开 `v1.3 / v1.4` 产品路线图讨论
