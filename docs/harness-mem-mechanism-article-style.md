# Harness-Mem

传统 Agent Memory 系统通常把“存什么、什么时候存、怎么取回”写死在某个固定 workflow 里：要么是对话摘要器，要么是向量库 RAG，要么是模型内部 memory token。这样的方式在短期演示里有效，但一旦进入真实软件项目协作，就会遇到三个问题：

- 普通对话、调试日志、代码决策、用户偏好、版本状态混在一起，缺少可审计边界。
- AI 生成的“记忆”如果直接进入长期上下文，会把误判、噪声和跨项目信息污染后续任务。
- 用户不应该逐条审查几百条候选，也不应该学习底层 MCP 或 CLI 命令才能使用记忆系统。

Harness-Mem 的核心不是让 Agent “自动记住一切”，而是把 Agent 记忆做成一个 **local-first、candidate-first、可审计的 AI memory runtime**。AI 负责读取历史 session、提炼候选、自动处理低风险项；人只做最终复核与纠错。只有经过确认的 current truth 才能进入 `wake` / `search_memory`，用于新任务上下文。

## Harness-Mem 架构

Harness-Mem 采用分层运行时架构：

```text
用户入口层
  /hm:distill / /hm:wake / /hm:search
  repo-local Skill
  自然语言指令

Agent 编排层
  session-distill
  auto-review
  mem-distill / grill-me / answer-me 等可选协作者

MCP 协议层
  mcp/server.py
  mcp/tool_specs.py
  wake / search_memory / prepare_session_distill / suggest_* / auto_review_candidates

运行时命令层
  commands/wake.py
  commands/search.py
  commands/ingest.py
  commands/auto_review.py
  commands/candidates.py
  commands/metabolism_pass.py
  context_assembly.py / wake_render.py

本地存储层
  LocalMemoryBackend
  LocalVerbatimStore
  LocalStructuredStore
  ReflectionJobStore
  JSON blobs + SQLite FTS5 + optional vector cache
```

用户看到的是 Slash、Skill 或自然语言；MCP 是 Agent 背后的传输层；CLI 只用于安装、自检、doctor、purge、config、integration 等维护场景，不承担日常 memory workflow。

## Harness-Mem 核心过程

### 1. Evidence Packet 构建过程

当用户触发 `/hm:distill` 或自然语言等价入口时，Agent 不会直接凭印象写记忆，而是先调用：

```text
prepare_session_distill(client="auto", scope="project", project_root=<当前项目根>)
```

Runtime 会自动识别 Codex、Claude Code、Cursor、Antigravity、opencode、Hermes 或 generic agent 的历史来源，并把项目范围内的 session、observation、source id 组织成 evidence packet。

这一层的关键是 **raw evidence first**：原始 observations 和 provenance 必须保留。摘要可以帮助理解，但不能替代证据。

### 2. 记忆候选构建过程

LLM Agent 或 `session-distill` Skill 读取 evidence packet 后，会提炼出几类候选：

- `MemoryEntry`：长期项目事实、技术决策、任务状态、架构约定。
- `RuleCandidate`：会影响未来协作方式的规则或偏好。
- `RelationFact`：实体之间的关系，例如模块、版本、文档、决策之间的关联。
- `ProceduralCandidate`：可复用工作流，确认后才能成为 `Skill`。
- `SupersedeCandidate` / `MergeSuggestionCandidate` / `StaleTruthSuggestionCandidate`：纠错、合并、过期治理建议。

所有这些内容都先进候选层。也就是说，AI 提炼出的内容默认只是 pending candidate，不是 confirmed truth。

对应工具链是：

```text
suggest_memory_entry
suggest_rule
suggest_relation_fact
suggest_skill
suggest_supersede
```

### 3. 自动审核过程

候选写入后，Agent 调用：

```text
auto_review_candidates(project_name=<project>, apply=true)
```

这一层复用 shared low-risk review policy：

- 自动确认低风险、证据充分的长期事实。
- 自动拒绝噪声、重复、跨项目泄漏、工具调用失败记录、泛泛建议。
- 对高风险、证据不足、会改变长期行为的候选保持 pending，并放进最终摘要给人复核。

关键点是：自动审核不是静默改写真值。每个 applied decision 都有 candidate id、evidence id 和 policy reason，可以回看为什么确认或拒绝。

### 4. Human Final Review 过程

人类不需要逐条看所有候选。默认体验是只看 `/hm:distill` 的最终摘要：

```text
自动确认了什么
自动拒绝了什么
还剩哪些高风险项
哪些需要人工确认
```

人类的职责不是做机械分类，而是处理 AI 不该擅自决定的部分：证据不足、跨项目边界不清、可能改变长期工作方式、可能覆盖旧 truth 的候选。

### 5. Confirmed Truth 消费过程

只有 confirmed/current truth 才能进入运行时消费：

```text
wake
search_memory
file_context
search_skills
get_skill
```

`wake` 用于新 session 启动或恢复任务时注入上下文；`search_memory` 用于主动检索历史决定；`file_context` 用于按文件路径找到相关记忆；`search_skills` 和 `get_skill` 用于显式查找可复用流程。

Pending 候选、历史失效 truth、未确认 procedural skill 不会默认混进 wake。

### 6. Signal 与 Metabolism 过程

Harness-Mem 会记录记忆如何被使用：

- `wake_surfaced`
- `search_hit`
- `confirmed`
- `rejected`
- `skill_result_success`
- `skill_result_failure`
- `supersede_completed`

这些 `RetrievalSignal` 不是新的 truth，而是治理证据。它们可以帮助后续 metabolism 过程发现重复命中、长期未使用、低成功率 skill、可能需要合并或过期的记忆。

`metabolism_preview` 只做 replay 窗口预览，不改 truth；`metabolism_run` 可以生成 merge / stale / supersede suggestion candidates，但仍然进入候选层，不会自动修改 confirmed truth。

## 核心机制

### Candidate-before-Truth 机制

Harness-Mem 最重要的机制是 **候选先行**：

```text
AI 提炼 / 用户显式记录 / 纠错建议
        ↓
pending candidate
        ↓
auto-review + human final review
        ↓
confirmed/current truth
        ↓
wake / search_memory 消费
```

这与许多动态记忆系统不同。Harness-Mem 不把“LLM 觉得重要”直接等同于“长期事实”。AI 只能先提出候选，truth 变化必须经过 review 边界。

### Raw Evidence + Progressive Disclosure 机制

系统保留原始 observation，并用 source ids 把摘要、候选和 confirmed truth 连回证据。

默认检索先返回摘要、来源和少量解释；需要时再展开 timeline、raw observation 或 get details。这种 progressive disclosure 可以避免每次 wake 都塞入大量历史全文，同时仍保留审计能力。

### Hybrid Retrieval 机制

底层检索由 `HybridSearchLayer` 提供：

```text
query
  -> SQLite FTS5
  -> optional vector candidates
  -> weighted RRF fusion
  -> source ids
  -> progressive disclosure
```

当 embedding 不可用时，系统退回 FTS；当 hybrid 可用时，FTS 与向量候选通过 weighted reciprocal rank fusion 融合。Raw regex search 还会通过 trigram candidate pruning 降低原始文本扫描成本。

### Context Assembly 机制

`wake` 不是简单拼接所有记忆，而是通过 context assembly 生成分层计划：

- L0：项目 profile 和当前任务基础信息。
- L1：高优先级 confirmed rules / handoffs。
- L2：相关 memory entries。
- L3：query-driven drilldown，例如 relation facts 或 skill hints。
- L4：需要时展开的原始 evidence pointer。

`wake_render.py` 再把计划渲染成带 source id 的上下文文本。Compact renderer 和 skill hints 都是 opt-in，不会默认把完整 procedural skill body 注入上下文。

### Procedural Skill 机制

重复工作流可以沉淀成 procedural memory，但仍然走候选层：

```text
ProceduralCandidate
  -> confirm_skill
  -> confirmed Skill
  -> search_skills / get_skill
  -> record_skill_result
```

Skill 不会自动自学习，不会默认进入 wake，也不会静默跨项目共享。跨项目 skill 需要 `skill_promotion` 候选和显式确认；skill revision / deprecation 也进入 review surface。

### Reflection Job / Host Trigger 机制

v2.4 以后，Harness-Mem 提供 opt-in host hook / scheduler trigger 的技术地基：`ReflectionJob`、lease、retry、provenance、job visibility、doctor queue health。

但它不是 always-on daemon。`triggers.*` 默认是 `off`，`worker.mode` 也不是默认后台主路径。host trigger 只是安全触发入口，不会把候选写入变成 autonomous learning。

## 与典型 Agent Memory 方案的区别

### 与 A-MEM 的区别

A-MEM 强调动态记忆操作、结构化笔记和基于 Zettelkasten 的链接生成。Harness-Mem 也支持结构化记忆和关系事实，但它更强调工程协作中的治理边界：

- A-MEM 的重点是动态组织和联动检索。
- Harness-Mem 的重点是候选、证据、审核、确认、消费之间的可审计链路。

换句话说，Harness-Mem 不是只解决“怎么把记忆连起来”，而是解决“哪些 AI 提炼可以成为长期 truth，以及为什么”。

### 与 MemoryBank 的区别

MemoryBank 更像用户画像、事件摘要和遗忘曲线驱动的长期对话记忆。Harness-Mem 面向的是 AI 编程/项目协作场景：

- 不把所有对话都自然衰减成记忆强度。
- 不默认后台随手记。
- 更重视 project scope、source id、候选审核和 confirmed truth。

### 与 MemoChat 的区别

MemoChat 主要服务开放域多轮聊天一致性，通过备忘录维护长期对话状态。Harness-Mem 面向跨 session 的开发协作：

- 记忆对象包括代码决策、架构约定、测试状态、release gate、用户工作方式。
- 读取方式不只是聊天回复，而是 `wake`、`search_memory`、`file_context`、`search_skills` 等运行时工具。

### 与 MemGPT 的区别

MemGPT 把 LLM 看作 CPU + 小上下文窗口，通过函数调用在主上下文和外部记忆之间搬运数据，强调模型自己管理虚拟上下文。

Harness-Mem 不把记忆管理完全交给 LLM 自治。它让 LLM 作为操作者和一线审核员，但所有长期 truth 变化必须通过 candidate/review 层：

- MemGPT 强调 LLM 自主调度记忆。
- Harness-Mem 强调 AI 提议、人类可复核、系统可审计。

### 与 Memory Token 类方案的区别

Memory Token 方案把记忆注入模型内部可更新 token 或隐藏状态，适合研究模型内部长期学习。Harness-Mem 是外部 runtime：

- 不改模型权重。
- 不依赖特定模型架构。
- 可被 Claude Code、Codex、Cursor、Gemini 等不同 Agent 共享。
- 本地存储、可检索、可审计、可回滚。

## 一句话总结

Harness-Mem 是一个面向 AI 编程协作的 **可审计记忆运行时**：它不追求让 Agent 静默自学习，而是让 Agent 在显式入口下读取证据、提炼候选、自动审核低风险项，并把最终确认过的长期 truth 用于 wake、search 和任务恢复。
