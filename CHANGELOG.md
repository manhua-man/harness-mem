# Changelog

所有正式版本变更记录。格式参照 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

### Changed

- **增量 ingest 语义收紧**
  - Claude project-scoped ingest 现在把 `last_ingest_session_id` 解释为“上次 ingest 时看到的最新 session”
  - 默认只处理 cursor 之前的前缀新 session，不再重复吞旧 session
  - `--full-rescan` 现在会显式忽略 cursor 并打印 full-rescan 提示

- **search / MCP 显示实际检索模式**
  - CLI `search` 和 MCP `search_memory` 都会返回 `requested_mode` / `effective_mode`
  - embedding 不可用时会明确显示 fallback 到 FTS，而不是静默退化

- **内部自用前硬化**
  - `purge` 新增 `-p/--project`，对 `structured` / `all` 不再静默依赖活动项目
  - CLI 会把 command / next-step 事件写入本地 `events.log`
  - 新增 `hybrid` optional extra，用于显式安装 `sentence-transformers`
  - `ingest` / `wake` 对空 profile 的输出更明确，不再打印空的 profile 字段

- **Workflow skill 边界**
  - 新增项目级 `grill-me` / `answer-me` / `ask-me` 可选协作者资产
  - `session-distill` 主链保持 `packet-memory-export -> memory-drafts review` 作为默认 draft gate
  - `mem-distill` 保持既有 memory / observations 整理入口，不进入 raw session promotion 主链

- **Temporal Bias benchmark gate**
  - LongMemEval 工具新增 `--temporal-bias` 与 `--compare-temporal-bias`
  - 新增 `benchmark` optional extra，声明 LongMemEval 工具所需的 `PyStemmer`
  - benchmark 临时 observations 表现在保留 timestamp，真实 `HybridSearchLayer` 路径可以评测 recency tie-break
  - 对照输出会记录 baseline、temporal-bias、per-type delta 和是否可进入 dogfood 的 gate 判断
  - 性能 benchmark 新增 `daily-wake-temporal-safety` 报告型 gate，用固定夹具检查旧但关键的 memory 是否会被最近普通 memory 挤出
  - wake-up memory 选择新增重要性保护，保留最近条目的同时为高置信、已使用或标记 critical / expected-wake 的旧 memory 预留保护名额

### Fixed

- **真实 Claude 项目体验修复**
  - `ingest claude-code` 现在会读取 session 里的真实 `cwd` 来识别项目 profile，支持从 Unity `Assets/` 目录归一到工程根
  - Unity profile 新增 `unity` / `csharp` 识别与 `ProjectSettings/ProjectVersion.txt`、`Packages/manifest.json` 等 key files
  - Claude observation 摘要保留 session 开头和结尾，避免大 session 的最近结论完全搜不到
  - observation FTS 索引会为中英混排文本补 token 边界，`创建ScriptableObject配置` 可被 `ScriptableObject` 命中
  - search 结果 preview 现在优先展示命中上下文，而不是固定显示 transcript 开头
  - `distill` 无稳定模式可提升时返回成功扫描结果，不再把“0 条可提升记忆”当作命令失败
  - distill 的 bug heuristic 不再把普通 `API Error` / `exception` / `failed with` 工具噪声提升为长期 memory

- **`purge` 回归修复**
  - 修复 `--before` 与持久化 UTC 时间戳比较时的 naive/aware datetime 崩溃
  - 修复 `observations` / `memory_entries` 缺失 `compacted` 列导致 soft-delete 失败
  - purge 后的数据现在默认不会再出现在 `wake`、`search`、`timeline` 和 structured memory 列表中

- **HybridSearchLayer 真正接线**
  - 修复 hybrid search 只存在于底层实现、但 CLI/MCP 仍走纯 FTS 的问题
  - verbatim / structured store 现在都会通过统一的 `mode=auto|fts|hybrid` 路径执行查询

- **MCP parity 修复**
  - `search_memory` 现在支持 `mode`
  - CLI / MCP 共享同一套检索语义和 fallback 行为

- **REST API 自用稳定性**
  - 修复 API 请求路径里的 backend 初始化，不再在异步请求中调用 `asyncio.run()`
  - `/search` 在 `scope=project` 下现在会显式要求 `project_name`
  - `/search` 返回 `requested_mode` / `effective_mode` / `fallback_reason`
  - `/rules/{id}/reject` 的 reject reason 现在是可选的

## [1.2.0] — 2026-04-25

### Added

- **`wake-up` explainability**
  - 每块 section 标题追加来源注释：`## Project Profile  (source: profile, ~N chars)`
  - 空数据区块显示 `(source: {category}, empty)` 而非跳过，保持结构一致

- **Compact Guard（提示文字）**
  - `doctor` 和 `wake-up` 在 L3/L4+ 时打印 Compact suggestion
  - 建议运行 `harness-mem ds --category bug` 或 `harness-mem ds --category decision`

- **`profile --edit`（merge 策略）**
  - 交互式编辑 profile 字段：`description`、`stacks`、`key_files`、`conventions`
  - 新值覆盖对应字段，其他字段保留
  - `!clear` 可重置字段为空；回车保持原值

### Changed

- `profile --edit` 时跳过未修改字段，merge 保存而非全量覆盖

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

### Fixed

- **`distill` 重复运行不再误报新增条目**
  - 修复 `distill_session()` 在所有 entry 都被去重时错误返回原 entries 列表而非空列表的问题
  - 重复 distill 现在正确返回空列表，CLI 不再打印 "Extracted N" 误导用户

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
