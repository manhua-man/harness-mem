# Letta

- 定位：Agent 运行时的上下文预算、可编辑 core memory、归档记忆和摘要压缩参考；不是 `harness-mem` 的存储后端候选。
- Upstream：<https://github.com/letta-ai/letta>
- 本地镜像：`F:\AIInfra\upstreams\harness-mem\letta`
- 已核验 HEAD：`5beb66e9981da4802de05c90bf43fba18053d5d6`（2026-08-01）。

## 架构与数据流

Letta 将 agent 可见状态拆成 in-context 的可编辑 `Memory` blocks、消息、摘要，和上下文外的 archival/recall memory。`ContextWindowOverview` 把 system、core、summary、消息、archival、recall 以及 external-memory summary 的 token 用量显式投影出来；因此“为什么要压缩”和“压缩了什么”是可观测的，而不是隐式 prompt 拼接。

典型路径是：消息进入 agent -> context window 接近预算 -> `Summarizer` 依据模式压缩历史或滑窗旧消息 -> 保留最近消息和摘要 -> 继续调用模型。core memory block 可以按标签、字符上限和只读状态渲染；archival 则由独立服务创建、读取、更新和删除。这个分层与本项目的 raw evidence / durable truth / wake context 相似，但 Letta 的 block 是 agent runtime 状态，不应作为本项目的 truth authority。

## 状态、错误与评测语义

- 压缩是有模式、阈值和回退路径的状态转换；测试覆盖“不需要裁剪”“用户消息裁剪”“JSON 解析失败”“硬驱逐”等情形，而不是只测试最终摘要文本。
- archive manager 在服务边界处理持久化异常；它不是检索效果 benchmark，故不能从其架构推断检索质量。
- UI/UX 的核心启示是 token 预算分解和 memory projection，而不是复制其 server、API 或 block 文件树。

## 可复核证据

| 结论 | 本地源码证据 |
|---|---|
| 上下文视图列出 core、summary、archival、recall 与各段 token | `F:\AIInfra\upstreams\harness-mem\letta\letta\schemas\memory.py:23` |
| in-context memory 由带 labels 的 blocks 组成，并负责渲染 | `F:\AIInfra\upstreams\harness-mem\letta\letta\schemas\memory.py:68` |
| agent 在会话历史上调用摘要器 | `F:\AIInfra\upstreams\harness-mem\letta\letta\agents\letta_agent.py:1621` |
| archive 是独立 CRUD 服务 | `F:\AIInfra\upstreams\harness-mem\letta\letta\services\archive_manager.py:30` |
| 上下文仍超阈值时硬驱逐有回归测试 | `F:\AIInfra\upstreams\harness-mem\letta\tests\integration_test_summarizer.py:999` |
| static buffer 的裁剪和失败情况有单元测试 | `F:\AIInfra\upstreams\harness-mem\letta\tests\test_static_buffer_summarize.py:41` |

## 对 harness-mem 的取舍与版本影响

**Adapt，目标 `0.9.8`：** 在既有 `wake`/`distill` 全量诊断响应中增加内部 `context_budget` 和 `compaction_outcome`：原始证据、压缩摘要、检索上下文、最终注入上下文的数量/预算，以及 `not_needed`、`compacted`、`fallback`、`evicted` 等结果。它只解释已有数据流，不新建 store、scheduler 或 MCP tool。

验收：同一输入的预算投影确定；压缩失败或预算仍超限时有明确 outcome 和保守回退；snapshot 测试覆盖无压缩、成功压缩、失败回退、超限处理四种状态。

**Reject：** Letta agent/server runtime、云 archival 语义、block filesystem 和把可编辑 prompt block 升格为 durable truth。它们会破坏本项目“本地、审计、单一 truth store、固定 27-tool surface”的边界。
