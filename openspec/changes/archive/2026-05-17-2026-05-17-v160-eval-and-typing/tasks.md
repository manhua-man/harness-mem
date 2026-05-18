# v160-eval-and-typing Tasks

## Schema 与 storage

- [x] 在 `harness_mem/core/schemas/memory_entry.py` 增加 `memory_type: Literal["episodic", "semantic", "procedural"]`，默认 `semantic`
- [x] `MemoryEntry.from_dict` 兼容老数据：缺 `memory_type` 时按 `category` 自动派生（`bug / decision / architecture / convention / api -> semantic`，无对应 -> `episodic`）
- [x] `MemoryEntry.to_dict` 输出 `memory_type` 字段
- [x] 在 `harness_mem/core/schemas/__init__.py` 导出 `MemoryType` 类型别名（`Literal["episodic", "semantic", "procedural"]`）
- [x] 补 `tests/storage/` 用例：老 JSON blob 加载零回归，派生规则覆盖 5 类 category + catch-all
- [x] 补 `tests/storage/` 用例：`memory_type` 字段在 `to_dict / from_dict` 往返一致

## Backfill 命令

- [x] 在 `harness_mem/commands/` 增加 `maintenance.py`，实现 `assign_memory_types(project: str, dry_run: bool)`
- [x] CLI 注册 `harness-mem maintenance assign-memory-types --dry-run / --apply`，默认 dry-run
- [x] 命令输出每条变更的 `(id, category, derived memory_type)` 与汇总数字
- [x] 命令幂等：`--apply` 第二次运行变更数为 0
- [x] 补 `tests/cli/test_maintenance.py`：dry-run 不写、apply 写完后 dry-run 显示 0、缺活动项目时报错
- [x] 文档：在 `README.md` "CLI 命令" 表格里登记新命令

## search payload 暴露 `memory_type`

- [x] `harness_mem/read_api.py` 中拼装 search row 时附带 `memory_type`
- [x] MCP `search_memory` 工具返回 payload 增加 `memory_type` 字段
- [x] REST `/search` 返回 payload 增加 `memory_type` 字段
- [x] CLI `search` 输出格式增加 `memory_type` 显示（紧跟 `category` 后面，避免破坏现有列宽）
- [x] 三端契约测试覆盖新字段
- [x] **不允许**为 search 增加 `memory_type` filter 参数（v1.6.1 才做）

## LongMemEval 五维报告

- [x] 在 `harness_mem/tools/longmemeval.py` 顶部声明 `LONGMEMEVAL_QUESTION_TYPES = frozenset({"multi-session", "temporal-reasoning", "single-session-user", "single-session-preference", "single-session-assistant", "knowledge-update"})`
- [x] 数据加载阶段对未知 `question_type` 产生 `warnings.warn(...)`，不阻断
- [x] CLI 输出的 `PER-TYPE RECALL` 段按维度名字典序对齐打印（已有逻辑，本次只确认与登记常量一致）
- [x] JSON 报告 `per_type` 字段保持现有 schema：`{question_type: avg_recall}`
- [x] 补 `tests/benchmark/test_longmemeval_per_type.py`：验证 6 个登记维度归类正确、未知维度 warning

## Baseline 与文档

- [x] 新增 `docs/benchmark/longmemeval-five-dimensions.md`：每个维度的含义、典型问法、当前 baseline 数字
- [x] 新增 `docs/benchmark/v160-baseline.md`：跑 `fts / hybrid / hybrid-stemfallback` 三种模式的全量 + 五维 R@5
- [x] 在 `docs/README.md` 登记两份新文档
- [x] 在 `CHANGELOG.md` 草拟 `[1.6.0]` 段落（标记为 `## [Unreleased]` 直到发版）

## Validation

- [x] `python -m pytest -q` 全绿
- [x] `python -m ruff check .` 无警告
- [x] `python -m mypy harness_mem` 无错误
- [x] `python -m pytest tests/storage/test_memory_entry.py tests/cli/test_maintenance.py tests/benchmark/test_longmemeval_per_type.py -q` 全绿
- [x] `python -m harness_mem.tools.longmemeval <dataset> --mode hybrid --top-k 5 --use-real-hybrid --out benchmarks/results/v160-baseline-hybrid.json` 输出 5 个维度 R@5
- [x] `openspec validate 2026-05-17-v160-eval-and-typing`
