---
name: session-distill
version: 1.0.0
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

## 概述

Claude Code 的会话文件存储在 `~/.claude/projects/` 目录下，每个项目一个文件夹，会话以 `.jsonl` 格式存储。

**本技能执行两阶段流程：**

| 阶段 | 执行者 | 说明 |
|------|--------|------|
| 准备阶段 | 脚本 | `index` → `bundle`，生成审查包 |
| 提炼阶段 | AI（我） | 读取 packet → 查询增强 → 增量判断 → 写 session note → 写 knowledge-base → 判断升规则 → mark |

## 核心概念

| 概念 | 说明 |
|------|------|
| `.jsonl` 会话文件 | 每行一个 JSON，包含 `type: user/assistant/system` 等 |
| Packet (审查包) | 从会话中生成的紧凑摘要 |
| Manifest (索引) | 会话清单，记录哪些已处理、哪些待处理 |
| Knowledge Base | 稳定可复用的知识库 |
| Session Note | 单个会话的提炼笔记 |
| Memory Entry | 标准导出的知识条目，带 YAML frontmatter |

## 快速开始

```bash
# 先准备下一批待审会话，再由 AI 完成提炼
session-distill run --next 3
```

## 完整工作流程

### 阶段 1：脚本准备（自动）

```bash
session-distill run --next 3
```

脚本自动完成：
1. **Index** — 扫描会话目录，更新 manifest
2. **Bundle** — 解析 .jsonl，生成下一批审查包 (packets/*.md)

### 阶段 2：AI 提炼（我执行）

```
1. 读取审查包 packets/<session-id>.md
2. 分析会话内容
3. 查询 claude-mem（查询增强）
4. 增量判断：new / refine / confirm / conflict / ephemeral
5. 提炼稳定知识
6. 写 session note → distilled/sessions/<session-id>.md
7. 追加到 knowledge-base.md
8. 判断是否升到项目规则
9. 执行 mark 标记为 distilled
```

---

## 与 claude-mem 的联动

### 设计目标

- 提炼前优先复用已有记忆，避免重复沉淀
- 提炼后输出结构稳定、可审阅、可迁移的知识条目
- 不依赖 claude-mem 的写接口，session-distill 不与特定记忆后端强耦合

### 角色定位

session-distill 充当：
1. **提炼器**：从 session 中提炼稳定知识
2. **查重器**：在提炼前查询已有记忆，减少重复记录
3. **导出器**：输出适合人工审阅和后续导入的标准化记忆条目

### 联动原则

| 模式 | 启用 | 说明 |
|------|------|------|
| 查询增强 | ✅ | 提炼前先查 claude-mem，用于去重、补充上下文、统一术语 |
| 标准导出 | ✅ | 输出固定格式的 memory entries，便于人工审阅与后续导入 |
| 手动同步 | ✅ | 用户定期把导出结果同步到 claude-mem |
| 自动写入 | ❌ | 暂不作为默认能力 |
| 强耦合依赖 | ❌ | session-distill 不应依赖 claude-mem 才能工作 |

### AI 提炼详细流程

#### Step 1: 读取审查包

```
读取 ~/.claude/session-distill/packets/<session-id>.md
```

分析：
- 用户请求是什么？
- AI 给出了什么解决方案？
- 使用了哪些工具/命令？
- 发现了哪些文件/代码结构？
- 如果会话很长，packet 会保留开头请求和结尾结论，省略中间冗余轮次

#### Step 2: 查询增强

查询 claude-mem，搜索相关主题的历史记忆：

```bash
# 搜索相关主题
mem-search search --query "登录 认证 游客" --limit 5

# 查看时间线上下文
mem-search timeline --limit 5
```

#### Step 3: 增量判断

把本次会话内容与查到的历史记忆做对比，给每个候选结论打上标签：

| 状态 | 说明 | 动作 |
|------|------|------|
| `new` | 新知识，历史中没有 | 导出为新条目 |
| `refine` | 对已有知识做补充/细化 | 追加到现有条目 |
| `confirm` | 再次验证已有知识 | 标记为 confirmed |
| `conflict` | 与已有知识冲突 | 标记为 conflict，人工审核 |
| `ephemeral` | 只适合本次上下文 | 跳过，不导出 |

#### Step 4: 提炼输出

生成面向长期复用的知识条目，优先输出：
- 稳定事实
- 可操作步骤
- 约束条件
- 决策原因
- 与旧知识的差异说明

#### Step 5: 标准导出

导出为 Markdown + YAML frontmatter 格式：

```markdown
---
id: sd-2026-04-22-xxx
source: session-distill
topic: 登录策略配置接口
status: new
confidence: high
sync_recommended: yes
source_session: <session-id>
dedupe_keys:
  - uos-app/login-strategy/config-endpoint
---

# 登录策略配置接口

## Summary
...

## Stable Facts
- ...

## Decisions
- ...

## Constraints
- ...

## Delta vs Existing Memory
- 新增：...
- 确认：...
```

#### Step 6: 判断升到项目规则

自问：这个知识是否应该改变 AI 在项目中的默认行为？

| 知识类型 | 目标位置 |
|---------|---------|
| 工程纪律、发布策略 | `.kiro/steering/generalbeliefs.md` |
| TypeScript/NestJS 规则 | `.kiro/steering/typescript.md` |
| 调试和问题排查 | `.kiro/steering/troubleshooting.md` |
| 模块级接口契约 | 模块文档 |

#### Step 7: 标记完成

```bash
session-distill mark <session-id> distilled
```

---

## 增量判断标准

### 推广到知识库

- 可跨任务复用
- 稳定的命令或工作流
- 有文件位置或代码结构
- 有实际验证过的解决方案

### 保留在会话笔记

- 一次性任务
- 环境特定配置
- 探索性死路
- 临时解决方案

### 升到项目规则

- 影响 AI 默认行为
- 跨会话重复出现
- 通用工程实践
- 安全或质量关键

---

## 冲突处理

如果本次会话与历史记忆冲突：

1. 不要静默覆盖旧知识
2. 在导出中标记 `conflict`
3. 显式写出：
   - 旧说法是什么
   - 新证据是什么
   - 当前更可信的判断是什么
   - 是否建议人工复核

---

## 失败与降级策略

如果 claude-mem 不可用或查询失败：

- session-distill 仍可正常工作
- 跳过查询增强步骤
- 在导出中标记：`memory_lookup: skipped`
- 继续生成标准导出

> claude-mem 联动是增强项，不是前置依赖。

---

## 命令参考

### run — 准备阶段

```bash
session-distill run [--next N] [--project PROJECT] [--force]
```

`--next N` 表示本次最多生成多少个待审 packet。

### status — 查看状态

```bash
session-distill status [--project PROJECT]
```

### list — 列出可用会话

```bash
session-distill list [--project PROJECT] [--size MIN-SIZE]
```

### mark — 标记状态

```bash
session-distill mark <session-id> <status>
```

状态：`new` | `bundled` | `distilled` | `skipped`

---

## 输出结构

```
~/.claude/session-distill/
├── manifest.json              # 会话索引和状态
├── knowledge-base.md          # 提炼的知识库
├── packets/                   # 审查包（脚本生成）
│   └── <session-id>.md
└── distilled/                # 已提炼的会话（AI 生成）
    └── sessions/
        └── <session-id>.md
```

---

## 知识库模板

```markdown
# 会话蒸馏知识库

## 稳定工作流

- **[工作流名称]**: 描述
  - 来源: `<session-id>`

## 实用命令模式

- **[命令]**: 用途
  - 来源: `<session-id>`

## 代码库发现

- **[文件/模块]**: 发现内容
  - 来源: `<session-id>`

## 反模式和失败经验

- **[问题]**: 解决方案
  - 来源: `<session-id>`

## 调试和问题排查

- **[现象]**: 排查方法
  - 来源: `<session-id>`
```

---

## 与 Codex archived-session-distiller 的对照

| Codex | Claude Code session-distill |
|-------|---------------------------|
| `distill-next.ps1` | `session-distill run` |
| `archived_session_distiller.py` | `session-distill` (Shell wrapper + Python CLI) |
| 人工审阅 packet | AI 提炼 + claude-mem 查询增强 |
| `distill` + `mark` | AI 提炼 + `session-distill mark` |

---

## 文件位置

- **会话文件**：`~/.claude/projects/<project-name>/*.jsonl`
- **项目目录**：`~/.claude/projects/`
- **蒸馏工作区**：`~/.claude/session-distill/`
- **脚本**：`~/.claude/skills/session-distill/bin/session-distill.sh`
