# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [1.1.3] — 2026-04-24

### Added

- **`search` 增加来源层标注**
  - 每条结果明确标记来自 `structured` 或 `verbatim`
  - 降低搜索结果黑盒感，帮助用户理解双层检索逻辑

- **`doctor` 增加 wake-up budget 预警**
  - 输出当前项目的估算 wake-up token 预算
  - 当预算达到高水位（L3/L4+）时，主动提示用户考虑先 `distill` 或清理陈旧 memory

- **`distill` 支持按 category 过滤**
  - 新增 `--category` / `-c`
  - 支持只提取指定类型的结构化记忆：`architecture`、`convention`、`api`、`bug`、`decision`

---

## [1.1.2] — 2026-04-24

### Added

- **`wake` 命令增加 token budget 摘要**
  - 末尾打印一行：`Approx wake-up tokens: ≈ N [L0/L1/L2/L3/L4+]`
  - 计算与 `profile` 一致（profile text + 5 entries + all rules + 3 handoffs）
- **`status` 命令增加 budget 行**
  - 每个项目块末尾打印：`Estimated wake-up: ≈ N tokens [L0/L1/L2/L3/L4+]`
- **`distill` 输出标注 pattern 来源**
  - 每条 memory entry 打印时追加 ` (source: {category})`，明确标注是从哪个 pattern 蒸馏而来

---

## [1.1.1] — 2026-04-24

### Added

- **`profile` 命令增加 memory budget 估算**
  - 预算统计与实际 wake-up 负载完全对齐（profile + 5 entries + all rules + 3 handoffs）
  - 显示各层 token 近似值和 disclosure level（L0/L1/L2/L3/L4+）
- **`doctor` 命令显示 Stacks detected**
  - 当 profile 存在且有 stack 信息时，额外输出 `Stacks detected: python, typescript, ...`
- **`rules` 输出增加 Source session 标注**
  - 每条 Confirmed Rule 显示它来自哪条 session（`source_session_id`）

### Changed

- `ConfirmedRule` schema 新增 `source_session_id` 字段，记录来源 session
- `LocalStructuredStore` 保存 confirmed rule 时写入 `source_session_id`

### Fixed

- 修复 profile token 预算不包含 observations（实际 wake-up 不注入 observations）
- 修复 disclosure level 标注逻辑，显示实际等级值而非说明文字
- 修复空数据时 `max(1, round(...))` 导致的虚假 1 token 问题

---

## [1.0.1] — 2026-04-24

**定位**：v1 稳定化 / 体验收口版本。

### Added

- **`quickstart` 命令**
  - 一步完成初始化、活动项目设置、最近 session 发现与接入引导
  - `--client skip` 可跳过自动 ingest
- **`doctor` 命令**
  - 展示当前项目状态、最近 sessions
  - 根据现状明确建议下一步是 `ingest`、`ds` 还是 `wake`
- **Active project 记忆**
  - 不必在每条命令里重复 `--project`
  - 数据存在 `~/.harness-mem/data/active_project.txt`
- **短别名**：新增 `qs`（quickstart）、`ds`（distill）、`wake`、`tl`、`rules`
- **交互式 `correct`**
  - 缺字段时逐项提示，无需一次性手打所有参数
- **交互式 `handoff`**
  - 任务摘要、状态、next step、blocker 可逐项输入
- **`init` 自动执行**
  - 所有写入操作自动触发目录初始化，无需手动 `harness-mem init`

### Changed

- `quickstart` 后直接建议 `doctor`，不再是直接 ingest
- `doctor` 建议路径根据当前 observations / memory entries 数量动态调整
- `wake` 输出含 "Recent Tasks" 块（如果存在 handoffs）

### Fixed

---

## [1.0.0] — 2026-04-23

**定位**：v1 Core MVP，首个正式版本。

### Added

- **双层记忆底座**
  - Verbatim Layer（原始 session transcript → Observation）
  - Structured Layer（MemoryEntry / TaskHandoff / RuleCandidate / ConfirmedRule）
- **Claude Code Adapter**
  - 接入 `~/.claude/projects/{project}/*.jsonl` sessions
  - `ingest` 命令支持 `-n` 限制 session 数量
- **Codex Adapter**（minimal search-mode）
- **`distill` / `ds`**：从 sessions 提取结构化 memory entries（启发式 pattern 匹配）
- **`wake-up` / `wake`**：生成项目唤醒上下文
- **`search`**：跨 structured + verbatim 检索
- **`timeline` / `tl`**：Observation 时间线视图
- **`show`**：查看单条 Observation
- **`status` / `st`**：查看当前记忆状态
- **Learning Loop**：correct → candidate → confirm/reject → confirmed rules
- **Task Handoff / Resume**：任务续接
- **MCP Server**：`search_memory`, `timeline`, `get_observations`, `get_task_handoffs`, `get_confirmed_rules`, `get_project_profile`, `create_rule_candidate`, `confirm_rule`
- **Project Profile**：自动探测 stack（Python/TypeScript/Go/PHP 等）

---

## v1 Launch Gate 状态

| Gate | 状态 |
|------|------|
| Ingest 成立 | ✅ |
| Structured Memory 成立 | ✅ |
| Wake-up 成立 | ✅ |
| 渐进式检索成立 | ✅ |
| Learning Loop 成立 | ✅ |
| Task Resume 成立 | ✅ |
| 本地模式独立成立 | ✅ |

> 7/7 在 v1.0.1 发布前均已实现，smoke test（`scripts/smoke-v1.0.1.ps1`）验证通过。
