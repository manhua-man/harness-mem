# v161 Tasks

## 1. wake-up 三桶预算

- [x] 在 `harness_mem/wake_selection.py` 加入 `select_wake_memory_entries_with_buckets(entries, limit, quotas, enabled)`，与现有 `select_wake_memory_entries` 共存（后者在 enabled=False 时复用）
- [x] 在 `harness_mem/commands/support.py` 增加 `wake_bucket_quotas(config) -> dict[str, float]` 与 `wake_bucket_enabled(config) -> bool`；非法配额抛 `WakeBucketQuotaError(message, code="HM-101")`
- [x] 在 `harness_mem/commands/wake.py` 调用 `select_wake_memory_entries_with_buckets`，header 输出 `bucket quotas` / `bucket fill` 行；超额时输出 `[truncated within bucket: <type> X/Y]`
- [x] CLI 注册 `harness-mem wake --no-bucket-quota`；`cmd_wake_up` 接受 `no_bucket_quota: bool`
- [x] `tests/wake/test_bucket_budget.py`：8 个 Scenario（默认配额 / 关闭 / 单桶溢出 / 桶让渡 / 非法配额抛错 / procedural=0 空桶 / 默认值 / enabled flag）
- [x] doctor 注册 `HM-101 / HM-102` 错误码 + `docs/error-codes.md` 更新

## 2. distill 只读边界

- [x] 新建 `harness_mem/distill_context.py`：`DistillContext` 类 + `DistillReadOnlyError` 异常
- [x] `cmd_distill` 入口构造 `DistillContext(backend)`，把 `backend.structured_store` 不再暴露给 adapter；`ClaudeCodeAdapter.distill_session / distill_relation_facts` 改为接受 `distill_context: DistillContext`
- [x] adapter 内部所有 `save_memory_entry / save_relation_fact` 走 `DistillContext.suggest_memory_entry / suggest_relation_fact`，写入时 status=`pending`
- [x] `tests/distill/test_readonly_boundary.py`：DistillContext 不暴露 `.delete / .update`；尝试调用 raise `DistillReadOnlyError`（9 个用例覆盖）
- [x] `tests/distill/test_readonly_boundary.py::test_suggest_memory_entry_persists_pending` + `test_auto_confirm_via_cli_helper_flips_status`：distill 默认产 pending 记忆 + `--auto-confirm` 兼容旧行为
- [x] `tests/cli/test_distill.py::test_cmd_distill_default_writes_pending_candidates`：CLI 默认 pending 输出契约

## 3. search 按 memory_type filter

- [x] `harness_mem/storage/local_structured_store.py` 的 `search_memory_entries` 增加 `memory_type: list[str] | None = None` 参数；SQL 层 WHERE 过滤
- [x] `harness_mem/storage/sqlite_index.py` 的 `memory_entries` schema 增加 `memory_type` 列与 `_COLUMN_MIGRATIONS` 自动迁移
- [x] `harness_mem/core/interfaces/structured_store.py` Protocol 同步增加 `memory_type` 参数
- [x] `harness_mem/read_api.py` 的 `search_memory` 透传 memory_type
- [x] `harness_mem/mcp/server.py` 的 `tool_search_memory` 工具 `input_schema` 增加 `memory_type: array<string>` 可选参数 + 非法值 422-class 错误
- [x] `harness_mem/api/models.py` 的 `/search` 请求模型增加 `memory_type` 列表 + `harness_mem/api/server.py` 的 `/search` route 接受重复 query param
- [x] `harness_mem/commands/search.py` 增加 `--memory-type <type>` 多值 CLI flag
- [x] `tests/test_memory_type_search_payload.py`：CLI / MCP / REST 三端 ✕ {未传 / 单值 / 多值 / 非法值} 共 4 个新增 Scenario

## 4. distill `--auto-confirm` 兼容 flag

- [x] CLI `harness-mem distill --auto-confirm` 把 distill 输出从 pending 转为 accepted（通过 `_confirm_pending_outputs` helper 走 `update_*_status` mutator，而非 `DistillContext`）
- [x] `tests/cli/test_distill.py::test_cmd_distill_default_writes_pending_candidates` + `tests/cli/test_search_and_wake.py::test_best_practices_claude_mainline_flow` 覆盖默认 pending 与 `--auto-confirm` accepted

## 5. baseline 与文档

- [x] 跑 `python -m harness_mem.tools.longmemeval <dataset> --mode hybrid --top-k 5 --use-real-hybrid --out benchmarks/results/v161-baseline-hybrid.json`：总 R@5 = 0.953，五维与 v1.6.0 baseline 一字不差
- [x] 写入 `docs/benchmark/v161-bucket-budget-impact.md`：五维 R@5 对比表 + 解释"为什么 v1.6.1 不应改变 LongMemEval 结果"
- [x] CHANGELOG 草拟 `[1.6.1]` 段，登记 breaking 改动（distill 默认 pending）
- [x] `docs/error-codes.md` 登记 HM-101 / HM-102
- [x] `docs/README.md` 追加 `v161-bucket-budget-impact.md` 索引
- [x] `docs/roadmap-v16x.md` 标记 v1.6.1 段为已完成

## 6. Validation

- [x] `python -m pytest -q` 全绿（286 passed in 225.76s）
- [x] `python -m ruff check .` 无警告
- [x] `python -m mypy harness_mem` 无错误
- [x] LongMemEval 五维：6 维度 0 回退，总 R@5 与 v1.6.0 baseline 完全相同（0.953）
- [x] `openspec validate 2026-05-19-v161-bucket-budget-and-distill-readonly` 通过；后续 `openspec validate --all --strict` 也覆盖该 change。
