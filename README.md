# harness-mem

Local-first, pluggable **AI memory runtime** for Claude Code, Codex, and Gemini CLI.

**核心理念**：让 AI 拥有跨 Session、可审计的长期记忆。AI 是记忆的“操作员”和一线审核员，人只做最终复核与纠错。

Agent 协作真值见 [AGENTS.md](./AGENTS.md)。

---

## 核心工作流 (The Cycle)

| 阶段 | 动作 | 驱动者 | 实现方式 |
| :--- | :--- | :--- | :--- |
| **1. 摄取 (Ingest)** | 抓取原始会话日志 | AI | MCP `ingest_sessions` / Slash `/hm:distill` |
| **2. 提炼 (Distill)** | **AI 读 Session 提炼精华知识** | **AI** | **Skill: `session-distill`** |
| **3. 自动审核 (Auto-review)** | AI 自动确认低风险记忆、拒绝噪声，并把高风险项留给用户复核 | **AI + 人复核** | Slash `/hm:distill` + MCP `confirm_*` / `reject_*` |
| **4. 消费 (Use)** | AI 在新任务中自动加载记忆 | AI | **MCP: `search_memory` / `wake`** |

---

## Golden Path：用户怎么用

### 1. 安装

```bash
pip install harness-mem
harness-mem quickstart
```

需要启用本地 hybrid vector search 时安装 extra：

```bash
pip install "harness-mem[hybrid]"
```

如果你是在这个仓库里开发而不是只使用成品包，再改用：

```bash
pip install -e ".[dev,hybrid]"
```

### 2. 提炼历史：`/hm:distill`

在支持 harness-mem slash / MCP 的 agent 里运行：

```text
/hm:distill <project> 10
```

这一步会完成 session 摄取、AI 提炼、低风险候选自动审核，并把确实需要人看的内容留在最终摘要里。用户不需要逐条扫原始 session，也不需要手动分类候选。

### 3. 开新任务：`/hm:wake`

```text
/hm:wake
```

`wake` 只注入已确认的记忆。pending 候选、procedural Skill 候选和历史失效 truth 不会默认混进上下文。

### 4. 查记忆：`/hm:search`

```text
/hm:search "authentication"
```

Agent 内部也可以直接调用 MCP：

```text
search_memory(project_name="<project>", query="authentication", mode="auto")
```

需要找原始证据、错误码、路径或日志片段时，让 agent 用 `search_raw` / `harness-mem search-raw`；它只做 observation 证据定位，不替代语义检索。

### 5. 查可复用流程：`search_skills`

v1.8.0 起，重复工作流可以沉淀为 confirmed Skill。日常入口是 MCP：

```text
search_skills(project_name="<project>", query="release hygiene")
record_skill_result(skill_id="<id>", success=true)
```

本地兜底 CLI：

```bash
harness-mem search-skills -p <project> "release hygiene"
harness-mem record-skill-result <skill-id> --success
```

Skill 不会自动自学习，也不会进入默认 `wake`。新 Skill 必须先成为 `ProceduralCandidate`，再经 `confirm_skill` / `harness-mem confirm-skill` 显式确认。

### 6. 只有需要复核或排障时才碰 CLI

CLI 只作为安装、排障和显式 cleanup 的本地控制面。下面命令不是用户日常路径，只是本地兜底：

```bash
harness-mem candidates           # 查看 AI 提炼的候选条目
harness-mem confirm <id>         # 确认记忆：从此该条目可被 wake/search 消费
harness-mem reject <id>          # 拒绝噪声候选
harness-mem confirm-skill <id>   # 确认 procedural Skill 候选
harness-mem search-raw --regex "HM-201|timeout"
```

---

## 产品原则 (Principles)

`harness-mem` 的目标不是做一个“记忆搜索工具”，而是做一个 **local-first、可审计、可控的 AI memory runtime**。

- **Runtime over interface**: 核心价值是让多个 AI client 共享同一套长期记忆，不是某一个前端形态本身。
- **Local-first and auditable**: 记忆默认留在本地；用户可以搜索、追溯、纠正和清理，而不是接受黑箱记忆。
- **CLI as bootstrap**: CLI 负责安装、试用、调试和显式控制，不是用户日常主路径；日常主路径应是 slash/MCP/Skill。
- **MCP-first**: 长期主路径是把能力接到 agent runtime 里，让 Claude Code、Codex 等 client 默认能读写同一层记忆。
- **Invisible by default, visible when needed**: 日常体验应尽量无感，但一旦用户想问“记住了什么、为什么被注入、怎么删掉”，系统必须可见、可解释、可退出。
- **No extension/daemon or LSP roadmap**: 当前路线不规划 VS Code extension、后台 daemon 或 LSP server，先把 MCP 自动化和本地 runtime 主链路做透。

---

## 仓库地图

如果你觉得根目录有点杂，先按这张最小地图理解：

- `harness_mem/`: 主产品源码
- `tests/`: 自动化测试
- `docs/`: 文档和设计说明
- `benchmarks/`: benchmark 结果与评测相关内容
- `.claude/` / `.codex/` / `.cursor/`: 多 Agent 协作配置
- `openspec/`: 变更提案和 spec 资产
- `tools/session-distill/`: raw session -> packet 主入口
- `tools/mem-distill/`: 既有 memory / observations 整理入口
- `tools/grill-me/` / `tools/answer-me/` / `tools/ask-me/`: review 阶段可选协作者，不是默认主链依赖

文档入口和实际文件列表见 [docs/README.md](./docs/README.md)。

### Workflow Skill Boundary

默认主链是：

```text
session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only
```

`grill-me`、`answer-me`、`ask-me` 和 `mem-distill` 只在已安装且场景匹配时接入 review 或整理阶段。任何一个外置协作者不可用时，主链仍应继续运行。

如果根目录里又冒出 `.pytest_cache/`、`.mypy_cache/`、`.ruff_cache/`、`.gstack/`、`.coverage` 或 `tmp-*`，可以把它们当成本地运行产物，不算项目主结构。

---

## 开发者与 CLI 参考

日常用户先走上面的 Golden Path。本节只保留开发者、本地排障和脚本化入口。

### 环境自检

```bash
harness-mem doctor
```

`quickstart` 和 `doctor` 会自动发现最近的 Claude Code / Codex sessions，并根据当前阶段直接建议下一步更适合走 `/hm:distill`、`ingest` 兜底还是 `wake`。默认摄取路径会按当前 agent 环境和当前项目路径收窄；跨项目或全局历史导入必须显式写 `--scope all`。

开发环境里也可以不依赖 console script，直接从源码树运行：

```bash
python -m harness_mem.cli --help
python -m harness_mem.tools.longmemeval --help
```

`harness-mem` 这个裸命令来自 editable install 生成的 console script。Windows 上如果 `Scripts` 目录不在 `PATH`，就用 `python -m harness_mem.cli ...`，或把对应 Python 的 `Scripts` 目录加入 `PATH`。

### Session 接入兜底

用户日常入口是 `/hm:distill <project> 10`，由 Agent 通过 MCP `ingest_sessions` 自动完成当前环境和当前项目路径匹配。下面命令只作为开发者排障或自动化脚本参考。

```bash
harness-mem use <project-name>
harness-mem ingest -n 10                  # 默认 auto：当前 agent 环境 + 当前项目路径
harness-mem ingest claude-code -n 10       # 显式 Claude Code 项目会话
harness-mem ingest claude-code --full-rescan   # 显式忽略 ingest cursor
harness-mem ingest codex-archive -n 10 --project-root .
harness-mem ingest codex-archive -n 10 --scope all   # 显式全局回扫
```

### 运行时检查

```bash
harness-mem wake
harness-mem search "authentication" --mode auto
harness-mem search "authentication" --mode hybrid
harness-mem search-raw --regex "HM-201|timeout"
harness-mem search-skills -p <project-name> "release hygiene"
harness-mem tl 20
harness-mem show -o <observation-id>
```

`auto` 会优先尝试 hybrid search；embedding 不可用时自动回退到 FTS，并把实际模式显示在结果头部。

### 维护与 benchmark

```bash
harness-mem maintenance rebuild-vector-index --project <project-name>
harness-mem maintenance rebuild-verbatim-index --project <project-name>
python -m harness_mem.tools.embedding_shootout
harness-mem purge -p my-project --before 2026-01-01 --category all --dry-run
harness-mem purge -p my-project --before 2026-01-01 --category observations
```

`doctor` 会提示是否需要重建向量索引或 exact evidence 索引；`rebuild-vector-index` 和 `rebuild-verbatim-index` 会按项目重建本地索引。`purge` 使用 soft-delete / `compacted` 标记。被 purge 的 observations 和 memory entries 默认不会再出现在 `wake`、`search`、`timeline` 和常规列表结果里。

### 编辑 Profile

```bash
harness-mem profile --edit
# 交互式编辑 description、stacks、key_files、conventions
# 回车保持原值，!clear 重置字段
```

### 规则学习循环

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

### 任务交接

```bash
# 交互式输入
harness-mem handoff

# 或者短参数模式
harness-mem handoff -t <id> -s "Fix auth bug" \
  -n "Check JWT validation logic" \
  -b "Waiting for token samples"
```

### MCP Server (Claude Code 中使用)

```bash
# 安装 MCP server
claude mcp add -s user harness_mem "python -m harness_mem.mcp.server"

# Claude Code 中可用工具（工具名使用无短横线 alias，如 mcp__harness_mem__search_memory）
# - get_project_status, prepare_session_distill, list_candidates
# - search_memory, timeline, get_observations
# - get_task_handoffs, get_confirmed_rules, get_project_profile
# - suggest_memory_entry, suggest_rule, suggest_relation_fact, create_task_handoff
# - search_raw, search_skills, suggest_skill, confirm_skill, reject_skill, record_skill_result
#
# search_memory 支持:
# - scope=project|all
# - mode=auto|fts|hybrid
```

长期来看，MCP 是首选集成形态；CLI 继续保留为 bootstrap、调试入口和显式控制面板。目标不是让用户反复手动敲 `ingest` / `wake`，而是让记忆能力尽量自然地出现在 agent 工作流里。

### REST API

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
  Structured Layer  →  MemoryEntry, RelationFact, TaskHandoff
                      RuleCandidate, SupersedeCandidate, ProceduralCandidate
                      ConfirmedRule, Skill

Storage
  JSON blobs + SQLite FTS5 index
  Persistent vector index + verbatim exact evidence index
  Optional local hybrid retrieval (FTS + vector fallback-safe)
  ~/.harness-mem/data/
```

---

## 路线定位

V1.x 的定位是把本地优先、可解释、可落盘的 memory baseline 做扎实：JSON blobs + SQLite FTS5 + structured memory + 轻量 hybrid retrieval，优先跑通 ingest、wake-up、search、learning loop、task resume、purge 这条主链路。这个阶段里，CLI 是正确的 bootstrap：它负责把 happy path、显式控制和调试能力先做完整。

V2 的重点不再是“补一个基础 hybrid search”，而是继续往 invisible memory 和更完整的 agent runtime 演进：更强的 reranking、图结构记忆、跨客户端任务续接、更少显式命令、更高自动化。这里的“invisible”不是黑箱化，而是默认自动、必要时可见：用户平时不必频繁管理记忆，但始终可以追溯来源、审查内容、纠正错误和执行清理。

---

## 命令面

用户日常不需要学习完整 CLI。正常入口是 Slash/MCP：

| 入口 | 用途 |
|------|------|
| `/hm:status` | 看当前项目记忆健康度和下一步建议 |
| `/hm:distill <project> <n>` | 一键灌入、提炼、自动审核低风险候选，并给最终复核摘要 |
| `/hm:wake` | 开新任务时加载已确认记忆 |
| `/hm:search "query"` | 搜索本项目记忆 |

CLI 是开发者控制台，用于安装、诊断、脚本化和异常兜底。README 只保留最小参考，完整列表以 `harness-mem --help` 为准：

| 场景 | 命令 |
|------|------|
| 安装/诊断 | `harness-mem quickstart`、`harness-mem doctor`、`harness-mem status` |
| 当前项目 | `harness-mem use <project>`、`harness-mem profile` |
| 摄取兜底 | `harness-mem ingest -n 10`，跨项目历史必须显式 `--scope all` |
| 提炼兜底 | `harness-mem distill` / `harness-mem ds`，仅作启发式 fallback |
| 运行时检查 | `harness-mem wake`、`harness-mem search "query"`、`harness-mem timeline`、`harness-mem show -o <id>` |
| 候选修正 | `harness-mem candidates`、`harness-mem confirm <id>`、`harness-mem reject <id>` |
| 维护/服务 | `harness-mem purge --dry-run`、`harness-mem api`、`harness-mem maintenance ...` |

---

## CLI UX Notes

- `quickstart` 会先看最近的 session，再建议接入 Slash/MCP 主路径或给出本地兜底命令
- `doctor` 会根据当前项目里有没有 observations / structured memory，优先建议 `/hm:distill`、`/hm:wake` 或必要的本地排障命令
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
    relation_facts/             JSON blobs
    task_handoffs/              JSON blobs
    rule_candidates/            JSON blobs
    supersede_candidates/       JSON blobs
    procedural_candidates/      JSON blobs
    confirmed_rules/            JSON blobs
    skills/                     JSON blobs
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
