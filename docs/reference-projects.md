# 参考项目边界与机制结论

> **Maintainer-only — not user-facing.**
>
> 这份文档保留当前仍有维护价值的外部参考锚点、机制速记和直接设计结论；不再维护历史评分、跨项目总分榜或整份深读摘抄。当前版本状态、已完成切片和对外 claim 边界以 [`roadmap-status.md`](./roadmap-status.md) 与 `../CHANGELOG.md` 为准。
>
> 分维能力对照（十维雷达、含「参考项目峰值」说明）见 [`reference-comparison-matrix.md`](./reference-comparison-matrix.md)。

## 文档定位

- 它不是路线图，不负责描述未来版本计划。
- 它不是 benchmark，不负责给外部项目打总分。
- 它不是当前实现真值；当前真值仍以状态页、CHANGELOG、spec 和测试为准。
- 它只回答三件事：**该借什么**、**不该借什么**、**这些机制对 harness-mem 直接意味着什么**。

## 当前参考锚点

| 参考 | 该借什么 | 不该借什么 |
|---|---|---|
| `claude-mem` | progressive disclosure、queue/worker health、graceful degradation、failure-visible runtime discipline | Claude-only hook daemon、默认阻断式 file gate、产品壳绑定 |
| `mempalace` / `ai-harness` | raw/verbatim 优先、generated/manual 分层、source-first cache、memory stack | palace 术语体系、generated 内容反写 truth、运行产物变协作源 |
| `codedb-mcp` | project-local generated layer、index discipline、tool-cost observer、结构层先于 prose | 把 code-intel benchmark 当成 harness-mem 收益、把 generated wiki/module atlas 当 truth |
| `llm_wiki` / `meta-kb` | claims-first、source map、citation verification、incremental compile、review queue | 用 wiki/prose 替代 canonical memory truth |
| `Graphiti / Zep` / `hypatia` | current/history/as_of、valid/recorded time、bounded graph/time retrieval | 完整图数据库路线、自动 ontology、图先于 truth |
| `evo` / `OpenSpace` / `Memento-Skills` | ledger、host adapter、skill outcome governance、显式 activation | 自治 skill rewrite、默认后台优化循环、绕过候选审核 |
| `Letta` / `EverOS` / `hindsight` | platform boundary awareness、scope separation、broader memory OS framing | cloud-first 平台化转向、把 harness-mem 扩成全栈 agent runtime |
| `MemChinesePalace` | compact renderer、中文压缩表达、palace hierarchy 的展示启发 | 有损压缩替代原文、把 compact 输出当 canonical truth |

## `codedb-mcp` cost / performance 锚点

`codedb-mcp` 不是 memory runtime，但它仍然是本仓在 cost discipline、generated layer
和本地索引工程化上的 P0 参考。保留这一节，是为了提醒自己什么能借，什么不能偷换成
`harness-mem` 自己的收益叙事。

README benchmark snapshot 给出的锚点仍值得记住：

| 指标 | enabled | disabled | 观察 |
|---|---:|---:|---|
| Total feature-analysis runs | 335,940 tokens / 920.9s | 590,834 tokens / 1,482.9s | token -43.1%，runtime -37.9% |
| World-map marching logic | 92,639 tokens / 272.5s | 231,810 tokens / 617.8s | token -60.0%，runtime -55.9% |
| Hero attributes / power calculation | 114,436 tokens / 348.0s | 173,576 tokens / 379.9s | token -34.1%，runtime -8.4% |
| Alliance rally / join-rally logic | 128,865 tokens / 300.4s | 185,448 tokens / 485.2s | token -30.5%，runtime -38.1% |

真正该借的是三件事：

- project-local generated layer：派生产物有明确落点、可删、可重建。
- tool-cost observer：能看 broad reads、high-output calls、missed bundle/context opportunities。
- 结构层先于 prose：先有 module/source/claim 层，再有 wiki 页面。

明确不该借的是两件事：

- 不能把这组 code-intel benchmark 直接写成 `harness-mem` 的收益。
- 不能把 generated wiki、module atlas、agent prose 提升成 truth。

因此本仓对外讲 token/cost saving、latency 或 retrieval recall 时，仍只能引用自己的
artifact；`codedb-mcp` 只能当方法学和工程形态参考。

## 项目机制速记

### `claude-mem`

- 最有价值的是 progressive disclosure：先给 observation index，再走 timeline / detail，而不是一上来塞整段历史。
- queue/worker health 和 graceful degradation 很实用。记忆系统出故障时应该可见、可诊断，但不能拖死主会话。
- File Read Gate 的思路可借，但在本仓里更适合作为显式建议，而不是默认阻断用户读文件。

### `mempalace` / `ai-harness`

- 两者共同指向 raw/verbatim 优先、source-first cache、generated/manual 分层。
- `closet -> drawer` 很适合映射到“短索引先返回，原文按需打开”的搜索路径。
- Memory Stack 对 wake 有启发：常驻层只放 profile、essential truth、active handoff，深层材料按 query 再取。
- AAAK 之类压缩适合 renderer，不适合作为 canonical storage。

### `codedb-mcp`

- 关键价值不是 DeepWiki 本身，而是 project-local generated layer、module/source 中间层和可观测工具面。
- setup、registration、usage、maintenance 分开写，是很重要的产品纪律。
- 它证明了“更强的 repo knowledge 编译”应先生成结构层，再让 agent 写 prose。
- 它也再次提醒：code-intel substrate 和 cross-session memory runtime 是互补关系，不是一个东西。

### `llm_wiki` / `meta-kb`

- 最值得吸收的是 claims-first、source map、citation verification、incremental compile、review queue。
- generated layer 应该能表达“这条 claim 来自哪里、何时失效、为什么需要重编译”。
- 不应让 wiki/prose 反写 canonical truth。

### `Graphiti / Zep` / `hypatia`

- 真正有价值的是 `current / history / as_of`、`valid time / recorded time` 和 bounded graph/time retrieval。
- 这证明本仓可以先在 SQLite 上做最小 temporal truth/read model，而不是先上完整图数据库。
- 不该借的是 graph-first ontology、自动实体图 merge、把图结构本身当 truth authority。

### `evo` / `OpenSpace` / `Memento-Skills`

- ledger、host capability matrix、skill outcome governance、显式 activation 都值得借。
- 这些项目证明了“运行时账本”和“低成功率 / 失败面可诊断”对自治能力很重要。
- 不该借的是 always-on 优化循环、自治 skill rewrite、默认后台自我改写。

## 吸收优先级

| 已落地线 | 主要参考 | 已吸收 | 明确不吸收 |
|---|---|---|---|
| v3.1 Auto Dream | `claude-mem` + `evo` + `OpenSpace` + `Memento-Skills` | queue/job health、显式 run ledger、apply/reject/undo、host/scheduler 触发 | always-on daemon、自治 truth mutation、默认 subagent orchestration |
| v3.2 / v3.6 Generated Knowledge Compiler | `codedb-mcp` + `llm_wiki` + `meta-kb` + `ai-harness` | project-local generated layer、source map、atomic claims、citation validation、incremental cache | 把 wiki prose 或 generated cache 当 truth |
| v3.3 Temporal Query | `Graphiti` + `hypatia` + `mempalace` + `hindsight` | current/history/as_of、valid/recorded time、supersede timeline、abstention metadata | 完整图数据库、自动 ontology、AI 直接改 confirmed truth |
| v3.4 / v3.5 Runtime Health / Cost / Benchmark Evidence | `codedb-mcp` + `claude-mem` + `evo` + `OpenSpace` | cost observer、per-surface budget、runtime health、version drift、claim gate | 云端 telemetry、dashboard-first、未过 gate 的收益宣传 |
| v3.7 Skill Evolution Governance | `OpenSpace` + `Memento-Skills` + `evo` + `claude-mem` | skill outcome ledger、revision/deprecation candidates、显式 shared activation | skill 自改 confirmed body、shared skill 默认污染 wake |
| v3.8 Retrieval Shootout | `hypatia` + `mempalace` + `codedb-mcp` | FTS/vector/hybrid 对照、latency/fallback/token-cost 字段、embedding candidate 治理 | 用 recall 冒充 answer correctness，或静默替换默认 embedding |
| v4.0.x Storage / Index Foundation | `codedb-mcp` + `mempalace` | canonical store、migration checksum、SearchBackend contract、generated sidecar 纪律 | 把 smoke 当生产性能、过早宣传 Rust speedup |
| v4.1 Context Sufficiency | `Graphiti / Zep` + `codedb-mcp` + `hindsight` | deterministic sufficiency report、retrieval plan、context plan、wake budgeter | 用 sufficiency smoke 冒充端到端回答正确率 |
| v4.3 Code-Memory Federation | `codedb-mcp` + `llm_wiki` | file fingerprint、symbols、code-evidence stale checks、generated layer boundary | 把 generated wiki/module atlas 当 truth，或宣称达到 code-intel benchmark |

## 对 harness-mem 的直接设计结论

### 1. 索引先行，全文按需

正确方向不是 wake 时塞更多全文，而是：

```text
wake
-> L0 profile / identity
-> L1 essential truth
-> L2 active handoff
-> search / timeline / get_observations 按需取详情
```

### 2. wiki bridge 先结构层，再 prose

最小可行形态应该是：

```text
accepted memory + curated docs
-> project-local generated cache
-> claim / module / source-map 中间层
-> wiki / compact page / human-readable output
```

### 3. sleep / metabolism 只生成候选，不静默改 truth

安全形态应该是：

```text
scan
-> merge / dedupe / stale / conflict detection
-> pending candidates
-> auto-low-risk review or human review
-> confirmed truth
```

### 4. compact renderer 可以压缩，但不能替代原文

- 可以做 compact wake renderer、中文压缩表达、短索引摘要。
- 不可以丢 source ID，不可以让压缩文本替换 accepted memory 或 observation 原文。

### 5. 文件级记忆辅助应是建议式，而不是阻断式

- 先返回这个文件的历史 observations、相关决策、stale signal、上下文成本提示。
- 是否真的读取文件全文，仍由 agent 或用户决定。

### 6. code knowledge compilation 与 memory substrate 必须分层

- repo source 可以生成 code-intel / wiki cache，再由 memory 通过 file path、claim ID、source ID 去引用它。
- 不能把 generated prose、DeepWiki、module atlas 直接写回 accepted truth。

### 7. 自动化能力必须是 opt-in + ledger-first

- 自动化能做建议、审计、低风险处理、健康信号汇总。
- 自动化不能绕过 candidate / review / supersede / ledger，也不能默认变成后台自治循环。

## 硬边界

- external benchmark numbers 不是 harness-mem 分数
- generated layer 不是 truth store
- code-intel substrate 不是 memory runtime
- retrieval / cost / latency 的 claim 只能来自本仓自己的 artifact
- generated prose 不是 canonical memory truth
- 不做 cloud-first memory platform
- 不允许 AI 自治删除 accepted memory 或静默改 confirmed truth
- 任何外部机制都不能绕过 candidate / review / supersede / ledger
