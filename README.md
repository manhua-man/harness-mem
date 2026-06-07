# harness-mem

Local-first, pluggable **AI memory runtime** for Claude Code, Codex, and Gemini CLI.

**核心理念**：让 AI 拥有跨 Session、可审计的长期记忆。AI 是记忆的"操作员"和一线审核员，人只做最终复核与纠错。

> **v2.0**：distill 路径只接受 LLM agent。低质量正则启发式已在 v2.0 移除——它产出的 0.7 confidence 候选既无法触发 auto-review 自动确认、也几乎抓不到自然 prose 里的关系事实，违反"AI memory runtime"承诺。任意 LLM agent（Claude Code skill、Codex agent、Cursor、Gemini、自定义）都可以在背后调用同一套 runtime 写候选；harness-mem 不绑特定客户端。

候选写入只发生在显式 agent 流程里：例如 `/hm:distill`、repo-local skill，或用户明确要求“记下这条规则”。当前产品仍没有默认后台 daemon、默认自动 IDE hook 路径或 turn-end 自检来自动产生“日常随手记”；v2.4 已提供 opt-in host hook / scheduler trigger，但 `triggers.*` 默认仍是 `off`，而且它们不会把候选写入变成 autonomous learning。

Agent 协作真值见 [AGENTS.md](./AGENTS.md)。
当前发版状态与已落地边界以 [docs/roadmap-status.md](./docs/roadmap-status.md) 和
[CHANGELOG.md](./CHANGELOG.md) 为准；各版本 roadmap 更多是切片设计与历史决策链，不应单独当作当前实现真值。

---

## 用户可见入口

用户不需要理解 MCP 工具名。正常体验应该是显性的 IDE 命令、Slash、Skill，或一句自然语言指令：

```text
/hm:distill
/hm:wake
/hm:search "auth logic"
用 harness-mem 整理最近 10 个 session，自动审核低风险候选，最后只给我复核摘要。
```

MCP 是 Agent 背后的传输层，不是用户日常心智模型。CLI 是安装、自检、排障和清理控制台，不承载 wake/search/timeline/candidate review 这类日常动作。

---

## 核心工作流 (The Cycle)

| 阶段 | 用户看到 | Agent 实际做什么 |
| :--- | :--- | :--- |
| **1. 唤醒 (Wake)** | `/hm:wake` 或新任务自动注入 | 读取 profile、已确认规则、最近 handoff 和必要 observations；只消费 accepted/current truth |
| **2. 提炼 (Distill)** | `/hm:distill` 或“整理最近 session” | 项目范围 ingest -> evidence packet -> LLM 提炼 -> `suggest_*` 写候选 |
| **3. 自动审核 (Auto-review)** | 只看到最终摘要和少数高风险项 | Agent 确认低风险长期事实、拒绝噪声/重复/跨项目项，高风险留给人 |
| **4. 检索 (Search)** | `/hm:search` 或自然语言查询 | 先返回可解释摘要和 source IDs；需要时再展开原始 evidence |
| **5. 清理 (Cleanup)** | 明确的排障/维护动作 | `doctor` / `purge --dry-run` / rebuild index；不进入日常 happy path |

这条链路不会在普通编码 turn 结束时自动运行。是否触发提炼，取决于 slash 命令、Skill、用户指令，或客户端自己额外实现的 hook。

---

## Golden Path：用户怎么用

### 1. 安装

harness-mem 不发 PyPI；从 git 安装即可。三条路径按需选：

**A. Cursor / Codex / 通用 MCP 客户端**——直接从 git 安装包：

```bash
pip install git+https://github.com/manhua-man/harness-mem.git
```

需要本地 hybrid vector search 时加 extra：

```bash
pip install "harness-mem[hybrid] @ git+https://github.com/manhua-man/harness-mem.git"
```

**B. Claude Code 用户**——通过 repo-local plugin 一键装好包 + slash 命令 + （可选）MCP 注册：

```powershell
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
.\plugins\harness-mem\scripts\install.ps1 -WithHybrid -RegisterClaude
```

脚本会做：editable install harness-mem、把 `plugins/harness-mem/commands/hm/*.md` 复制到
`~/.claude/commands/hm/` 让 `/hm:distill` `/hm:wake` `/hm:search` `/hm:review` `/hm:status`
全局可用、`claude mcp add` 把 MCP server 注册到 Claude Code、最后跑 `harness-mem doctor` 自检。

**C. 改 harness-mem 自身的开发者**——editable install：

```bash
git clone https://github.com/manhua-man/harness-mem.git
cd harness-mem
pip install -e ".[dev,hybrid]"
```

任意路径装完后，第一次或本机状态异常时跑：

```bash
harness-mem quickstart
harness-mem doctor
```

### 2. 接到你的 IDE / Agent

推荐通过 repo-local plugin / MCP Router / 客户端 MCP 配置接入。这个步骤只在安装阶段出现；使用阶段不要让用户手动调用 MCP 工具。

Claude Code 用户安装 slash 后，直接使用：

```text
/hm:distill
/hm:wake
/hm:search "authentication"
```

Cursor、Codex、Gemini 或其它 AI IDE 没有 `/hm:*` 时，直接对 Agent 说：

```text
用 harness-mem 整理当前项目最近 10 个 session。
用 harness-mem 的记忆继续这个任务。
搜索项目记忆里 auth 相关的历史决定。
```

### 3. 日常闭环

```text
/hm:distill
```

`/hm:distill` 是默认闭环：Agent 自己 ingest、提炼、写候选、自动审核低风险项，最后只给你看摘要和需要人判断的少数残留。

新任务开始时：

```text
/hm:wake
```

`wake` 只注入已确认的记忆。pending 候选、procedural Skill 候选和历史失效 truth 不会默认混进上下文。

查历史时：

```text
/hm:search "authentication"
```

需要找原始证据、错误码、路径或日志片段时，让 Agent 使用 raw evidence search；它只做 observation 证据定位，不替代语义检索。

### 4. 可复用流程

v1.8.0 起，重复工作流可以沉淀为 confirmed Skill：

```text
用 harness-mem 查 release hygiene 相关的可复用流程。
```

Skill 不会自动自学习，也不会进入默认 `wake`。新 Skill 必须先成为 `ProceduralCandidate`，再经 `confirm_skill` 显式确认。

### 5. 只有排障或 cleanup 时才碰 CLI

AI IDE 用户不需要学习 CLI 命令清单。候选复核、确认、拒绝、搜索、wake 都应由 Agent 在背后完成。CLI 只作为安装、自检、脚本化和显式 cleanup 的本地控制面；需要时再查 `harness-mem --help`。

---

## 产品原则 (Principles)

`harness-mem` 的目标不是做一个“记忆搜索工具”，而是做一个 **local-first、可审计、可控的 AI memory runtime**。参考项目给出的取舍是：

- **User command first, MCP behind the curtain**: 用户入口是 `/hm:*`、Skill 或自然语言；MCP 只是 Agent 调 runtime 的协议层。
- **Raw evidence first**: 借鉴 MemPalace 的 raw/verbatim 路线，原始 observations 和 provenance 必须保留；摘要不能替代证据。
- **Progressive disclosure**: 借鉴 `claude-mem` 的 search -> timeline -> get details 思路，默认先给索引、摘要和来源，需要时再展开全文。
- **Candidate before truth**: 任何 AI 提炼、纠错、supersede、Skill 学习都先进候选层；accepted/current truth 才能进 wake。
- **Agent handles routine review**: `/hm:distill` 应自动确认低风险长期事实、拒绝噪声，只把高风险或证据不足项交给人。
- **Main task must not be held hostage**: 记忆系统失败要可见、可诊断、可重试，但不能阻断用户当前开发流。
- **CLI is maintenance, not product UX**: CLI 只做安装、自检、doctor、purge、maintenance、导入文件等本地控制台能力。
- **No default daemon / LSP / extension lock-in**: 当前路线不做常驻后台主路径，也不把产品绑死在某个编辑器扩展上；显式命令和 Skill 先把闭环跑稳。

---

## 仓库地图

如果你觉得根目录有点杂，先按这张最小地图理解：

- `harness_mem/`: 主产品源码
- `tests/`: 自动化测试
- `docs/`: 文档和设计说明
- `benchmarks/`: benchmark 结果与评测相关内容
- `.claude/` / `.codex/` / `.cursor/`: 可选的多 Agent 协作配置（非安装必需）
- `openspec/specs/`: 当前主 spec 真值
- `openspec/changes/`: 仍在进行中的 active changes
- `openspec/changes/archive/`: 已完成 change 的归档记录
- `tools/`: 可选 skill 与 session 整理入口（默认主链仍是 `/hm:distill`）

文档入口见 [docs/README.md](./docs/README.md)。发版审计与跨客户端测试材料在维护者文档区，不面向终端用户。

**默认主链**（用户只需记住这一条）：

```text
/hm:distill  ->  ingest + LLM 提炼 + 写候选 -> auto_review_candidates(apply=true) -> 摘要给你复核
/hm:wake     →  只注入已确认记忆
/hm:search   →  先摘要与来源，需要时再展开证据
```

Session 来源由 runtime 自动识别，无需手动指定客户端类型。高级维护（标记已蒸馏 session、清理 KB、`/hm:prd-sync` 等）见 `plugins/harness-mem/commands/hm/` 与 [docs/roadmap-v28.md](./docs/roadmap-v28.md)。

本地测试缓存目录（`.pytest_cache/`、`.mypy_cache/` 等）可忽略，不属于产品结构。

---

## 开发者与维护入口

日常用户先走 Golden Path。本节只保留安装、自检、排障、脚本化和显式 cleanup。

```bash
harness-mem quickstart
harness-mem doctor
python -m harness_mem.cli --help
python -m harness_mem.tools.longmemeval --help
harness-mem maintenance rebuild-vector-index --project <project-name>
harness-mem maintenance rebuild-verbatim-index --project <project-name>
harness-mem purge -p my-project --before 2026-01-01 --category all --dry-run
```

`quickstart` / `doctor` 可以帮助确认本机安装、数据目录、项目上下文、索引健康和 cleanup 建议。它们不替代 `/hm:distill`、`/hm:wake`、`/hm:search`。

维护者测试不要默认全量跑。日常先跑 touched tests；不确定影响面时用：

```powershell
.\scripts\test-fast.ps1
```

发版、OpenSpec 收口、大重构或广泛状态判断再跑 full gate：

```powershell
.\scripts\test-full.ps1
```

完整分层规则见 [docs/testing.md](./docs/testing.md)。

面向命令/Skill 作者的 MCP server 启动命令是：

```bash
python -m harness_mem.mcp.server
```

这条命令应由 MCP Router、客户端配置或安装脚本持有；使用过程中不要让用户手动调用 MCP tool names。

---

## 架构

```text
用户可见入口
  /hm:distill / /hm:wake / /hm:search
  自然语言命令
  repo-local Skill / command instructions

Agent 编排层
  plugin commands / skills
  session-distill, mem-distill, grill-me, answer-me
  自动审核低风险候选，只把高风险项交给人

传输层
  MCP server (隐藏在 Agent/IDE 配置后)
  CLI maintenance console (quickstart, doctor, purge, maintenance, import, config, integration)

命令与运行时编排
  commands/ (wake, ingest, search, candidates, handoff...)
  mcp/server.py 委托 LocalMemoryBackend 和 command helpers

领域模型
  Observation, MemoryEntry, RelationFact, RuleCandidate
  SupersedeCandidate, ProceduralCandidate, ConfirmedRule, Skill
  MergeSuggestionCandidate, StaleTruthSuggestionCandidate

检索与渲染
  search/ (SQLite FTS5 + optional vector hybrid)
  read_api.py shared payload serialization
  progressive disclosure: search -> timeline -> get_observations

存储
  LocalVerbatimStore + LocalStructuredStore
  JSON blobs + SQLite FTS5 + optional vector cache
  ~/.harness-mem/data/

适配器
  各 AI IDE / CLI 的 session 来源（自动识别）
```

REST API 不属于当前产品主路径，也不作为默认接入层维护。

---

## 路线定位

V2 的重点不是让用户学习更多底层工具，而是把记忆能力藏进 Agent 工作流：显性入口少、默认闭环强、失败可诊断、证据可追溯。

参考项目给出的边界也很明确：`claude-mem` 的 hook/worker 证明了 progressive disclosure 和 graceful degradation 的价值，但它的 Claude 专属 hook daemon 不适合直接作为本项目主线；MemPalace 的 raw/verbatim 和 memory stack 证明了“先保留证据，再按需压缩/索引”的方向；`ai-harness` 的 source cache 说明生成物和人工权威源必须分层。harness-mem 当前主线是跨 Agent 的本地 memory runtime，而不是 VS Code extension、always-on daemon、REST service 或 CLI-first 工具。

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
    merge_suggestion_candidates/ JSON blobs
    stale_truth_suggestion_candidates/ JSON blobs
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
