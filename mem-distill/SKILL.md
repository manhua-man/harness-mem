---
name: mem-distill
version: 1.2.0
description: |
  整理已有 memory / observations，把分散记忆收敛为稳定规则、工作流和项目级经验。
  当用户说"整理一下现有记忆"、"清理重复 observations"、"把记忆归纳成知识"时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
  - Agent
---

# Memory Distiller — 记忆层蒸馏器

## 定位

`mem-distill` 是既有记忆整理入口。

它只处理已经存在的 memory / observations，不负责原始 `.jsonl` 会话解析，也不替代 `session-distill` 或 `packet-memory-export`。

它可以作为 `session-distill` review 阶段的外置协作者被调用，但不是默认链路硬依赖。

## 主链边界

`session-distill` 的 durable memory promotion 主链仍然是：

```text
session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only
```

`mem-distill` 不进入这条 raw session 处理链。它只在用户已经要整理既有 memory / observations 时切换过去。

任何情况下，缺少 `mem-distill` 都不应阻塞 `session-distill` 主链。

## 场景路由

| 场景 | 使用哪个入口 |
|------|--------------|
| 用户要整理原始会话、生成 packet、写 session note | `session-distill` |
| 用户已有 packet，要导出结构化 memory drafts | `packet-memory-export` |
| 用户要整理现有 memory / observations、去重、归并、补充知识库 | `mem-distill` |

一句话分工：

- `session-distill` 是原始会话入口
- `packet-memory-export` 是默认 draft gate
- `mem-distill` 是现有记忆整理入口

和 `session-distill` 的衔接方式：

- `session-distill` 第一阶段先生成 packet 和 `Packet Audit`
- `packet-memory-export` 再把 packet 变成结构化 draft memory entries
- `mem-distill` 再处理已经存在的 observations，负责去重、归并、提炼和稳定化
- 如果手里还是 packet 或 draft memory entries，说明你还在 `session-distill / packet-memory-export` 阶段，不应直接切到 `mem-distill`

## 目标

把已有记忆做三件事：

1. 找出重复、冲突、可合并的 observations
2. 提炼为稳定知识，落到 `memory/knowledge-base.md`
3. 判断是否需要进一步升到项目规则

## 推荐流程

### 1. 先看记忆全貌

```bash
mem-search timeline --limit 20
mem-search smart_outline --limit 5
```

### 2. 再按主题聚类

```bash
mem-search search --query "登录 认证 JWT" --limit 10
mem-search search --query "支付 会员 发货" --limit 10
```

### 3. 对候选记忆做判断

对每条 observation，只做下面几类决策：

- `merge`：和已有记忆重复或可并入同一主题
- `refine`：已有结论基本正确，但可以补充约束、例外、步骤
- `confirm`：再次验证已有记忆，增强可信度
- `conflict`：与现有记忆冲突，需要显式记录冲突点
- `skip`：一次性上下文，不值得进入稳定知识层

### 4. 更新知识库

只把稳定、可复用的内容写进：

```text
memory/knowledge-base.md
```

可保留的类型：

- 稳定工作流
- 实用命令模式
- 文件地图和代码库事实
- 可复用的排障模式
- 值得脚本化/技能化的重复动作

## 推广标准

沿用 `session-distill` 的同一套规则，不在这里复制第二份：

- [../session-distill/references/distillation-rules.md](../session-distill/references/distillation-rules.md)
- [../session-distill/references/output-layout.md](../session-distill/references/output-layout.md)

原则上：

- memory 里的临时线索，不往上提
- 可复用做法和模式，进 `knowledge-base.md`
- 需要预先约束 AI 行为的，进项目规则
- 本质是系统事实的，回到模块文档 / 注释 / 测试

## 不做的事

- 不解析原始 `~/.claude/projects/*.jsonl`
- 不生成 packet / manifest
- 不把 packet 直接变成 memory drafts
- 不把自己当作 `session-distill` 的替代品
- 不把特定 memory backend 当成必须写回的强依赖出口
- 不作为 `session-distill` 主链的默认联动

## observer-sessions 例外说明

observer session 目录下虽然也是 `.jsonl`，但它们本质上更接近工具内部观察记录，不是这份 skill 要整理的 memory 层输入。

默认建议：

- 如果目标是整理现有 observations，继续使用 `mem-distill`
- 如果目标只是清理 observer session 这类内部记录，先确认相关 observations 已经入库；确认后，归档或删除通常比蒸馏更合理
- 只有在你明确想审计这些原始 observer session 本身时，才切到 `session-distill`

注意：

- 删除 observer session 不等于删除已经写进 memory backend 的 observations
- 但会失去这批原始 observer transcript 的追溯、重放和重新提取能力
- 因此更稳的默认动作不是"看见就删"，而是"确认已入库且不再需要审计后，再归档或删除"

## 常用命令

```bash
mem-search timeline --limit 10
mem-search smart_outline --limit 5
mem-search search --query "主题关键词" --limit 10
mem-search get_observations --ids "<observation-id>"
```

## 工作风格

- 先聚类，再提炼，不要一条条零散追加
- 优先合并重复记忆，不要制造第二份说法
- 冲突要显式记录，不要静默覆盖
- 如果用户给的是原始 session 而不是 memory，切回 `session-distill`
