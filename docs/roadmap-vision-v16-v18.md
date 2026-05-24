# harness-mem v1.6 - v1.8 远景路线

> 状态：远景文档（vision），不是承诺路线图。每个版本的落地形态会在前一版本收尾时再细化。
>
> 本文档配合 [`roadmap-v15x.md`](./roadmap-v15x.md) 阅读：v1.5.x 是把当前架构做扎实，v1.6 - v1.8 是架构跃迁。

---

## 当前生态坐标（参考与对标）

写这份远景前，先把本仓在 2026 年中 AI memory 生态的位置标清楚。下面只列**已验证可信**的对标项目，不含搜索时撞到的若干疑似 AI 生成的"传说"项目。

### 主流 agent memory 系统

| 项目 | 架构核心 | 我们的差异点 |
|------|----------|--------------|
| [Mem0](https://github.com/mem0ai/mem0) | Vector store + 可选 KG，托管云为主 | 我们 local-first，无云依赖；他们偏个性化场景 |
| [Zep / Graphiti](https://github.com/getzep/graphiti) | Bi-temporal 知识图谱（时间是一等公民） | 他们图为先；我们当前向量+FTS 为先，**v1.7 准备引入时间维度** |
| [Letta（MemGPT 后继）](https://docs.letta.com/) | OS 风格 stateful runtime，分级记忆 | 他们包了完整 agent 运行时；我们只做 memory 层，可被任何 agent 适配 |
| [A-MEM (NeurIPS 2025)](https://arxiv.org/abs/2502.12110) | Zettelkasten 风格 agentic memory，动态索引与连接 | 学术参考，我们 v1.7 的图化设计可以借鉴 |

### 关键学术方向（决定 v1.7 / v1.8 的形态）

- **三层记忆模型**：episodic（事件）/ procedural（技能）/ declarative（规则）。多篇 2025-2026 论文以此分层，例如 [Unifying Memory, Skills, and Rules in LLM Agents](https://arxiv.org/abs/2604.15877)（标题概念，未细读全文）
- **Procedural memory**：让 agent 把"我之前怎么解决"沉淀为可重用 skill 而非纯文本。代表工作 [LEGOMem](https://arxiv.org/abs/2510.04851)、[ProcMEM](https://arxiv.org/abs/2602.01869)、[Exploring Agent Procedural Memory](https://arxiv.org/abs/2508.06433)
- **Bi-temporal 知识图谱**：每条事实带 valid_from/valid_to + recorded_at，原生处理"知识更新"。Graphiti 是这条路线的工程代表
- **LongMemEval 五维评估**（[arxiv:2410.10813](https://arxiv.org/abs/2410.10813)）：information extraction / multi-session reasoning / temporal reasoning / knowledge updates / abstention。本仓 v1.5 baseline 已能跑 R@5；v1.7 后要按维度细分

### 关键基础设施选项

- [sqlite-vec](https://github.com/asg017/sqlite-vec)：sqlite-vss 后继，纯 C 零依赖，把向量搜索做进 SQLite 单文件——天然契合本仓 local-first 路线
- bge-small / nomic-embed-text 等比 all-MiniLM-L6-v2 更新的小型 embedding 模型

### 借鉴边界：吸收机制，不照搬产品

这几个版本会继续参考外部 agent memory 系统里已经验证过的机制，但只借**机制**，不借整套产品壳。尤其是 `Claude Dream / KAIROS` 一类系统，值得吸收的是：

- 锁文件 `mtime = cursor` 这一类低成本状态编码技巧
- “时间门 -> 会话门 -> 锁门”这种由便宜到昂贵的 gate 顺序
- distill / consolidation 期间的只读工具边界
- 对上下文预算和索引膨胀的强约束

不跟随的边界也要提前写死：

- 不做 daemon / proactive / 常驻 assistant runtime
- 不做 AI 无审核自治删除记忆
- 不用 markdown memory dir 取代 SQLite / structured store

这组边界会直接影响 v1.6 - v1.8 的设计取舍。

---

## v1.6 — 持久化向量与记忆分型

**主题**：把"查询时即算 embedding"的临时方案升级为持久化向量索引，并把 `MemoryEntry.type` 从单一字段拓展成显式分型，为 v1.7 / v1.8 打地基。

### v1.6 现状痛点（来自 v1.5 实测）

- `HybridSearchLayer._embed_texts` 每次查询都要 encode 整个 FTS 候选池（10× limit ≈ 50-100 条），CPU 上每次 ~50-150ms，是查询延迟主要来源
- `MemoryEntry.type` 当前只是字符串标签，AI 检索时无法按"事件 vs 规则 vs 技能"分桶，wake-up 永远把所有类型混在一起选 top-5

### v1.6 演进方向

| 方向 | 实质工作 | 预期收益 |
|------|---------|---------|
| 持久化向量索引 | 集成 sqlite-vec，所有 verbatim observation 与 memory entry 入库即算 embedding；search 走 SQL JOIN，不再热路径 encode | wake-up P95 latency 下降一档；冷启动后无 embedding 模型加载等待（可选） |
| 记忆三层分型 | 在 schema 显式区分 `episodic`（observation/事件原文）/ `semantic`（confirmed rule、relation fact）/ `procedural`（v1.8 引入） | wake-up 不再“全库混排 top-k”，而是按 type 分桶选取，避免 episodic 噪声淹没 semantic 规则 |
| 分桶预算纪律 | 借鉴外部系统对 `MEMORY.md` 行数/体积的强约束，但不引入 markdown 索引文件；改为 wake-up 的 **每个 type bucket 独立 token 配额 + 全局上限** | 让 wake-up 输出可控、可解释，避免某一类记忆无限膨胀 |
| Distill 只读安全护栏 | 在 distill / conflict detection 设计里提前定义只读边界：允许读取、搜索、比较、聚类，但不允许直接删 truth、改 confirmed rule、执行 SQL delete/update | 提前锁死安全边界，避免后续把 LLM 变成“能直接改库”的黑箱写手 |
| Embedding 模型升级 | all-MiniLM-L6-v2（22MB，384 维） → bge-small-en-v1.5 或 nomic-embed-text-v1.5（~130MB，768 维） | 学术 baseline 上 R@5 通常 +2-3 pp；代价是模型体积变大 |
| LongMemEval 五维细分 | 把当前 avg_recall 拆分为 5 个维度分别报告 | 后续优化能定位到"是 temporal 弱还是 abstention 弱"，不再笼统调权重 |

### v1.6 额外设计约束

- **分桶预算不是新文件系统**：这里借的是“预算纪律”，不是 `MEMORY.md` 这个产品形态。本仓 source of truth 仍然是 SQLite。
- **distill 只能写建议层**：即使 v1.6 引入更强的冲突检测，LLM 的“写”也必须落在 `RuleCandidate`、`MergeSuggestion`、`ConflictCandidate` 这一类候选层，而不是直接覆盖 truth。
- **推荐的首版 bucket 比例**：`semantic` 50%，`episodic` 50%，`procedural` 0%。`procedural` 在 v1.8 真正成型前不抢 wake-up 预算。

### v1.6 待确定的品味决策（启动时再定）

- 默认 embedding 模型选哪一个？体积/质量/许可的三角权衡
- sqlite-vec 是必选还是 optional extra？必选简化代码，optional 保 local-first 纯净度
- 记忆分型一次切到三层还是先切两层（episodic + semantic）？
- 分桶预算的默认比例是否按 `50 / 50 / 0` 起步，还是先只实现 `episodic / semantic` 两桶？

---

## v1.7 — 时间感知与图关系

**主题**：让"知识会变"成为一等公民。本仓当前的 ConfirmedRule / RelationFact 是无时间维度的快照——但用户的项目规则会演进（"以前用 Vue 现在改 React"），AI 需要知道"当前有效的事实"和"历史上曾经的事实"。

### v1.7 现状痛点

- `RelationFact` 只有 created_at，没有 `valid_from / valid_to`，没法表示"这条关系从某时起失效"
- ConfirmedRule 互相冲突时（旧规则 vs 新规则）只能靠用户手工 reject 旧的，没有自动 supersede 机制
- LongMemEval 的 `knowledge-update` 维度本仓当前是弱项（v1.6 拆完五维后会有具体数字）

### v1.7 演进方向

| 方向 | 实质工作 | 参考 |
|------|---------|------|
| Bi-temporal 字段 | 所有 RelationFact / ConfirmedRule 增加 `valid_from / valid_to / recorded_at`；search 默认只返回 currently-valid 事实，可显式查 history | Graphiti 的 bi-temporal 设计是工程参考 |
| Supersede 关系 | 新事实可声明 `supersedes: <old_fact_id>`，自动把旧事实置为 `valid_to=now`，**但不删除旧事实** | A-MEM 的 dynamic linking 思路 |
| 关系图查询 | RelationFact 当前是孤立三元组，v1.7 引入"沿关系链多跳"查询接口（subject → predicate → object → predicate' → ...） | HippoRAG 的多跳召回思路 |
| 冲突检测 | distill 阶段检测新规则是否与现有 confirmed rule 冲突，作为 RuleCandidate 的一类待审标记 | 本仓原创，无直接对标 |

### v1.7 设计立场：选择 supersede，不选择 dream-style 自治删除

这里要和外部 dream 系统做一个明确分叉。

- 外部 autonomous assistant 可以接受“发现旧事实错了就直接改掉”
- `harness-mem` 的护城河是 **auditable memory runtime**

因此 v1.7 的冲突解决策略必须是：

- 新事实生效
- 旧事实保留
- 旧事实只被标记 `valid_to=now`
- 用户仍然可以查历史和 provenance

这意味着 v1.7 做的是 **mark-not-delete**，不是“让 AI 自己收拾旧记忆”。

### v1.7 不做的（避免越界）

- 完整知识图谱引擎（Neo4j/嵌入图 DB）。**保留 SQLite 单文件**作为 local-first 底线，图查询用 recursive CTE 实现，跳数限制 ≤ 3
- 自动 ontology 学习。先让用户/AI 显式声明实体类型，自动学习留给 v2.0
- 自动冲突自修复。distill 可以提出 supersede 候选，但不能绕过 confirm/reject 直接改写已生效规则

---

## v1.8 — 程序记忆（技能层）

**主题**：从"记得起" → "做得对"。当前 ConfirmedRule 是声明式（"在这个项目里要用 single quote"），但很多有价值的"记忆"其实是过程式（"修这种 SQL 注入 bug 的步骤是 1-2-3"）。procedural memory 让 AI 把同类任务的解决路径沉淀为可调用 skill。

> **状态：2026-05-22 v1.8.x 已完成保守闭环。** 已新增 `ProceduralCandidate` 候选层、confirmed `Skill` 层、三组 repo-relevant fixture、`search_skills` 检索入口，以及 `record_skill_result` 成功率回写。边界仍然不变：不接入默认 wake selection、不自动提升 truth、不跨项目共享 skill、不做后台 daemon。

### v1.8 现状痛点

- `RuleCandidate` 只能表达"如果 X 则应当 Y"，无法表达"做 Z 任务时按 step1 → step2 → step3 走"
- 用户在 session 里反复教 AI 做同样的事（"先跑 ruff，再 mypy，再 pytest"），但 AI 下次新 session 又得重学

### v1.8 演进方向

| 方向 | 实质工作 | 参考 |
|------|---------|------|
| Skill schema | 新增 `Skill` 类型：activation_condition + steps + termination_condition + success_examples | ProcMEM 的 Skill-MDP 形式化 |
| 从 episodic 抽取 skill | session-distill 升级：识别"重复出现的多步流程"自动提议 SkillCandidate | LEGOMem 的轨迹分解思路 |
| Skill retrieval | 任务开始时 AI 先查 `search_skills(task_description)`，命中则按 step 执行 | A-MEM 风格 |
| Skill 评估闭环 | Skill 执行成功/失败需回写 success_rate；低于阈值的 skill 进入 review 队列 | 本仓的 confirm/reject 模式扩展 |
| 重型离线分析模型 | 仅当 procedural extraction 真的变重时，评估子进程 / subagent 式离线分析，把主请求和离线归纳解耦 | 借鉴 forked analysis 的任务模型，但不引入 KAIROS 生命周期 |

### v1.8 为什么才考虑后台分析

后台子进程 / 子代理并不是坏机制，但它属于“重型整理任务如何不阻塞主请求”的工程手段，不是当前产品的主轴。

因此只有当 v1.8 真的出现这些高成本任务时，才值得引入：

- 重复流程发现
- skill candidate 聚类
- 跨 session 的 procedural pattern 提炼

即便届时引入，也只借“主请求不阻塞、子任务只读分析、结果回写候选层”这套机制，不扩展成常驻 daemon 或 proactive assistant。

### v1.8 不做的

- 自学习 skill（强化学习/在线学习）。本仓坚持 human-in-the-loop——所有 skill 必须经用户 confirm 才生效，避免 AI 自我强化错误模式
- Skill 跨项目共享。先在单项目内闭环跑通；跨项目 skill 共享（"通用 React debugging skill"）留给 v2.0

---

## v2.0 展望（一句话级别，历史愿景）

> 注：这一节是 v1.6-v1.8 期间写下的历史愿景，不是后来实际发布的 v2.0 计划。实际 v2.0 是 heuristic distill 移除；当前版本状态以 [`roadmap-status.md`](./roadmap-status.md) 与 `CHANGELOG.md` 为准。

如果 v1.6 - v1.8 都跑通了，v2.0 的轮廓大致是：

- **多 agent 共享记忆**：不止 Claude Code 和 Codex，扩到 Cursor / Copilot / 自研 agent，记忆通过 MCP 互通
- **跨项目 skill 库**：从单项目 procedural memory 进化为可分享的"开发者技能包"
- **被动观察**：从"AI 主动写记忆" → "通过文件变更/Git 历史/编辑器事件被动学习"
- **隐私分层**：让用户标记哪些记忆"绝不上云"，哪些可在团队内共享

**现在不写 v2.0 的具体任务**——当 v1.7 / v1.8 完成时，AI 生态本身会演变到什么样还很不确定（开源 embedding 质量、本地 LLM 能力、MCP 标准化），到时再具体规划。

---

## 路线图风险与不做的事

诚实标出这份远景里**最容易变形**的几点：

1. **embedding 模型升级 vs 仓库体积**：bge-small ~130MB 已经超过 all-MiniLM 五倍多，如果 v1.6 想做更大模型（bge-large ~1.3GB），违反 local-first "开箱即用"原则。所以 v1.6 边界设在 small/base 档
2. **bi-temporal 复杂度**：Graphiti 一类系统需要专职团队维护，本仓如果只投入 1-2 人月，可能只能做最小子集（valid_from / valid_to 两个字段 + supersede 关系）。**不做**完整 ontology 演化
3. **procedural memory 学术分歧**：[Procedural Memory Is Not All You Need (arxiv:2505.03434)](https://arxiv.org/abs/2505.03434) 明确指出纯 procedural 不够，必须配 semantic 才能处理新颖任务。所以 v1.8 必须建立在 v1.7 的 semantic 层之上，不能跳着做
4. **不追 LongMemEval 单一数字**：v1.6 起按五维细分报告，避免下个 roadmap 又出现"R@5 0.95 → 0.97"这种单维度 KPI 主导的优化
5. **不引入 KAIROS / Proactive 风格 runtime**：这类能力属于完整 agent 生命周期管理，不是 memory layer 本身。需要 proactive 的用户，可以用 Letta 等 runtime 搭配 `harness-mem`
6. **不引入 AI 自治删记忆**：即使外部 dream 系统能自己“修正旧记忆”，本仓也不走这条路。所有 truth 变更都要保留历史并经过审核
7. **不把 markdown memory dir 作为主存储**：预算纪律和索引约束可以借，但 source of truth 仍然是 SQLite / structured entities，不反转底层存储模型
