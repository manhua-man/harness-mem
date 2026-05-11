---
name: session-distill
version: 1.2.0
description: |
  将 Claude Code 的 `.jsonl` 会话文件蒸馏为可审阅 packet、session note、knowledge-base 候选和 memory draft 输入。
  当用户说"整理一下对话"、"提炼会话经验"、"从会话中提取知识"时使用。
allowed-tools:
  - Bash
  - Read
  - Write
  - Edit
  - Glob
  - Grep
---

# Session Distiller — 会话蒸馏器

## 定位

`session-distill` 是原始会话处理主入口。

它负责：

1. 扫描 `~/.claude/projects/<project>/*.jsonl`
2. 生成 `manifest + packet + Packet Audit`
3. 基于 packet 做第一层提炼
4. 在需要结构化记忆时，把 packet 交给 `packet-memory-export`

它不直接写入 memory backend，也不依赖任何外置协作者才能运行。

## 主链边界

默认主链是：

```text
session-distill -> packet-memory-export -> memory-drafts review -> knowledge-base / sync-list / local-only
```

也就是说：

- `session-distill` 负责把 raw session 整理成可审阅 packet，并完成第一层 session note / knowledge-base 提炼
- `packet-memory-export` 是默认 draft gate，负责把 packet 变成结构化 memory draft
- `memory-drafts review` 决定每条 entry 是 `new / refine / confirm / conflict / ephemeral`
- review 后的落点只能是 `knowledge-base`、`sync-list` 或 `local-only`
- `Packet Audit: partial` 只降低 readiness，要求补证；它不改走另一条链
- session note 是可选归档，不是默认 promotion 通道

默认不要把它理解成 "raw session 直接写 memory backend"。

## 外置协作者

以下能力可以在已安装且场景匹配时参与 review，但都不是主链硬依赖：

| 协作者 | 使用时机 | 边界 |
|--------|----------|------|
| `grill-me` | 高风险候选结论需要压力测试 | 只给 review 意见，不 promote、不 sync |
| `answer-me` | draft 缺代码、文档、配置或测试证据 | 只补证据，不做最终决策 |
| `ask-me` | 架构、路线或方案需要咨询 | 只做方案咨询，不进入 memory promotion 主链 |
| `mem-distill` | 已有 memory / observations 需要聚类、去重、稳定化 | 处理既有记忆，不处理 raw session |

任何外置协作者不可用时，主链继续运行，不报错、不阻塞。

`grill-style` 是 review 方法论，不是独立 skill。

## 场景路由

| 场景 | 使用哪个入口 |
|------|--------------|
| 用户给的是原始 `.jsonl`、项目会话、packet、session note | `session-distill` |
| 用户已经有 packet，要导出结构化 memory drafts | `packet-memory-export` |
| 用户给的是已有 memory / observations，要整理记忆层 | `mem-distill` |
| 用户要压力测试候选结论 | 可选调用 `grill-me` |
| 用户要补证据 | 可选调用 `answer-me` |
| 用户要架构或方案咨询 | 可选调用 `ask-me` |

开始提炼前，先读：

- [references/distillation-rules.md](references/distillation-rules.md)
- [references/output-layout.md](references/output-layout.md)
- [references/memory-sync.md](references/memory-sync.md)

## 默认循环

| 步骤 | 动作 |
|------|------|
| 1 | `run --next N`，刷新 manifest 并生成 packet |
| 2 | 只读一个 packet，并先看 `Packet Audit` |
| 3 | 选择模式：standalone distill 或 `packet-memory-export` |
| 4 | standalone：按需更新 `distilled/sessions/<session-id>.md` |
| 5 | standalone：将稳定知识归并进 `knowledge-base.md` |
| 6 | enhanced：运行 `packet-memory-export export --session <session-id>` |
| 7 | enhanced：审阅 `new / refine / confirm / conflict / ephemeral`，并用 `approve / reject / defer / note` 落盘 |
| 8 | 如候选结论高风险，可选调用 `grill-me`；如缺证据，可选调用 `answer-me`；如涉及架构取舍，可选调用 `ask-me` |
| 9 | `mark distilled` |

## 快速开始

对普通用户，默认只需要记一个入口：

```text
/session-distill next
/session-distill review
/session-distill approve --entry <entry-id>
/session-distill sync-list
```

如果你在终端里直接跑脚本，默认入口是：

```bash
~/.claude/skills/manhua/session-distill/bin/session-distill.sh run --next 3
```

也可以直接调用 Python：

```bash
python ~/.claude/skills/manhua/session-distill/bin/session-distill.py run --next 3
```

如果要手动把 packet 导出成结构化 memory drafts：

```bash
python ~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py export --session <session-id>
python ~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py review --session <session-id>
python ~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py approve --session <session-id> --entry <entry-id>
python ~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py sync-list --session <session-id>
```

## 准备阶段

### run

```bash
session-distill run --next 3
```

含义：

- 扫描当前项目对应的 Claude 会话目录
- 更新 `manifest.json`
- 为接下来的 `3` 个待处理会话生成 packet

### status

```bash
session-distill status
```

查看：

- 总会话数
- `new / bundled / distilled / skipped`
- 当前待提炼 packet

### list

```bash
session-distill list --size 100
```

按文件大小筛选会话，仅用于浏览，不影响 `run --next N` 的语义。

### mark

```bash
session-distill mark <session-id> distilled
```

状态：`new` | `bundled` | `distilled` | `skipped`

### 非标准项目路径

默认情况下，`session-distill` 会优先根据当前项目目录推断 `~/.claude/projects/<project-name>/`。

如果你要处理的不是正常仓库目录，可以显式传项目名：

```bash
session-distill status --project <project-name>
session-distill run --next 3 --project <project-name>
```

默认建议仍然是：

- 普通业务项目 session -> `session-distill`
- 已有 memory / observations -> `mem-distill`
- 插件内部 observer session 如果只是做清理，先确认相关 observations 已经入库；确认后通常归档或删除即可，不必蒸馏

## 与 memory runtime 的联动

联动细则见：

- [references/memory-sync.md](references/memory-sync.md)

第一阶段默认采用：

- 查询增强
- packet 导出到 sidecar
- 人工审阅后同步候选

`session-distill` core 不直接写回 memory backend，也不直接导出 memory draft JSON；增强路径交给 `packet-memory-export`。

### 首选中间层：packet

默认链路不是 "raw session 直接写 memory backend"，而是：

```text
raw session -> packet -> packet-memory-export -> draft memory entries -> review -> knowledge-base / sync-list / local-only
```

原因：

- packet 会先去掉大量 transcript 噪声
- packet 仍保留用户目标、assistant updates、final answers、commands、file refs 等关键证据面
- 多条 memory entry 可以从一个 packet 里拆出来，不必整段压成一条模糊记忆

只有 packet 缺失关键证据时，才回看原始 transcript 补证。

### Packet Audit

- `Coverage: high`
  - packet 可以作为 draft memory entry 的主输入
- `Coverage: partial`
  - 不代表改走外置协作者
  - 只代表 readiness 降低，需要先补看相关 raw transcript 或调用 `answer-me` 补证
  - 证据补齐前，不要把结论升到 knowledge-base、sync-list 或 repo 规则

### 提炼阶段的候选标记

这些标签由 `packet-memory-export` 产出，或由 AI 沿用同一套结构手工审阅：

- `new`
  - 现有记忆里还没有，值得作为新增候选
- `refine`
  - 现有记忆大体正确，但需要补充约束、例外或更好的表述
- `confirm`
  - 现有记忆被新的 session 再次验证，可以增强可信度
- `conflict`
  - 与现有记忆冲突，需要显式指出冲突点，不能静默覆盖
- `ephemeral`
  - 只对当前任务有意义，不值得进入稳定记忆层

### 标准导出

第一阶段的默认目标不是"自动写进 memory backend"，而是把 packet 交给 `packet-memory-export`，导出为标准化 memory entry 草稿。

也就是至少要形成：

- 归一化后的候选结论
- 候选标签：`new / refine / confirm / conflict / ephemeral`
- 一句理由
- 建议落点
- 来源 session id

这一步的默认产物是：

- `~/.claude/session-distill/memory-drafts/<session-id>.json`
- 当存在已人工 `approved` 且 `ready-candidate` 的 entry 时，还会派生：
  - `~/.claude/session-distill/sync-lists/<session-id>.json`

优先从 packet 抽取，而不是直接从 raw transcript 整段压缩。

### 不启用的能力

- 不默认自动写入 memory backend
- 不把特定 memory backend 当成强依赖
- 不因为查不到已有记忆就停止蒸馏
- 不把 memory draft 导出逻辑重新塞回 core parser
- 不把 `grill-me` / `answer-me` / `ask-me` / `mem-distill` 内置成默认链路

## 工作风格

- 默认先读 packet，不直接啃原始 `.jsonl`
- 详细 promote / filter 规则放在 [references/distillation-rules.md](references/distillation-rules.md)
- 文件布局和状态定义放在 [references/output-layout.md](references/output-layout.md)
- 一次只处理少量会话，做增量蒸馏
- 源会话继续增长时，允许重新 bundle
- memory drafts 由 sibling sidecar `packet-memory-export` 负责，而不是在这里复制第二套 parser
- 若用户其实要整理现有 memory / observations，而不是原始 session，切换到 `mem-distill`

## 与 Codex archived-session-distiller 的关系

这两个技能是同一思路在两个客户端里的实现：

- 都是"先准备 packet，再人工/AI 提炼"
- 都把记忆系统当增强项，不做强依赖
- Claude 版面向 `~/.claude/projects/*.jsonl`
- Codex 版面向 `~/.codex/archived_sessions/rollout-*.jsonl`

## 文件位置

- 会话目录：`~/.claude/projects/<project-name>/`
- 蒸馏工作区：`~/.claude/session-distill/`
- Python 脚本：`~/.claude/skills/manhua/session-distill/bin/session-distill.py`
- Shell wrapper：`~/.claude/skills/manhua/session-distill/bin/session-distill.sh`
- memory draft exporter：`~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py`
