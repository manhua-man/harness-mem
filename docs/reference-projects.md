# 参考项目深读：记忆运行时、知识库与自进化

> 状态：持续维护的参考地图。
>
> 初次收录：2026-05-18。中文化与本地深读修订：2026-05-19。
>
> 本文记录对 `harness-mem` 设计有参考价值的外部项目。它不是路线图本身；当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。若需回看当时的历史路线设计，再参考 `roadmap-v15x.md`、`roadmap-v16x.md`、`roadmap-v17x.md` 与 `roadmap-vision-v16-v18.md`。

## 文档定位

我们之前已经在 [`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 里写过“当前生态坐标（参考与对标）”，但那一节偏 v1.6 到 v1.8 的远景定位。

本文的职责不同：它是参考项目的一手读书笔记，优先记录已经下载到 `F:\memory-lab\upstreams` 的项目。远程项目如果还没镜像，只作为待研究线索，不和本地深读项目混在同一个可信度层级。

## 本地 upstream 总览

`F:\memory-lab\upstreams` 是外部参考项目的本地书架。这些目录只用于对照、阅读和 benchmark，不是当前主产品源码。

| 本地路径 | 上游仓库 | 本文定位 |
|---|---|---|
| `F:\memory-lab\upstreams\ai-harness` | `https://github.com/killop/ai-harness.git` | 本地 MemPalace workspace。重点看“源文档同步到 knowledge cache，再 mine 成 palace”的知识库工作流。 |
| `F:\memory-lab\upstreams\claude-mem` | `https://github.com/thedotmack/claude-mem.git` | Claude Code 插件式记忆系统。重点看 hook 生命周期、progressive disclosure、File Read Gate、worker 队列与降级策略。 |
| `F:\memory-lab\upstreams\mempalace` | `https://github.com/MemPalace/mempalace.git` | 最接近的 local-first memory runtime。重点看 raw/verbatim 优先、palace/closet/drawer 结构、memory stack、SQLite temporal KG、AAAK 边界。 |

## 已下载项目深读

### 1. `ai-harness`

已读本地文件：

- `F:\memory-lab\upstreams\ai-harness\README.md`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\README.md`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\knowledges-cache\README.md`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\tools\sync-map.json`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\tools\Sync-MemoryCache.ps1`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\tools\Refresh-MemPalace.ps1`
- `F:\memory-lab\upstreams\ai-harness\harness-workspace\tools\Rebuild-MemPalace.ps1`
- `F:\memory-lab\upstreams\ai-harness\.codex\config.toml`

它不是一个普通竞品仓库，更像一个“MemPalace 知识库工作区样板”。核心数据流是：

```text
source docs
-> tools/Sync-MemoryCache.ps1
-> knowledges-cache/
-> tools/Refresh-MemPalace.ps1
-> .mempalace_local/palace
```

关键机制：

- `knowledges-cache/` 是共享知识源，按 wing 分成 `game_design`、`game_server`、`game_client`、`game_shared`。
- 每个 wing 用 `mempalace.yaml` 定义可挖掘输入。
- `manual/` 放人工长期维护知识，`generated/` 放同步脚本生成内容。
- `sync-map.json` 把上游源目录映射到 knowledge cache，例如 `DesignDoc -> game_design/generated/DesignDoc`、`docs/architecture -> game_shared/generated/docs-architecture`。
- `Refresh-MemPalace.ps1` 先同步 cache，再对每个带 `mempalace.yaml` 的 wing 执行 `python -m mempalace.cli --palace ... mine ...`。
- `.mempalace_local/palace` 是运行产物，不是共享源。

对 `harness-mem` 的启发：

- 如果做 `wiki bridge`，第一版不应该直接写入 runtime truth；更合理的是先有一个显式的 source cache / generated cache 分层。
- “人工维护内容”和“脚本生成内容”必须分目录，避免 AI 把生成物当成权威源。
- 后续如果引入文档知识库，可以参考这个工作流：

```text
repo docs / accepted memory
-> generated knowledge cache
-> wiki compiler 或 memory mine
-> 可检索知识输出
```

不能照搬：

- 不能把 `.mempalace_local/` 这类运行产物当成协作源。
- 不能把游戏项目的 wing 命名直接套到通用 memory runtime。
- 不能让 `sync-map.json` 成为隐藏真相；映射规则需要在 `doctor` 或文档索引里可见。

### 2. `claude-mem`

已读本地文件：

- `F:\memory-lab\upstreams\claude-mem\docs\architecture-overview.md`
- `F:\memory-lab\upstreams\claude-mem\docs\public\architecture\overview.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\public\architecture\search-architecture.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\public\context-engineering.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\public\progressive-disclosure.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\public\file-read-gate.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\public\hooks-architecture.mdx`
- `F:\memory-lab\upstreams\claude-mem\docs\production-guide.md`

它的核心不是单纯“有 SQLite + ChromaDB”，而是一个 hook 驱动的 Claude Code 外挂记忆系统：

```text
Claude Code hooks
-> CLI / hook command layer
-> Worker service
-> SQLite + FTS5 + ChromaDB
-> MCP/search skill/progressive disclosure
```

关键机制：

- **Hook lifecycle**：SessionStart 注入上下文，UserPromptSubmit 初始化 session，PostToolUse 捕捉工具使用，Stop 生成 summary，SessionEnd 做收尾。
- **Worker sidecar**：后台 Express worker 负责 observation 处理、search API、SSE/UI、SDK agent 调用。
- **CLAIM-CONFIRM queue**：pending -> processing -> confirm/delete；processing 超时后重置 pending，失败项可 retry，避免 hook 进程和 worker 崩溃造成丢消息。
- **Graceful degradation**：worker 不可用时不阻塞 Claude Code 主会话；传输错误 exit 0，客户端 bug 才 exit 2。
- **Progressive disclosure**：先给 observation index，再通过 timeline 和 get_observations 拉细节，避免一上来塞完整历史。
- **3-layer retrieval**：`search(query)` 先拿 ID 索引，`timeline(anchor=ID)` 看上下文，`get_observations([IDs])` 只取筛过的全文。
- **File Read Gate**：拦截大文件 `Read`，如果数据库里已有该文件相关 observations，先展示 timeline 和成本提示，让 agent 决定是否读详情、读 outline，或最后再读全文。
- **Production health**：文档里明确监控 pending_messages、failed queue、active sessions、WAL size、Chroma size、errors/day。

对 `harness-mem` 的启发：

- 我们已经有 `search -> timeline -> get_observations` 的类似工作流，应该继续把它写成强约束，而不是让 agent 直接拉全文。
- `wake` 不应该只追求“多给记忆”，而应该像 progressive disclosure 一样暴露“有什么、成本多少、怎么取详情”。
- 如果将来做文件级记忆辅助，可以参考 File Read Gate 的思想，但在 Codex 侧应更保守：先作为显式建议或工具，不直接拦截用户文件读取。
- `wake-up` 的 auto-ingest / distill 任务如果变重，可以借鉴 CLAIM-CONFIRM queue 和 health 指标，避免 silent stuck。
- “主会话不被记忆系统拖死”是硬边界：memory runtime 失败应可见、可诊断，但不能破坏用户当前开发流。

不能照搬：

- `claude-mem` 是 Claude Code 深绑定 hook 插件；`harness-mem` 的主线是跨 Agent 的本地 memory runtime，MCP 只是隐藏传输层，不能变成只服务 Claude Code 的 hook daemon。
- 不应默认引入常驻 worker/daemon。当前 `harness-mem` 路线已经明确先做本地 runtime 和 MCP 自动化，不把 daemon 当主路线。
- File Read Gate 不应直接变成默认阻断行为；这类能力要先有用户可理解的 escape hatch 和 stale 判断。

### 3. `mempalace`

已读本地文件：

- `F:\memory-lab\upstreams\mempalace\README.md`
- `F:\memory-lab\upstreams\mempalace\benchmarks\BENCHMARKS.md`
- `F:\memory-lab\upstreams\mempalace\benchmarks\README.md`
- `F:\memory-lab\upstreams\mempalace\docs\CLOSETS.md`
- `F:\memory-lab\upstreams\mempalace\docs\schema.sql`
- `F:\memory-lab\upstreams\mempalace\website\concepts\memory-stack.md`
- `F:\memory-lab\upstreams\mempalace\website\concepts\the-palace.md`
- `F:\memory-lab\upstreams\mempalace\website\concepts\knowledge-graph.md`
- `F:\memory-lab\upstreams\mempalace\website\concepts\contradiction-detection.md`
- `F:\memory-lab\upstreams\mempalace\website\concepts\agents.md`
- `F:\memory-lab\upstreams\mempalace\website\concepts\aaak-dialect.md`
- `F:\memory-lab\upstreams\mempalace\mempalace\dialect.py`

它最重要的产品判断是：默认存 raw/verbatim，不先让 LLM 提取后丢原文。MemPalace 自己的 benchmark 文档也把“raw verbatim + semantic search”视为核心发现，而 AAAK 只是实验压缩层。

关键机制：

- **Drawers**：原始内容 chunk，verbatim，是当前搜索和 benchmark 的主路径。
- **Closets**：可搜索索引层，包含 topic/entities/quote，并指回 drawer ID。搜索先命中 closet，再打开 drawer；没有 closet 时 fallback 到 drawer search。
- **Palace hierarchy**：wing 是人/项目，room 是主题，hall 是概念类别，tunnel 是跨 wing 的共享 room 连接。
- **Memory Stack**：L0 identity 常驻，L1 essential story 常驻，L2 room recall 按 topic 加载，L3 deep search 显式查询。
- **Temporal knowledge graph**：SQLite 中的 `entities`、`triples`、`attributes`，triple 带 `valid_from / valid_to / confidence / source_closet / source_file`。
- **Contradiction detection**：文档明确标为 experimental/planned，当前只有 temporal KG primitives，不是完整 MCP/CLI 闭环。
- **Agent diary**：通过稳定 agent name 写入各自 wing 的 diary room，用 AAAK 压缩 diary entry，但当前不宣称完整 agent registry。
- **AAAK**：有损结构化摘要方言，提取 entities/topics/key quotes/emotions/flags，不可还原原文，也不是默认存储。文档中 AAAK mode 的 LongMemEval R@5 低于 raw mode。

对 `harness-mem` 的启发：

- 默认 truth 仍应保留原始 observation 和 provenance，不应让压缩摘要替代原文。
- `wake` 可以借鉴 Memory Stack：常驻层只放 profile / essential rules / recent handoff，topic-specific recall 通过 search 或 wiki bridge 按需加载。
- `closet -> drawer` 很适合映射到我们未来的 `wiki bridge` 或 compact search：先返回短索引和 provenance，再按需打开 source observation。
- temporal KG 的 `valid_from / valid_to` 与本仓 v1.7 方向一致；它证明 SQLite 足够表达最小 bi-temporal 子集，不必一上来引入图数据库。
- contradiction detection 只能作为候选生成器参考，不应直接变成 AI 自动改 truth。
- AAAK 可以作为 wake context renderer 研究，不适合作为 canonical storage。

不能照搬：

- ChromaDB 默认后端不符合 `harness-mem` 当前 SQLite FTS5 + sqlite-vec 路线。
- Palace 的建筑隐喻很强，但本仓面向多 agent client 的 runtime，不应该强迫所有用户接受 wing/room/hall 术语。
- AAAK 对 token budget 有启发，但有损压缩会损害审计性；只能输出短摘要并保留 source ID。
- MemPalace 的 benchmark headline 只能作为复现实验线索，不能直接写进 `harness-mem` README 当比较结论。

## 对 `harness-mem` 的直接设计结论

### 1. 已下载项目共同指向“索引先行，全文按需”

三者都在不同层面支持同一个方向：

- `ai-harness`：先整理 source docs 到 knowledge cache，再 mine。
- `claude-mem`：先展示 observation index，再按 ID 拉详情。
- `mempalace`：先搜 closet，再打开 drawer。

所以 `harness-mem` 后续的正确形态不是“wake 时塞更多全文”，而是（v2.5.0/v2.5.1 已落地为分层 context assembly）：

```text
wake-up
-> 分层渲染 L0 项目 profile/identity · L1 essential truth(confirmed rules + accepted current truth) · L2 active task(handoff)
   每条带 source id 与 why-included，每层有预算与截断说明
-> search/timeline/get_observations 按需取详情（relation facts / skill 完整步骤 / raw evidence 属 query-driven L3/L4，不在 cold-start wake）
-> source observation 永远可追溯
```

### 2. wiki bridge 应该从 `ai-harness` 和 `mempalace closets` 借形

最小可行形态：

```text
accepted memory + curated docs
-> generated knowledge cache
-> docs/wiki 或其他可读输出
-> 每条 claim 保留 source observation / memory ID
```

这里借的是 source cache、generated/manual 分层、短索引指向原文，不是借一个桌面 UI。

### 3. sleep cycle 应该从 `claude-mem` 的队列和 `mempalace` 的 contradiction 边界借形

安全形态：

```text
sleep scan
-> merge / dedupe / conflict / stale detection
-> pending candidates
-> human review 或 auto-low-risk review
-> accepted truth
```

不做：

- AI 直接删 accepted memory
- AI 直接 update confirmed rule
- 失败的后台任务静默丢消息

### 4. compact renderer 可以借 AAAK，但不能变成 truth

可接受：

```text
/hm:wake --format compact
```

输出短摘要、实体、标签、source ID。

不可接受：

```text
把 accepted memory 或 observation 改写成 AAAK 后丢掉原文
```

### 5. 文件级记忆辅助可以学 File Read Gate，但默认不应阻断

File Read Gate 的真正价值是“先给历史索引和成本提示”。在 `harness-mem` 中更适合先做成：

```text
harness-mem file-context <path>
```

或 MCP tool：

```text
get_file_memory(path)
```

先返回过去对这个文件的 observations、改动、决策和 token 成本。是否读取当前文件，仍由 agent 或用户决定。

## 远程参考项目：待镜像后再深读

下面这些项目来自 2026-05-18 的讨论，目前尚未下载到 `F:\memory-lab\upstreams`。它们只作为“待镜像研究线索”，不能和上面的本地深读结论同等权重。

| 项目 | 暂定类型 | 当前可借鉴方向 | 后续动作 |
|---|---|---|---|
| [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) | Agent skill self-evolution | skill 候选生命周期、质量监控、成功工作流变成 reusable skill。 | 若进入 procedural memory 设计，先镜像后读 `openspace` 的 skill/evolution 数据模型。 |
| [Memento-Skills](https://github.com/Memento-Teams/Memento-Skills) | Deployment-time skill learning | Read-write-reflective learning，执行后反思并更新 skill library。 | 等 v1.8 procedural memory 启动前再镜像。 |
| [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) | 自动维护 wiki | Two-step ingest、source traceability、incremental cache、knowledge graph signals。 | `wiki bridge` 设计前优先镜像。 |
| [chappyasel/meta-kb](https://github.com/chappyasel/meta-kb) | 自改进知识编译器 | raw sources 编译 wiki，atomic claims 对 citation 校验，content hash 增量编译。 | `wiki bridge` 设计前优先镜像。 |
| [MarchLiu/hypatia](https://github.com/MarchLiu/hypatia) | 本地图记忆 | Knowledge entries、statement triples、temporal ranges、JSE 查询、FTS + vector。 | v1.7 temporal graph 设计前优先镜像。 |
| [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS) | 长期记忆 OS 与 benchmark 套件 | use cases / methods / benchmarks 分层，LoCoMo/LongMemEval/PersonaMem 评估。 | 只在 benchmark 口径扩展时镜像。 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | Agent memory that learns | “learn, not just recall” 的定位，API/CLI/client 分层。 | 若要复现其公开 benchmark，再镜像。 |
| [Chandler-Sun/MemChinesePalace](https://github.com/Chandler-Sun/MemChinesePalace) | 压缩实验 | “简/牍”双层表达、压缩快读摘要、原文可追溯。 | compact renderer 研究时镜像。 |
| [Jason Zuo X thread](https://x.com/xxxjzuo/status/2038086450013495554) | 想法线索 | “execution -> memory” 的 agent harness 叙事。 | 只有可访问、可引用后才正式摘录。 |

## 后续优先级

| 优先级 | 动作 | 原因 |
|---|---|---|
| P0 | 把 `reference-projects.md` 作为外部参考唯一入口，后续读项目就补这里。 | 避免 roadmap 变成研究剪贴簿。 |
| P0 | 真要做 `wiki bridge` 前，先镜像 `llm_wiki` 和 `meta-kb`。 | 它们最接近知识库编译机制。 |
| P1 | 真要做 temporal graph 前，先镜像 `hypatia`。 | 它更接近 SQLite/FTS/vector/graph 的本地实现形态。 |
| P1 | 把 `ai-harness` 的 generated/manual cache 边界转化成 `harness-mem` 的 wiki bridge 设计约束。 | 防止 AI 生成文档污染人工真相。 |
| P2 | 把 AAAK / MemChinesePalace 类压缩只放入 wake renderer 实验，不进入 storage truth。 | 保护可审计性和原文追溯。 |

## 明确不做

- 不做 cloud-first memory platform。
- 不让 AI 自治删除 accepted memory。
- 不在 runtime 和 docs compiler 有价值前先做 desktop UI。
- 不用 Markdown directory 替代 memory source of truth。
- 不允许 skill auto-rewrite 绕过 candidate review。
- 不把还没本地镜像、还没读源码的远程项目写成已验证结论。
