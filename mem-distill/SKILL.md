---
name: mem-distill
version: 1.1.0
description: |
  整理已有 chuck-mem observations，把分散记忆收敛为稳定规则、工作流和项目级经验。
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

## 目录结构

这套 skill 故意分成两层：

- `~/.claude/skills/manhua/mem-distill`
  - canonical implementation，真正维护行为的地方
- `~/.claude/skills/mem-distill`
  - compatibility alias，让 `Skill(mem-distill)` 和 `/mem-distill` 能直接命中

如果你在维护这套 skill，默认应该改这里，而不是改顶层 alias。

## 定位

`mem-distill` 只处理**已经进入 chuck-mem 的 observations**，不负责原始 `.jsonl` 会话解析。

| 场景 | 使用哪个 skill |
|------|----------------|
| 用户要整理原始会话、生成 packet、写 session note | `session-distill` |
| 用户要整理现有 chuck-mem 记忆、去重、归并、补充知识库 | `mem-distill` |

一句话分工：

- `session-distill` 是**原始会话入口**
- `mem-distill` 是**现有记忆整理入口**

和 `session-distill` 的衔接方式：

- `session-distill` 第一阶段先生成 packet 和 `Packet Audit`
- `packet-memory-export` 再把 packet 变成结构化 draft memory entries
- `mem-distill` 再处理已经存在于 chuck-mem 的 observations，负责去重、归并、提炼和稳定化
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
- 不把 chuck-mem 当成必须写回的强依赖出口

## observer-sessions 例外说明

`chuck-mem` 相关的 `observer-sessions` 目录下虽然也是 `.jsonl`，但它们本质上更接近插件内部观察记录，不是这份 skill 要整理的 memory 层输入。

默认建议：

- 如果目标是整理现有 `chuck-mem observations`，继续使用 `mem-distill`
- 如果目标只是清理 `observer-sessions` 这类内部记录，先确认相关 observations 已经入库；确认后，归档或删除通常比蒸馏更合理
- 只有在你明确想审计这些原始 observer session 本身时，才切到 `session-distill`

注意：

- 删除 `observer-sessions` 不等于删除已经写进 chuck-mem 数据库的 observations
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
