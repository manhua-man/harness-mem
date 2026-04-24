# harness-mem v1.1.3

Local-first, pluggable AI memory runtime for Claude Code and Codex.

**V1 闭环**: ingest → distill → structured memory → wake-up context → search/timeline → candidate rules → task resume.

Release notes: [v1.0.1](./docs/v1.0.1-release-notes.md)
Changelog: [CHANGELOG.md](./CHANGELOG.md)

---

## 快速开始

### 1. 安装

```bash
cd harness-mem
pip install -e .
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
harness-mem ingest codex -n 10
```

### 4. 生成唤醒上下文

```bash
harness-mem wake
```

### 5. 搜索记忆

```bash
harness-mem search "authentication"
harness-mem tl 20
harness-mem show <observation-id>
```

### 6. 规则学习循环

```bash
# 交互式输入
harness-mem correct

# 或者半交互式
harness-mem correct <id> \
  -r "Always validate JWT expiry before API calls" \
  -t "Before any authenticated API call"

# 确认候选规则
harness-mem confirm <candidate-id>

# 列出规则
harness-mem rules
```

### 7. 任务交接

```bash
# 交互式输入
harness-mem handoff

# 或者短参数模式
harness-mem handoff -t <id> -s "Fix auth bug" \
  -n "Check JWT validation logic" \
  -b "Waiting for token samples"
```

### 8. MCP Server (Claude Code 中使用)

```bash
# 安装 MCP server
claude mcp add harness-mem -- python -m harness_mem.mcp.server

# Claude Code 中可用工具
# - search_memory, timeline, get_observations
# - get_task_handoffs, get_confirmed_rules, get_project_profile
# - create_rule_candidate, confirm_rule
```

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
  ~/.harness-mem/data/
```

---

## 路线定位

V1 的定位是先建立一个本地优先、可解释、可落盘的 memory baseline：JSON blobs + SQLite FTS5 + structured memory，优先跑通 ingest、wake-up、search、learning loop、task resume 这条主链路。

V2 的目标不是把 harness-mem 描述成“已经在检索指标上超过 MemPalace”，而是把它扩展成一个更完整的 agent memory runtime：在保留 local-first 底座的前提下，增加 hybrid retrieval（BM25/FTS + vector + graph）、更强的 reranking、可写结构化记忆、纠正学习闭环，以及跨客户端的任务续接能力。

换句话说，V2 要追求的是**产品能力面比 MemPalace 更完整**；至于检索指标是否超过 MemPalace，应以同 benchmark、同设置下的实测结果为准，而不是提前宣称。

---

## CLI 命令

| 命令 | 说明 |
|------|------|
| `harness-mem init` | 初始化数据目录 |
| `harness-mem quickstart` | 一步完成初始化、活动项目设置、最近 session 发现与接入引导 |
| `harness-mem doctor` | 检查本地状态、展示最近 session，并给出最佳下一步建议 |
| `harness-mem use` | 设置当前活动项目 |
| `harness-mem ingest [claude-code\|codex]` | 接入 Claude Code 或 Codex sessions |
| `harness-mem wake-up` | 生成项目唤醒上下文 |
| `harness-mem search` | 搜索记忆 |
| `harness-mem timeline` | 时间线视图 |
| `harness-mem show` | 查看单条 observation |
| `harness-mem status` | 查看状态 |
| `harness-mem profile` | 查看项目 profile |
| `harness-mem correct` | 纠正 → 生成候选规则 |
| `harness-mem confirm-rule` | 确认候选规则 |
| `harness-mem reject-rule` | 拒绝候选规则 |
| `harness-mem list-candidates` | 列出候选规则 |
| `harness-mem confirmed-rules` | 列出已确认规则 |
| `harness-mem handoff` | 创建/更新任务交接 |

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
