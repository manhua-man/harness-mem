# 参考项目地图：记忆运行时、知识库与自进化

> 状态：持续维护的参考地图。
>
> 初次收录：2026-05-18。中文化修订：2026-05-19。
>
> 本文记录对 `harness-mem` 设计有参考价值的外部项目。它不是路线图本身；路线图承诺仍以 `roadmap-v15x.md`、`roadmap-v16x.md` 和 `roadmap-vision-v16-v18.md` 为准。

## 已有相近文档

我们之前已经在 [`roadmap-vision-v16-v18.md`](./roadmap-vision-v16-v18.md) 里写过“当前生态坐标（参考与对标）”，但那一节偏 v1.6 到 v1.8 的远景定位，不适合承载完整参考项目清单。

本文作为更稳定的参考台账，专门回答四个问题：

- 哪些项目已经镜像到 `F:\memory-lab\upstreams`
- 哪些项目后续值得镜像
- 每个项目值得借鉴的机制是什么
- 哪些产品形态不应该照搬

## 本地 upstream 镜像

`F:\memory-lab\upstreams` 是外部参考项目的本地书架。这些目录只用于对照、阅读和 benchmark，不是当前主产品源码。

| 本地路径 | 上游仓库 | 当前用途 |
|---|---|---|
| `F:\memory-lab\upstreams\ai-harness` | `https://github.com/killop/ai-harness.git` | 本地 MemPalace workspace 封装。可参考 `source docs -> knowledge cache -> palace refresh` 的工作流形态。 |
| `F:\memory-lab\upstreams\claude-mem` | `https://github.com/thedotmack/claude-mem.git` | 面向 Claude Code 的持久记忆与压缩系统。可参考插件包装和 Claude 集成方式，但不照搬其存储模型。 |
| `F:\memory-lab\upstreams\mempalace` | `https://github.com/MemPalace/mempalace.git` | 最接近的 local-first memory runtime 参考：verbatim storage、scoped retrieval、wake-up、benchmark 与 palace 结构。 |

## 产品分层判断

这些项目不应该混成一个“大而全系统”。更合理的分层是：

```text
llm-wiki / meta-kb 风格层
  -> 项目知识库、文档维护、source traceability、wiki links、domain-topic-sub 导航

harness-mem / MemPalace 风格层
  -> 本地 memory runtime、wake context、search、confirmed rules、task handoffs

OpenSpace / Memento 风格层
  -> 技能自进化、执行模式学习、procedural memory
```

`harness-mem` 应继续保持为 local-first memory runtime。wiki 可以作为伴生输出层，而不是替代 runtime store。

## 2026-05-18 讨论新增参考

| 项目 | 类型 | 值得借鉴 | 对 `harness-mem` 的边界 |
|---|---|---|---|
| [HKUDS/OpenSpace](https://github.com/HKUDS/OpenSpace) | Agent skill self-evolution | evolved skill 的候选生命周期、skill quality monitoring、“成功工作流变成可复用 skill”、local skill search、可选 MCP 集成。 | 不把 cloud skill community 作为默认路径；继续坚持 local-first 和 review-gated memory truth。 |
| [Memento-Skills](https://github.com/Memento-Teams/Memento-Skills) | Deployment-time skill learning | Read-write-reflective learning：先检索或生成 skill，执行后再根据成功或失败反写 skill library。 | Agent 不能直接改写已生效 skill 或 memory truth；必须先进入候选层和审核层。 |
| [nashsu/llm_wiki](https://github.com/nashsu/llm_wiki) | 自动维护 wiki | Two-step ingest、source traceability、incremental cache、knowledge graph signals、community detection、persistent ingest queue、人类 review action。 | 不把 desktop UI 作为核心路线；先借 document compiler 和 traceability 模型。 |
| [chappyasel/meta-kb](https://github.com/chappyasel/meta-kb) | 自改进知识编译器 | repo-as-demo 模式：raw sources 编译成 wiki；atomic claims 对照 citation 校验；按 content hash 增量编译。 | 可以作为 `docs/wiki` 伴生架构参考；不能用 Markdown 替代 SQLite structured memory 的 truth。 |
| [MarchLiu/hypatia](https://github.com/MarchLiu/hypatia) | 本地图记忆 | Knowledge entries、statement triples、temporal ranges、JSON search expressions、FTS + vector、k-hop graph query。 | 查询语言应保留为内部或专家能力；普通 agent 使用仍走 MCP/search/wake 抽象。 |
| [EverMind-AI/EverOS](https://github.com/EverMind-AI/EverOS) | 长期记忆 OS 与 benchmark 套件 | use cases / methods / benchmarks 三段式组织，memory types，LoCoMo/LongMemEval/PersonaMem 评估口径，自进化 benchmark 视角。 | 不把 `harness-mem` 做成 server-first 平台；借 benchmark 框架，不借完整部署形态。 |
| [vectorize-io/hindsight](https://github.com/vectorize-io/hindsight) | Agent memory that learns | “learn, not just recall” 的定位，LongMemEval 中心化的评估叙事，API/CLI/client 分层。 | 公共性能数字只能作为复现实验线索，不能直接变成本仓产品宣称；先本地复现。 |
| [Chandler-Sun/MemChinesePalace](https://github.com/Chandler-Sun/MemChinesePalace) | 压缩实验 | “简/牍”双层形态：压缩快读摘要 + 原始完整来源；palace hierarchy 作为导航结构。 | 文言文压缩有启发，但不应成为 canonical storage；必须保留现代语言事实和 provenance。 |
| [Jason Zuo X thread](https://x.com/xxxjzuo/status/2038086450013495554) | 想法线索 | “execution -> memory” 的 agent harness 叙事，可用于理解 gstack + compound engineering 的产品表达。 | X 线程不是稳定技术证据；只有可访问、可引用后才适合镜像或正式总结。 |

## 架构启发

### 1. 知识库和记忆运行时不是同一个产品

wiki 层负责维护可导航的知识：

```text
domain -> topic -> sub
```

多数领域三层就够了。更深的结构应该放在 links、graph edges 或 search metadata 里，而不是暴露成用户要手动维护的层级。

memory runtime 负责维护可操作的记忆：

- accepted rules
- task handoffs
- relation facts
- searchable observations
- wake-up context

两层可以互相喂数据，但不要互相吞掉。

### 2. sleep 机制应该产出审核项，而不是自治改 truth

更适合 `harness-mem` 的 sleep 机制是：

```text
raw sessions/docs
-> sleep scan
-> dedupe / merge / conflict / decay / promote suggestions
-> pending candidates
-> review or auto-low-risk handling
-> accepted memory + optional wiki refresh
```

关键边界：sleep 可以整理、归并、发现冲突、提出建议，但不能绕过审核直接删除或改写 accepted truth。

### 3. 先借 traceability，再考虑 UI

`llm_wiki` 和 `meta-kb` 最值得学的是：把生成知识当作带 source links、status 和 review 的 compiled output。

对 `harness-mem` 来说，第一版有价值的不是新桌面应用，而是：

- 生成 `docs/wiki/` 或另一个知识输出目录
- 每个页面能追溯到 accepted memory ID 或 source observation
- 根据变更的 sessions/docs 增量刷新
- 对冲突和过期 claim 产出 pending review items

### 4. skill evolution 必须躲在候选层之后

OpenSpace 和 Memento 都指向 procedural memory：agent 应该复用成功工作流，也应该修复失败 skill。

在 `harness-mem` 里，它更适合落成未来的 `procedural` memory 和 `SkillCandidate`，而不是直接改已安装 skill。

安全形态：

```text
execution trace
-> skill pattern candidate
-> review
-> accepted procedural memory / skill asset
-> tracked success or failure
```

### 5. benchmark 必须本地可复现

EverOS 和 Hindsight 可以提供 benchmark 目录和评估语言，但它们的 headline 数字不能直接变成本仓产品宣称。

本仓仍按已有原则执行：按维度测量，保留结果文件，先本地复现，再写入路线图或 README。

## 建议的下一步

| 优先级 | 动作 | 原因 |
|---|---|---|
| P0 | 真要研究实现细节时，先把 `llm_wiki`、`meta-kb`、`hypatia` 镜像到 `F:\memory-lab\upstreams`。 | 它们最贴近 wiki/compiler/graph 这几条可能会被我们吸收的机制。 |
| P0 | `roadmap-v16x.md` 继续只写当前已承诺切片；本文保留为更宽的参考池。 | 防止 roadmap 变成研究剪贴簿。 |
| P1 | 等 v1.6 measurement 和 memory typing 稳定后，再设计最小 `wiki bridge`。 | 让 accepted semantic memory 能生成可读文档，同时不扰动 runtime。 |
| P1 | sleep cycle 只按“产出候选项的 maintenance job”设计。 | 吸收类脑整理思路，同时保留审计与审核边界。 |
| P2 | 压缩实验只作为 wake context renderer 研究。 | 对 token budget 有价值，但不适合作为 canonical truth。 |

## 明确不做

- 不做 cloud-first memory platform。
- 不让 AI 自治删除 accepted memory。
- 不在 runtime 和 docs compiler 有价值前先做 desktop UI。
- 不用 Markdown directory 替代 memory source of truth。
- 不允许 skill auto-rewrite 绕过 candidate review。
