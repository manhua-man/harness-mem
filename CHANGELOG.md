# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [1.5.3] — 2026-05-17

**主题：发布闭环与归档增量化**

### Added

- **Codex archive 增量 cursor**
  - `CodexArchiveAdapter` 现在按 `mtime_ns + size_bytes` 持久化 cursor。
  - `harness-mem ingest codex-archive` 支持默认增量扫描与 `--full-rescan` 显式回扫。
  - 已补 `tests/cli/test_ingest_codex_archive.py` 覆盖缺目录、增量追加、full-rescan 去重三条路径。
- **PyPI 发布链路**
  - 新增 tag 触发的 `.github/workflows/publish.yml`，构建 wheel + sdist，执行 `twine check`，并在发布前 smoke install 两种发行物。
- **Doctor 错误码目录**
  - `harness-mem doctor` 现在输出 `code: HM-xxx` 与对应修复命令。
  - 新增 `docs/error-codes.md` 作为稳定对照表。

### Changed

- `README.md` 现在把 `pip install harness-mem` 作为默认安装入口，保留 editable install 作为仓库开发路径。
- `pyproject.toml` 增加 `dev` optional dependency，并把 `README.md` / `docs/error-codes.md` 纳入发行物元数据。
- `test-matrix.yml` 改为使用仓库标准验证栈：`pytest` + `mypy` + `ruff`。

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
