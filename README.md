# harness-mem

Local-first, pluggable AI memory runtime for Claude Code and Codex.

**V1 闭环**: ingest → distill → structured memory → wake-up context → search/timeline → candidate rules → task resume。

当前主线已经补上：
- `purge` 软删除闭环
- 默认增量 ingest + `--full-rescan`
- `search --mode auto|fts|hybrid`
- CLI / MCP 一致的 search mode 与 learning-loop 语义

Release notes: [v1.0.1](./docs/v1.0.1-release-notes.md)
Changelog: [CHANGELOG.md](./CHANGELOG.md)
Repo map: [docs/repo-layout.md](./docs/repo-layout.md)

---

## 仓库地图

如果你觉得根目录有点杂，先按这张最小地图理解：

- `harness_mem/`: 主产品源码
- `tests/`: 自动化测试
- `docs/`: 文档和设计说明
- `benchmarks/`: benchmark 结果与评测相关内容
- `.claude/` / `.codex/` / `.cursor/`: 多 Agent 协作配置
- `openspec/`: 变更提案和 spec 资产
- `session-distill/` / `mem-distill/`: 配套 distill/workflow 技能资产

更详细的目录说明见 [docs/repo-layout.md](./docs/repo-layout.md)。

如果根目录里又冒出 `.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.gstack/`、`.coverage` 或 `tmp-*`，可以把它们当成本地运行产物，不算项目主结构。

---

## 快速开始

### 1. 安装

```bash
cd harness-mem
pip install -e .
# 如果你想真正启用 hybrid vector search，而不是只使用自动 fallback：
pip install -e ".[hybrid]"
harness-mem quickstart
```

### 2. 自检环境

```bash
harness-mem doctor
```

`quickstart` 和 `doctor` 会自动发现最近的 Claude Code / Codex sessions，并根据当前阶段直接建议下一步更适合跑 `ingest`、`ds` 还是 `wake`。

### 3. 接入 session

```bash
harness-mem use <project-name>
harness-mem ingest claude-code -n 10
harness-mem ingest claude-code --full-rescan   # 显式忽略 ingest cursor
harness-mem ingest codex -n 10
```

### 4. 生成唤醒上下文

```bash
harness-mem wake
```

### 5. 搜索记忆

```bash
harness-mem search "authentication" --mode auto
harness-mem search "authentication" --mode hybrid
harness-mem tl 20
harness-mem show -o <observation-id>
```

`auto` 会优先尝试 hybrid search；embedding 不可用时自动回退到 FTS，并把实际模式显示在结果头部。

### 6. 清理旧记忆

```bash
harness-mem purge -p my-project --before 2026-01-01 --category all --dry-run
harness-mem purge -p my-project --before 2026-01-01 --category observations
```

`purge` 使用 soft-delete / `compacted` 标记。被 purge 的 observations 和 memory entries 默认不会再出现在 `wake`、`search`、`timeline` 和常规列表结果里。对 `structured` 或 `all`，现在会要求明确项目上下文，不再静默跳过非活动项目的数据。

### 7. 编辑 Profile

```bash
harness-mem profile --edit
# 交互式编辑 description、stacks、key_files、conventions
# 回车保持原值，!clear 重置字段
```

### 8. 规则学习循环

```bash
# 交互式输入
harness-mem correct

# 或者半交互式
harness-mem correct <id> \
  -r "Always validate JWT expiry before API calls" \
  -t "Before any authenticated API call"

# 确认候选规则
harness-mem confirm <candidate-id>

# 拒绝候选规则
harness-mem reject <candidate-id>

# 列出规则
harness-mem rules
```

### 9. 任务交接

```bash
# 交互式输入
harness-mem handoff

# 或者短参数模式
harness-mem handoff -t <id> -s "Fix auth bug" \
  -n "Check JWT validation logic" \
  -b "Waiting for token samples"
```

### 10. MCP Server (Claude Code 中使用)

```bash
# 安装 MCP server
claude mcp add harness-mem -- python -m harness_mem.mcp.server

# Claude Code 中可用工具
# - search_memory, timeline, get_observations
# - get_task_handoffs, get_confirmed_rules, get_project_profile
# - create_rule_candidate, confirm_rule, reject_rule, suggest_rule
#
# search_memory 支持:
# - scope=project|all
# - mode=auto|fts|hybrid
```

### 11. REST API

```bash
harness-mem api
```

内部自用时，`GET /search` 现在要求：
- `scope=project` 时必须提供 `project_name`
- 支持 `mode=auto|fts|hybrid`
- 返回 `requested_mode` / `effective_mode` / `fallback_reason`

---

## 架构

```
Adapter Layer
  ClaudeCodeAdapter  →  ~/.claude/projects/{project}/*.jsonl
  CodexAdapter      →  Codex search-mode sessions

Memory Core (dual-layer)
  Verbatim Layer    →  Observation (原始 session transcript)
  Structured Layer  →  MemoryEntry, TaskHandoff, RuleCandidate, ConfirmedRule

Storage
  JSON blobs + SQLite FTS5 index
  Optional local hybrid retrieval (FTS + vector fallback-safe)
  ~/.harness-mem/data/
```

---

## 路线定位

V1.x 的定位是把本地优先、可解释、可落盘的 memory baseline 做扎实：JSON blobs + SQLite FTS5 + structured memory + 轻量 hybrid retrieval，优先跑通 ingest、wake-up、search、learning loop、task resume、purge 这条主链路。

V2 的重点不再是“补一个基础 hybrid search”，而是继续往 invisible memory 和更完整的 agent runtime 演进：更强的 reranking、图结构记忆、跨客户端任务续接、更少显式命令、更高自动化。

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `harness-mem init` | 初始化数据目录 |
| `harness-mem quickstart` | 一步完成初始化、活动项目设置、最近 session 发现与接入引导 |
| `harness-mem doctor` | 检查本地状态、展示最近 session，并给出最佳下一步建议 |
| `harness-mem use` | 设置当前活动项目 |
| `harness-mem ingest [claude-code\|codex]` | 默认增量接入 sessions，支持 `--full-rescan` |
| `harness-mem distill` | 从 session 提取 structured memory |
| `harness-mem wake-up` | 生成项目唤醒上下文 |
| `harness-mem search` | 搜索记忆，支持 `--mode auto\|fts\|hybrid` |
| `harness-mem timeline` | 时间线视图 |
| `harness-mem show` | 查看单条 observation，支持 `-o/--observation-id` |
| `harness-mem status` | 查看状态 |
| `harness-mem profile` | 查看项目 profile |
| `harness-mem purge` | 软删除旧 observations / structured memory |
| `harness-mem correct` | 纠正 → 生成候选规则 |
| `harness-mem confirm-rule` | 确认候选规则 |
| `harness-mem reject-rule` | 拒绝候选规则 |
| `harness-mem list-candidates` | 列出候选规则 |
| `harness-mem confirmed-rules` | 列出已确认规则 |
| `harness-mem handoff` | 创建/更新任务交接 |
| `harness-mem api` | 启动 REST API server |

### 常用短别名

| 简写 | 完整命令 |
|------|----------|
| `wake` | `wake-up` |
| `tl` | `timeline` |
| `ds` | `distill` |
| `confirm` | `confirm-rule` |
| `reject` | `reject-rule` |
| `rules` | `confirmed-rules` |
| `candidates` | `list-candidates` |
| `st` | `status` |
| `qs` | `quickstart` |

---

## CLI UX Notes

- `quickstart` 会先看最近的 session，再决定帮你走 ingest 还是提示你下一步
- `doctor` 会根据当前项目里有没有 observations / structured memory，直接建议 `ingest`、`ds` 或 `wake`
- `doctor` / `wake` 在 budget 达到高水位时，会直接给出带项目作用域的 `purge --dry-run` 建议
- `search` 会展示请求模式和实际生效模式；embedding 不可用时会明确标注 fallback 到 FTS
- 关键 CLI 流程现在会把 command / next-step 事件写入本地 `events.log`，方便内部 dogfooding
- 这套设计准则收在 [docs/cli-design-expert.md](./docs/cli-design-expert.md)

---

## 数据目录

```
~/.harness-mem/data/
  verbatim/                     JSON blobs (Observation)
  structured/
    memory_entries/             JSON blobs
    task_handoffs/              JSON blobs
    rule_candidates/            JSON blobs
    confirmed_rules/            JSON blobs
  profiles/                     Project profiles
  events.log                    本地事件日志
  active_project.txt            当前活动项目
  verbatim_index.sqlite         SQLite FTS5 index
  structured_index.sqlite       SQLite FTS5 index
```

---

## V1 Launch Gate — 7/7 implemented and smoke-tested

- [x] Ingest — session 数据流入本地 memory system
- [x] Structured Memory — MemoryEntry, TaskHandoff, RuleCandidate, ConfirmedRule 落盘
- [x] Wake-up — 新 session 启动时带出 lightweight context
- [x] Progressive Retrieval — search, timeline, get_observations
- [x] Learning Loop — correct → candidate rule → confirm → recall
- [x] Task Resume — 恢复之前的工作状态
- [x] Local Mode — 不依赖 cloud，核心环完全本地运行
