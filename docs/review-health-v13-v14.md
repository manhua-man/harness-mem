# Health 代码质量仪表盘：harness-mem v1.2.0

> 生成时间：2026-04-25
> 源码目录：`harness_mem/` (30 Python 文件)
> 测试目录：`tests/` (7 Python 文件，6 个 pytest 测试类，43 个测试用例)

---

## 1. 测试结果

```
43 passed in 3.82s
```

| 测试文件 | pytest 计数 | 结果 |
|----------|-------------|------|
| `test_cli_flows.py` | 24 个 (pytest) | PASS |
| `test_cli_ux.py` | 8 个 (pytest) | PASS |
| `test_distill_and_search.py` | 6 个 (pytest) | PASS |
| `test_mcp_smoke.py` | 3 个 (pytest) | PASS |
| `test_project_profile_detector.py` | 2 个 (pytest) | PASS |
| `e2e_test.py` | 非 pytest (无类/函数) | 未执行 |
| `longmemeval_bench.py` | 非 pytest (基准测试) | 未执行 |

**结论：43/43 全部通过，0 失败。**

---

## 2. Lint 检查 (ruff)

**22 个错误**，其中 **20 个可用 `--fix` 自动修复**，2 个需 `--unsafe-fixes`。

### 按规则分组

| 规则 | 数量 | 描述 |
|------|------|------|
| F541 | 8 | 无占位符的 f-string（`f"..."` 应为 `"..."`） |
| F401 | 11 | 未使用的 import |
| F841 | 3 | 未使用的局部变量 |

### 按文件分组

| 文件 | 错误数 | 详情 |
|------|--------|------|
| `cli.py` | 8 | 7x F541 (无占位符 f-string 打印标题), 1x F841 (`project_obs`) |
| `cli_commands.py` | 1 | 1x F541 (无占位符 f-string) |
| `adapters/claude_code/adapter.py` | 1 | 1x F841 (`except Exception as e` 中 `e` 未使用) |
| `adapters/codex/adapter.py` | 1 | 1x F401 (`import asyncio` 未使用) |
| `core/schemas/confirmed_rule.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `core/schemas/memory_entry.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `core/schemas/observation.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `core/schemas/project_profile.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `core/schemas/rule_candidate.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `core/schemas/task_handoff.py` | 1 | 1x F401 (`typing.Optional` 未使用) |
| `storage/local_memory_backend.py` | 1 | 1x F401 (`MemoryBackend` import 未使用) |
| `storage/local_project_profile_store.py` | 2 | 1x F401 (`asyncio`), 1x F401 (`ProjectProfileStore`) |
| `storage/local_structured_store.py` | 1 | 1x F401 (`StructuredStore` import 未使用) |
| `storage/local_verbatim_store.py` | 1 | 1x F401 (`VerbatimStore` import 未使用) |
| `storage/sqlite_index.py` | 1 | 1x F841 (`cursor` 未使用) |

### 模式分析

- **6 个 schema 文件** 全都 import `typing.Optional` 却从未使用（pydantic v2 使用 `| None` 语法），疑似 pydantic v1→v2 迁移遗留。
- **4 个 storage 文件** import 了接口基类但实际未用于类型注解，Python 运行时无此约束。
- **`cli.py`** 有 7 处无意义 f-string，用于打印纯文本标题。

---

## 3. 类型检查 (mypy)

**26 个类型错误**，分布在 **7 个文件**中（共检查 30 个源文件）。

### 按文件分组

| 文件 | 错误数 | 典型问题 |
|------|--------|----------|
| `cli.py` | 6 | `None` 传给 `MemoryBackend` 构造器 (2), `list?[Observation]` 不可迭代 (2), 适配器类型赋值不兼容 (1), `str.join(list[str] | None)` (1) |
| `mcp/server.py` | 4 | `list?[Observation]` 不可迭代 (2), `object.get()` 不存在 (1), `object` 不可调用 (1) |
| `storage/sqlite_index.py` | 4 | 方法名用作类型注解 (2), `list?[str]` 不可迭代 (2) |
| `adapters/codex/adapter.py` | 3 | `Sequence[str]` 没有 `.append()` (3) |
| `adapters/claude_code/adapter.py` | 3 | `sorted()` key 函数返回类型不兼容 (1), `Sequence[str]` 没有 `.append()` (2) |
| `core/interfaces/verbatim_store.py` | 2 | 方法 `list` 被用作类型注解 -- 应为 `Callable[[...], ...]` (2) |
| `storage/local_verbatim_store.py` | 2 | 同上模式 (2) |

### 根因聚类

| 聚类 | 计数 | 影响文件 |
|------|------|----------|
| `list?[T]` 不可迭代（方法返回 `Optional[list[T]]` 但调用方不加守卫直接遍历） | 5 | `sqlite_index.py`, `mcp/server.py`, `cli.py` |
| `Sequence[str]` 没有 `.append()`（应为 `list[str]` 类型注解） | 5 | `codex/adapter.py`, `claude_code/adapter.py` |
| 方法名 `list` 被用作类型注解（应为 `Callable[[...], ...]`） | 4 | `sqlite_index.py`, `verbatim_store.py`, `local_verbatim_store.py` |
| 类型不匹配 / `object` 当作 `Callable` 处理 | 7 | `cli.py`, `mcp/server.py` |
| 构造器传入 `None` 类型不兼容 | 2 | `cli.py` |

---

## 4. 文件行数与复杂度

### 源文件行数排名

| 排名 | 文件 | 行数 | 占总源码比 |
|------|------|------|-----------|
| 1 | `harness_mem/cli.py` | **1,242** | 29.0% |
| 2 | `harness_mem/mcp/server.py` | 589 | 13.7% |
| 3 | `harness_mem/storage/sqlite_index.py` | 361 | 8.4% |
| 4 | `harness_mem/storage/local_structured_store.py` | 350 | 8.2% |
| 5 | `harness_mem/adapters/claude_code/adapter.py` | 324 | 7.6% |
| 6 | `harness_mem/cli_commands.py` | 236 | 5.5% |
| 7 | `harness_mem/adapters/codex/adapter.py` | 179 | 4.2% |
| 8 | `harness_mem/storage/local_verbatim_store.py` | 158 | 3.7% |
| 9 | `harness_mem/adapters/claude_code/project_profile_detector.py` | 124 | 2.9% |
| 10 | `harness_mem/core/interfaces/structured_store.py` | 110 | 2.6% |
| 其余 20 个文件 | 各 < 70 行 | 总计 ~611 | 14.2% |
| **总计** | **30 个文件** | **4,284** | 100% |

### cli.py (1,242 行) 复杂度分析

- 第 157 行：`await ClaudeCodeAdapter(None)` — 显式传入 `None` 给构造器
- 第 162 行：`await CodexAdapter(None)` — 同上模式
- 第 1055 行：`adapter: ClaudeCodeAdapter` 声明后赋值为 `CodexAdapter(backend)`，mypy 标记类型不兼容
- 第 1227 行：`",".join(file_paths)` 中 `file_paths` 为 `list[str] | None`，mypy 报错
- **职责过重**：CLI 入口 (`main`)、后端工厂 (`create_backend`)、多命令处理 (profile/ingest/distill/search/wake-up)、适配器选择全都集中在此

### 测试文件行数

| 文件 | 行数 |
|------|------|
| `test_cli_ux.py` | 504 |
| `longmemeval_bench.py` | 474 |
| `test_distill_and_search.py` | 339 |
| `e2e_test.py` | 254 |
| `test_mcp_smoke.py` | 218 |
| `test_cli_flows.py` | 172 |
| `test_project_profile_detector.py` | 25 |
| **测试总计** | **1,986** |

**源码:测试 行数比 = 4,284 : 1,986 ≈ 2.2:1**

---

## 5. import 依赖分析

```
依赖方向（单向）: core/schemas ← core/interfaces ← storage/* ← {cli, mcp, adapters}
```

- **循环导入：无**
- **架构层级边界清晰：** 所有 import 方向均为上层 → 下层
- `core/schemas/` — 零内部依赖（纯 Pydantic 模型，叶子节点）
- `core/interfaces/` — 仅依赖 `core/schemas/`
- `storage/*` — 依赖 `core/interfaces/` + `core/schemas/`
- `cli.py` / `mcp/server.py` / `adapters/*` — 依赖 `storage/`

---

## 6. TODO / FIXME / HACK / XXX

```
harness_mem/ 源码中未发现任何 TODO/FIXME/HACK/XXX 注释。
数值: 0
```

---

## 7. `__pycache__` 遗留文件

| 位置 | 目录数 | .pyc 文件数 |
|------|--------|------------|
| `harness_mem/` | 9 个子目录 | 30 个 |
| `tests/` | 1 个子目录 | 8 个 |

**评价：正常现象。** Python 3.13 运行时自动生成，应在 `.gitignore` 中排除。

---

## 8. 测试覆盖分析

### 有测试覆盖的模块

| 源模块 | 直接测试文件 | 覆盖程度 |
|--------|-------------|----------|
| `cli.py` | `test_cli_flows.py`, `test_cli_ux.py`, `test_distill_and_search.py` | 功能流 + UI + 搜索 |
| `cli_commands.py` | `test_cli_flows.py`, `test_cli_ux.py` | 间接覆盖 |
| `mcp/server.py` | `test_mcp_smoke.py` | 基础冒烟测试 |
| `project_profile_detector.py` | `test_project_profile_detector.py` | 完整 |
| `adapters/claude_code/adapter.py` | `test_cli_ux.py`, `test_distill_and_search.py` | 间接覆盖 |
| `adapters/codex/adapter.py` | `test_cli_ux.py`, `test_distill_and_search.py` | 间接覆盖 |
| `storage/local_memory_backend.py` | 5 个测试文件 import 使用 | 间接覆盖 |

### 完全没有专属测试文件的模块 (12 个)

| 模块 | 行数 | 风险等级 | 说明 |
|------|------|----------|------|
| `storage/local_structured_store.py` | 350 | **HIGH** | 存储层核心实现，无直接测试 |
| `storage/sqlite_index.py` | 361 | **HIGH** | SQLite 底层索引，有 4 个 mypy 错误，无测试 |
| `adapters/claude_code/adapter.py` | 324 | MEDIUM | 仅通过 CLI 测试间接覆盖 |
| `adapters/codex/adapter.py` | 179 | MEDIUM | 仅通过 CLI 测试间接覆盖 |
| `storage/local_verbatim_store.py` | 158 | MEDIUM | 存储实现，无直接测试 |
| `core/interfaces/structured_store.py` | 110 | LOW | 抽象基类 |
| `storage/local_memory_backend.py` | 49 | LOW | 外观类，被所有测试使用 |
| `storage/local_project_profile_store.py` | 47 | LOW | 存储实现 |
| `core/interfaces/verbatim_store.py` | 53 | LOW | 抽象基类 |
| `core/interfaces/memory_backend.py` | 34 | LOW | 抽象基类 |
| `core/interfaces/project_profile_store.py` | 23 | LOW | 抽象基类 |
| `core/schemas/*.py` (6 文件) | 364 | LOW | Pydantic 模型（通过所有测试间接使用） |

### 覆盖缺口优先级

| 优先级 | 模块 | 行数 | 建议 |
|--------|------|------|------|
| **P0** | `storage/local_structured_store.py` + `storage/sqlite_index.py` | 711 | 存储核心无测试，且有类型错误 |
| **P1** | 两个 adapter | 503 | 适配器集成无直接测试 |
| **P2** | 其余 storage 实现 | 254 | 较低风险 |
| **P3** | schemas / interfaces | 584 | 间接覆盖已足够 |

---

## 9. 历史对比

| 维度 | v14 (当前) |
|------|-----------|
| 测试总数 | 43 |
| 测试通过率 | 100% |
| Lint 错误 (ruff) | 22 |
| 类型错误 (mypy) | 26 |
| 源码总行数 | 4,284 |
| 最大文件 (cli.py) | 1,242 行 |
| TODO/FIXME 标记 | 0 |
| 循环导入 | 0 |
| 无专属测试模块 | 12 |
| 源码:测试行数比 | 2.2:1 |
| `__pycache__` 目录数 | 10 |

---

## 10. 汇总仪表盘

| 类别 | 数值 | 评估 |
|------|------|------|
| 测试通过 | 43/43 | GREEN |
| Lint 错误 | 22 (20 可自动修复) | GREEN — 多数为格式问题 |
| 类型错误 | 26 | YELLOW — 3 个重复模式 |
| 死代码 | 15 (全部可自动修复) | GREEN |
| TODO 标记 | 0 | GREEN |
| 最大文件 | cli.py (1,242 行) | YELLOW — 拆分解耦候选 |
| 循环导入 | 0 | GREEN |
| 架构层级 | 单向依赖 | GREEN |

### 快速修复清单（按工作量排序）

1. **`ruff check --fix`** — 自动修复 20/22 个 lint 错误（工作量：< 1 分钟）
2. **移除 6 个 schema 文件中遗留的 `typing.Optional` import**（pydantic v1→v2 迁移遗留，自动修复已覆盖）
3. **修复 `list?[T]` 返回类型** — 3 个接口文件改为 `Optional[list[T]]`，修复约 12/26 个 mypy 错误
4. **将 `Sequence[str]` 改为 `list[str]`** — 2 个 adapter 文件，修复 5 个 mypy 错误
5. **为 `list?[T]` 返回增加守卫** — `cli.py` 和 `mcp/server.py`，修复 5 个"不可迭代"错误
6. **为 P0 模块添加单元测试** — `local_structured_store.py` + `sqlite_index.py`（~711 行无测试）

---

*报告由 `health` 工具于 2026-04-25 自动生成。工具链: pytest 4.22.4, ruff 0.11.8, mypy 1.15.0, Python 3.13.3*
