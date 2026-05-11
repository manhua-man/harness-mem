# Claude-Mem Sync Strategy

这份文件描述 `session-distill` 与 `claude-mem` 的第一阶段联动方式。

核心原则不是：

- raw session 直接写 claude-mem

而是：

- raw session -> packet -> packet-memory-export -> draft memory entries -> 人审/同步

## 为什么 packet 是首选中间层

直接从原始 transcript 往记忆层写，通常会同时遇到三个问题：

- 噪声太多
  - IDE 包装、重复 commentary、工具输出原文、请求重试等会一起混进去
- 压缩太早
  - 还没分清稳定结论和一次性上下文，就已经开始写 memory
- 结构不稳
  - 一段 raw session 往往同时包含多个可拆开的记忆点，不适合整段直写

`packet` 的价值就在这里：

- 它先做一次可审阅的低损耗整理
- 保留用户目标、assistant updates、final answers、commands、file refs、artifacts 等关键证据面
- 先去掉大部分原始噪声，再做 memory entry 抽取

所以对第一阶段来说，`packet` 通常比 “raw transcript 直接压成 memory” 更稳，也更容易降低无意义损耗。
真正把 packet 变成结构化 draft memory entries 的默认 sidecar 是 `packet-memory-export`，而不是让 `session-distill` core 继续长成第二个 memory tool。

但这里有一个前提：

- packet 不能假装自己完整
- 任何裁剪、compaction、只展示 top-N 的地方，都应该在 `Packet Audit` 里暴露出来

因此后续同步前，先看 packet 顶部的 `Packet Audit`：

- `Coverage: high`
  - 可以默认把 packet 当成 draft memory entry 的主输入
- `Coverage: partial`
  - 说明 packet 里仍有需要补证的地方
  - 先打开相关 raw transcript，再决定是否同步这条候选记忆

## 推荐链路

1. 原始 session 先生成 packet
2. 用 `packet-memory-export` 从 packet 提取多条 draft memory entries
3. 每条 draft entry 打标签：
   - `new`
   - `refine`
   - `confirm`
   - `conflict`
   - `ephemeral`
4. 同步策略：
   - `ephemeral` 不写入稳定记忆层
   - `conflict` 先人工审阅
   - `new / refine / confirm` 进入待同步候选
5. 用户或后续专门流程决定是否真正同步到 claude-mem

## Draft Memory Entry 最小结构

默认输出位置：

- `~/.claude/session-distill/memory-drafts/<session-id>.json`

每条 draft entry 至少应该包含：

- normalized statement
  - 归一化后的候选结论
- label
  - `new / refine / confirm / conflict / ephemeral`
- rationale
  - 一句为什么这样判定
- proposed destination
  - knowledge base / project rules / module docs / keep local
- source session id
- optional evidence
  - packet turn id、commands、files、冲突记忆 id

## 什么时候打开原始 transcript

默认先用 packet，不直接回 raw session。

只有在下面情况才回看原始 transcript：

- packet 缺了关键 turn
- 需要核对某条命令或某段原始措辞
- conflict 判断需要更完整上下文
- packet 的摘要让你无法确认这条结论是否真的稳定
- `Packet Audit` 标成了 `partial`

也就是说：

- packet 是默认入口
- raw transcript 是补证入口

## 与 mem-distill 的分工

- `session-distill`
  - 负责从 raw session 生成 packet，并给出 `Packet Audit`
- `packet-memory-export`
  - 负责把 packet 导出成 draft memory entries
- `mem-distill`
  - 负责整理已经进入 claude-mem 的 observations

因此 draft entry 仍属于 `session-distill + packet-memory-export` 这一阶段，不属于 `mem-distill` 的主输入。

## 第一阶段边界

第一阶段默认不做：

- 自动写入 claude-mem
- 与特定 memory backend 强耦合
- 未审阅直接覆盖现有 observations

第一阶段默认要做到：

- 查询增强
- 低损耗 packet 提取
- draft memory entries 标准化
- 人工可审阅的同步候选
