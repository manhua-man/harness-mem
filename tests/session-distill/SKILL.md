---
name: session-distill
version: 1.1.0
description: |
  将 Claude Code 的 `.jsonl` 会话文件蒸馏为可复用的规则、工作流和知识。
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

`session-distill` 是 Claude 侧的**原始会话主入口**。

它负责：
1. 扫描 `~/.claude/projects/<project>/*.jsonl`
2. 生成 packet / manifest
3. 由 AI 基于 packet 做提炼
4. 在需要时把 packet 交给下游流程继续处理

它**不**依赖 claude-mem 才能工作；claude-mem 只是查询增强项。
它的 core 输出就是：`manifest + packet + Packet Audit`。

## 链路总览

默认不要把它理解成“raw session 直接写 claude-mem”。

更准确的链路是：

1. `hook / archived session -> packet`
2. `packet -> standalone distill`
3. standalone distill 的落点通常是 `distilled/sessions/<session-id>.md`、`knowledge-base.md`，以及在明确时继续提升到 repo 规则
4. 如果要进入结构化记忆层，再走：`packet -> packet-memory-export -> memory-drafts -> 人工审阅 / sync-list -> claude-mem`

也就是说：

- `session-distill` 负责把原始会话整理成可审阅的 packet，并完成第一层提炼
- `packet-memory-export` 负责把 packet 变成结构化 memory draft
- `claude-mem` 是后续同步目标，不是 `session-distill` 的默认直写后端
- 只有 packet 证据不足时，才回看 raw session 补证

| 场景 | 使用哪个 skill |
|------|----------------|
| 用户给的是原始 `.jsonl`、项目会话、packet、session note | `session-distill` |
| 用户已经有 packet，要导出结构化 memory drafts | `packet-memory-export` |
| 用户给的是已有 claude-mem observations，要整理记忆层 | `mem-distill` |

开始提炼前，先读：

- [references/distillation-rules.md](references/distillation-rules.md)
- [references/output-layout.md](references/output-layout.md)
- [references/claude-mem-sync.md](references/claude-mem-sync.md)

## 默认循环

**路由规则**：根据 Packet Audit 的 Coverage 自动选择路径：

| Coverage | 路径 | 说明 |
|----------|------|------|
| `partial` | **standalone** | 直接读 packet → 写 session note（推荐，覆盖 96% 的 session） |
| `high` | **enhanced** | 可选走 packet-memory-export 导出到 claude-mem |

| 步骤 | 动作 |
|------|------|
| 1 | `run --next N`，刷新 manifest 并生成 packet |
| 2 | 只读一个 packet，并先看 `Packet Audit` |
| 3 | **Coverage: partial** → 直接走 standalone 路径 |
| 4 | standalone：提取用户目标、解决方案、命令、文件地图、失败模式 |
| 5 | standalone：写 `distilled/sessions/<session-id>.md` |
| 6 | standalone：将稳定知识归并进 `knowledge-base.md` |
| 7 | `mark distilled` |
| 8 | **Coverage: high**（可选）→ 运行 `packet-memory-export` 导出到 claude-mem |

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

### Auto-Standalone 模式（推荐）

自动循环处理多个 session，AI 只需读 packet 和提取知识：

```bash
# 处理下一个 session（默认）
session-distill auto-standalone

# 处理 5 个 session
session-distill auto-standalone --next 5

# 处理并同步到 claude-mem
session-distill auto-standalone --next 3 --sync-claude-mem

# 强制重新处理
session-distill auto-standalone --next 1 --force
```

**流程**：
1. 脚本自动 bundle 下一个 session
2. 脚本生成 packet 并显示路径
3. AI 读取 packet 并提取知识
4. AI 写 session note → `distilled/sessions/`
5. AI 追加稳定知识 → `knowledge-base.md`
6. 如果启用 `--sync-claude-mem`，AI 导出到 claude-mem
7. AI 运行 `mark distilled`
8. 继续下一个 session

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

如果你要处理的不是正常仓库目录，而是像 `claude-mem observer-sessions` 这种特殊项目名，需要显式传：

```bash
session-distill status --project <project-name>
session-distill run --next 3 --project <project-name>
```

但默认建议仍然是：

- 普通业务项目 session -> `session-distill`
- 已有 `claude-mem observations` -> `mem-distill`
- `observer-sessions` 这类插件内部记录，如果只是做清理，先确认相关 observations 已经入库；确认后通常归档或删除即可，不必蒸馏

## 与 claude-mem 的联动

联动细则见：

- [references/claude-mem-sync.md](references/claude-mem-sync.md)

第一阶段默认采用：

- 查询增强
- packet 导出到 sidecar
- 手动同步

也就是说，`session-distill` core 不直接写回 claude-mem，也不直接导出 memory draft JSON；增强路径交给 `packet-memory-export`。

### 首选中间层：packet

默认链路不是 “raw session 直接写 claude-mem”，而是：

- raw session -> packet -> packet-memory-export -> draft memory entries -> 人审 / 同步

原因很简单：

- packet 会先去掉大量 transcript 噪声
- packet 仍保留用户目标、assistant updates、final answers、commands、file refs 等关键证据面
- 多条 memory entry 可以从一个 packet 里拆出来，不必整段压成一条模糊记忆

只有 packet 缺失关键证据时，才回看原始 transcript 补证。

另外：

- 如果 packet 的 `Packet Audit` 显示 `partial`，不要直接把其中结论升到 claude-mem 或 repo 规则
- 先补看相关 raw transcript，再决定是否保留该条 draft memory entry

### 启用的能力

- 查询增强：提炼前先查历史记忆，用于去重、补充上下文、统一术语
- 去重：避免把旧知识再写一遍
- 术语统一：和已有记忆用同一套说法

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

第一阶段的默认目标不是“自动写进 claude-mem”，而是把 packet 交给 `packet-memory-export`，导出为标准化 memory entry 草稿。

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

- 不默认自动写入 claude-mem
- 不把 claude-mem 当成强依赖
- 不因为查不到记忆就停止蒸馏
- 不把 memory draft 导出逻辑重新塞回 core parser

### 同步方式

第一阶段默认采用人工审阅后再同步：

- `session-distill` 负责生成 packet 和 `Packet Audit`
- `packet-memory-export` 负责把 packet 变成结构化 memory drafts
- 用户或后续专门流程负责决定是否同步进 claude-mem

默认不把自动写入作为第一阶段能力。

失败时的降级策略：
- 跳过查询增强
- 继续完成 packet → session note → knowledge-base → mark

默认原则：

- claude-mem 是增强项，不是前置依赖
- session-distill 不应与特定记忆后端强耦合
- 自动写入不作为第一阶段默认能力

## 工作风格

- 默认先读 packet，不直接啃原始 `.jsonl`
- 详细 promote / filter 规则放在 [references/distillation-rules.md](references/distillation-rules.md)
- 文件布局和状态定义放在 [references/output-layout.md](references/output-layout.md)
- 一次只处理少量会话，做增量蒸馏
- 源会话继续增长时，允许重新 bundle
- memory drafts 由 sibling sidecar `packet-memory-export` 负责，而不是在这里复制第二套 parser
- 若用户其实要整理现有 observations，而不是原始 session，切换到 `mem-distill`

## 与 Codex archived-session-distiller 的关系

这两个技能是同一思路在两个客户端里的实现：
- 都是“先准备 packet，再人工/AI 提炼”
- 都把记忆系统当增强项，不做强依赖
- Claude 版面向 `~/.claude/projects/*.jsonl`
- Codex 版面向 `~/.codex/archived_sessions/rollout-*.jsonl`

## 文件位置

- 会话目录：`~/.claude/projects/<project-name>/`
- 蒸馏工作区：`~/.claude/session-distill/`
- Python 脚本：`~/.claude/skills/manhua/session-distill/bin/session-distill.py`
- Shell wrapper：`~/.claude/skills/manhua/session-distill/bin/session-distill.sh`
- memory draft exporter：`~/.claude/skills/manhua/packet-memory-export/bin/packet-memory-export.py`
