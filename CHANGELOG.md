# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

(no changes yet)

---

## [1.6.0] — 2026-05-17

**主题：测量地基 + 记忆分型 schema（非破坏性 baseline 切片）**

v1.6.x 三切片路线的第一刀。本切片只动 schema 与测量层，不动 retrieval / wake-up / distill 行为；为 v1.6.1（wake-up bucket budget + distill 只读边界）与 v1.6.2（sqlite-vec 持久化向量 + embedding 模型 shootout）打地基。

完整决策与 baseline 见 [`docs/roadmap-v16x.md`](docs/roadmap-v16x.md) 与 [`docs/benchmark/v160-baseline.md`](docs/benchmark/v160-baseline.md)。

### Added

- **`MemoryEntry.memory_type` 字段**：新增 `Literal["episodic", "semantic", "procedural"]`，默认 `semantic`。`from_dict` 兼容老数据：缺字段时按 `category` 自动派生（`architecture / convention / api / bug / decision -> semantic`，否则 `episodic`）。`procedural` 字面量保留供 v1.8 使用，v1.6.0 不主动产生。
- **`MemoryType` 类型别名**：从 `harness_mem.core.schemas` 顶层导出。
- **`harness-mem maintenance assign-memory-types`**：一次性幂等 backfill 命令，把 `memory_type` 持久化到老 `MemoryEntry` JSON blob。`--dry-run` 默认；`--apply` 落盘；连续 `--apply` 后再次 `--dry-run` 显示 0 条变更。
- **search payload 暴露 `memory_type`**：CLI / MCP `search_memory` / REST `/search` 三端在 memory entry 行返回 `memory_type` 字段（只读，v1.6.1 才引入按类型 filter）。CLI 输出格式从 `[category]` 改为 `[category/memory_type]`。
- **LongMemEval 五维评分作为一等公民**：`harness_mem.tools.longmemeval` 顶部声明 `LONGMEMEVAL_QUESTION_TYPES` 常量（6 个登记维度）；CLI 输出 `PER-TYPE RECALL` 段；JSON 报告含 `per_type` 字典；未登记维度产生 `UserWarning`，不阻断评测。
- **v1.6.0 LongMemEval baseline**：`docs/benchmark/v160-baseline.md` 记录 `fts / hybrid (synthetic) / hybrid (real)` 三种 mode 在 6 个维度的 R@5；`hybrid (real) avg = 0.953`，精确复现 v1.5.2/v1.5.3 数字。`docs/benchmark/longmemeval-five-dimensions.md` 解释每个维度含义与 v1.6.x 各切片预期。
- **v1.6.x roadmap**：`docs/roadmap-v16x.md` 写明三切片切分、决策路径、不回退判定规则。

### Changed

- `docs/README.md` 登记 `roadmap-v15x` / `roadmap-v16x` / `roadmap-vision-v16-v18` 三份 roadmap，并更新 benchmark 目录条目。
- `tests/conftest.py` 把 `maintenance` 模块加入 `DEFAULT_DATA_DIR` monkeypatch 列表。

### Notes

- v1.6.0 是非破坏性切片：v1.5.3 用户升级后不需要任何数据迁移。`MemoryEntry.from_dict` 在加载时即 derive `memory_type`，`maintenance assign-memory-types` 是把它显式持久化到 JSON 的运维入口，不是必需步骤。
- LongMemEval 总分不再作为单一 KPI——v1.6.x 起所有 retrieval 改动必须贴五维对比表。详见 `docs/benchmark/longmemeval-five-dimensions.md` "为什么单一总分会误导" 段。
- v1.6.2 默认 embedding 模型不在启动前预选，由 shootout 数据驱动；详见 `docs/roadmap-v16x.md` "已决策 3"。

---

## [1.5.3] — 2026-05-17

**主题：发布闭环与归档增量化**

### Added

- **Codex archive 增量 cursor**
  - `CodexArchiveAdapter` 现在按 `mtime_ns + size_bytes` 持久化 cursor。
  - `harness-mem ingest codex-archive` 支持默认增量扫描与 `--full-rescan` 显式回扫。
  - 已补 `tests/cli/test_ingest_codex_archive.py` 覆盖缺目录、增量追加、full-rescan 去重三条路径。
- **PyPI 发布链路**
  - 新增 tag 触发的 `.github/workflows/publish.yml`，构建 wheel + sdist,执行 `twine check`，并在发布前 smoke install 两种发行物。
- **Doctor 错误码目录**
  - `harness-mem doctor` 现在输出 `code: HM-xxx` 与对应修复命令。
  - 新增 `docs/error-codes.md` 作为稳定对照表。

### Changed

- `README.md` 现在把 `pip install harness-mem` 作为默认安装入口，保留 editable install 作为仓库开发路径。
- `pyproject.toml` 增加 `dev` optional dependency，并把 `README.md` / `docs/error-codes.md` 纳入发行物元数据。
- `test-matrix.yml` 改为使用仓库标准验证栈：`pytest` + `mypy` + `ruff`。
- **MCP `search_memory` 工具签名调整**：`query` 提到第一位、`project_name` 改为可选关键字参数（`scope=all` 时省略即可）。MCP 客户端按 `input_schema` 字段名传参不受影响；任何按位置传参的内部脚本必须改成关键字传参。
- **MCP `tool_search_memory` 内部合并 event loop**：之前每次请求会执行 4 次 `asyncio.run`（search / search_relation_facts / 循环 touch / build context map），现在合并为单次 `asyncio.run` 调用 `_gather_search_payload`。Backend 连接池在一次请求内保持活跃。返回字段不变。
- **`HybridSearchLayer` 的 RRF 参数提到模块级常量**：`DEFAULT_RRF_K / DEFAULT_FTS_WEIGHT / DEFAULT_VECTOR_WEIGHT / DEFAULT_FTS_CONFIDENCE_EXPONENT / DEFAULT_VECTOR_CONFIDENCE_EXPONENT`，并在源码注释里诚实记录这些值是经验值而非 ablation 结果，留待 v1.6 embedding 升级时一并复评。

### Notes

- v1.5.2 的 `hybrid` P95 latency `625.17ms` 是 LongMemEval 全量带 vector encode 的端到端数据，**与 v1.5.1 baseline 文档里 wake-up 数据加载 `25.57ms` 的 P95 不可直接相比**。
- v1.5.2 引入的 Porter-stem FTS fallback 会把 token 用前缀匹配扩散（`auth` -> `auth*` 命中 `auth_handler / auth_handler_v2`），这是 LongMemEval session_id-only 评分体系下不可见的 precision 副作用。代码符号搜索 / 完全匹配场景请显式 `mode="fts"` 并配合精确查询；细节见 `docs/benchmark/v152-recall-failure-analysis-stemfallback.md`。

## [1.5.0] — 2026-05-16

**主题：The 4-Role Memory Loop (4 角色记忆闭环)**

本版本正式确立了 harness-mem 的核心协作协议，实现了“历史归档集成”与“AI 原生工作流”的深度统一。

| 角色 | 动作与职责 | 最佳技术载体 |
| :--- | :--- | :--- |
| **AI（操作者/后端）** | 批量读取旧 Session，用强大的 LLM 提炼知识，过滤废话，生成结构化记忆。 | Skill (如 `session-distill`) |
| **AI（操作者/随手）** | 在日常写代码中，顿悟了某个规则，随手记下一笔。 | MCP (调用 `suggest_rule`) |
| **人（审查者）** | 不看几万字的废话，只看 AI 提炼好的结论，点确认 (Confirm) 或拒绝 (Reject)。 | CLI (`confirm` / `reject`) |
| **AI（消费者/前端）** | 在新 Session 中，自动读取之前人确认过的记忆 (Wake/Search)，应用到任务。 | MCP (`search_memory`) |

### Added

- **Codex 历史归档集成 (Legacy Activation)**
  - 移植了 OneDrive 版 `session-distill` 的高精度解析算法，支持 `rollout-*.jsonl` 格式。
  - 新增 `CodexArchiveAdapter` 适配器，支持 `harness-mem ingest codex-archive`。
  - 自动清洗 IDE 上下文模板、转义字符及 `<turn_aborted>` 标记。
- **Repo-local Codex plugin wrapper**
  - Added `plugins/harness-mem/` with a Codex plugin manifest, harness-mem skill, MCP server config, and PowerShell install/doctor helpers.
  - Added `.agents/plugins/marketplace.json` entry for local plugin discovery.

### Removed
- **Temporal Bias feature** — removed `--temporal-bias` CLI flag, `temporal_bias` MCP/REST API parameter, and all related code. Benchmark evidence showed it was ineffective.

### Changed
- **文档体系大重构**
  - 重写 `best-practices.md`：转向“4 角色协作”与“候选层”核心机制。
  - 重写 `session-distill` Skill 定义：废弃本地文件 Packet 流，拥抱 Python 原生与 MCP 接口。
  - 生成 `retrospective-v13-v14.md`：归档“八方评审”结论，确立架构演进真值。
- **检索与 Ingest 体验硬化**
  - 增量 ingest 现在使用 `last_ingest_session_id` 作为精准游标。
  - search / MCP 显示实际检索模式（requested vs effective），显式展示 fallback。
  - `purge` 增强：支持 `-p/--project`，修复 UTC 时间戳比较崩溃及 `compacted` 列缺失问题。
- **Parity & API**
  - `search_memory` MCP 工具支持 `mode` 参数。
  - REST API 稳定性增强，修复 `/search` 的项目隔离与异步初始化。

### Fixed
- **真实项目体验**
  - `ingest claude-code` 支持通过 `cwd` 识别项目根目录，适配 Unity 等复杂工程布局。
  - Unity profile 自动探测（C#、ProjectVersion、manifest 等）。
  - Claude observation 摘要逻辑优化，保留上下文首尾。
  - FTS 索引中英混排 Token 分词优化。

---

## [1.2.0] — 2026-04-25

### Added

- **`wake-up` explainability**
  - 每块 section 标题追加来源注释：`## Project Profile  (source: profile, ~N chars)`
  - 空数据区块显示 `(source: {category}, empty)` 而非跳过，保持结构一致

- **Compact Guard（提示文字）**
  - `doctor` 和 `wake-up` 在 L3/L4+ 时打印 Compact suggestion
  - 建议运行 `harness-mem ds --category bug` / `decision`

- **`profile --edit`（merge 策略）**
  - 交互式编辑 profile 字段：`description`、`stacks`、`key_files`、`conventions`
  - 新值覆盖对应字段，其他字段保留

---

## [1.0.1] — 2026-04-24

**定位**：v1 稳定化 / 体验收口版本。

### Added
- **`quickstart` 命令**：一步完成初始化、活动项目设置、最近 session 发现。
- **`doctor` 命令**：状态感知决策树建议。
- **Active project 记忆**：不必重复指定 `--project`。

---

## [1.0.0] — 2026-04-23

**定位**：v1 Core MVP。

### Added
- **双层记忆底座**：Verbatim (Observation) + Structured (Entry/Rule/Handoff)。
- **Adapter**：Claude Code + Codex。
- **MCP Server**：完整读取/写入工具链。
