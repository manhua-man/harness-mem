# v1x-postship-regressions Tasks

## Purge 回归

- [x] 用 UTC-aware cutoff 修复 `purge --before`
- [x] 给 `observations` / `memory_entries` 补 `compacted` schema migration
- [x] 让 `list/search/timeline/wake` 默认过滤 `compacted`
- [x] 增加 dry-run、真实执行、以及 migration 回归测试

## 增量 ingest 回归

- [x] 让 `args.full_rescan` 真正传到 `cmd_ingest`
- [x] 用“cursor 之前的新 session 前缀”替换 `!= last_ingest_session_id`
- [x] 缺失 cursor 时打印 warning 并回退到受限扫描
- [x] 增加二次 ingest 不重复导入、full-rescan、cursor 丢失回归测试

## Hybrid Search 接线

- [x] 给 store / CLI / MCP 接口增加 `mode=auto|fts|hybrid`
- [x] 让 store 内部通过 `HybridSearchLayer` 执行查询
- [x] 在 CLI / MCP 暴露 effective mode 与 fallback reason
- [x] 增加 hybrid / fallback / CLI-MCP 一致性测试

## Validation

- [x] 触碰路径通过 `ruff check`
- [x] 触碰路径通过 `mypy`
- [x] 关键回归测试通过
- [x] 跑仓库级 `pytest -q --ignore=tests/test_api.py`
- [ ] 跑仓库级 `pytest -q`（当前环境缺 `fastapi`，`tests/test_api.py` 收集失败）
- [x] 跑仓库级 `openspec validate v1x-postship-regressions`
