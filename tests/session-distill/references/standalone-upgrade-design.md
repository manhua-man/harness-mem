# Standalone 路径升级设计

## 问题现状

当前 standalone 路径的问题：

1. **手动操作多** — 每个 session 需要 AI 手动读 packet、写 session note、mark distilled
2. **输出格式不统一** — session note 结构依赖 AI 临场发挥
3. **无法导出到 claude-mem** — 知识只停留在 session note，无法跨 session 复用
4. **效率低** — 一次只能处理一个 session

## 升级目标

| 目标 | 说明 |
|------|------|
| 自动化 | 脚本自动完成读 packet → 提取知识 → 写 session note → mark distilled |
| 模板化 | 统一 session note 结构，提高知识提取质量 |
| 集成 claude-mem | standalone 也能导出到 claude-mem，不依赖 packet-memory-export |
| 批量处理 | 一次处理多个 session，自动循环 |

## 设计方案

### 1. 新增命令：`auto-standalone`

```bash
session-distill auto-standalone --next 5
```

**功能**：
- 自动循环处理 N 个 session
- 对每个 session：bundle → 读 packet → 提取知识 → 写 session note → 导出到 claude-mem → mark distilled
- 最后汇报处理结果

### 2. Session Note 模板

```markdown
# Session Note: {session_id}

## 概述
- **日期**: {date}
- **类型**: {type} (部署/代码审查/功能开发/调试/其他)
- **Coverage**: {coverage}
- **模型**: {model}

## 用户目标
{用户想要完成什么}

## 解决方案
{如何解决的，包括关键决策}

## 关键命令
| 命令 | 用途 |
|------|------|
| {command} | {purpose} |

## 文件地图
| 文件 | 用途 |
|------|------|
| {file} | {purpose} |

## 失败模式
{遇到的问题和解决方案，如果没有则写"无"}

## 稳定知识
{可以跨 session 复用的知识，将追加到 knowledge-base.md}
```

### 3. 自动化流程

```
auto-standalone --next N
    ↓
for each session:
    ↓
┌─────────────────────────────────────────┐
│ 1. session-distill run --next 1         │
│    ↓                                    │
│ 2. 读取 packet 文件                      │
│    ↓                                    │
│ 3. 解析 Packet Audit                     │
│    ├── Coverage: partial → standalone    │
│    └── Coverage: high → enhanced (可选) │
│    ↓                                    │
│ 4. AI 提取知识（使用模板）                │
│    ↓                                    │
│ 5. 写 session note → distilled/sessions/│
│    ↓                                    │
│ 6. 追加稳定知识 → knowledge-base.md      │
│    ↓                                    │
│ 7. 导出到 claude-mem（可选）             │
│    ↓                                    │
│ 8. mark distilled                       │
│    ↓                                    │
│ 9. 继续下一个 session                    │
└─────────────────────────────────────────┘
    ↓
汇报结果
```

### 4. Claude-mem 集成

**方式 1：直接写入（推荐）**
- 从 session note 提取稳定知识
- 调用 claude-mem API 写入
- 标记来源 session id

**方式 2：导出为 memory draft**
- 生成 `memory-drafts/{session-id}.json`
- 人工审阅后同步

**建议**：采用方式 1，但需要用户确认是否自动写入。

### 5. 批量处理汇报

```
==> Auto-Standalone Complete

Processed: 5 sessions
├── 10acc6af: 部署 session → 3 条知识
├── 66a0de9a: 代码审查 → 5 条知识
├── 95076365: 功能开发 → 2 条知识
├── 2cd3dcde: 调试 → 1 条知识
└── 625302a6: 其他 → 0 条知识

Knowledge base: 105 → 116 lines
Claude-mem synced: 11 entries (optional)
```

## 实现计划

### Phase 1：基础自动化
- [ ] 新增 `auto-standalone` 命令
- [ ] 实现 session note 模板
- [ ] 实现自动写 session note
- [ ] 实现自动追加到 knowledge-base.md
- [ ] 实现自动 mark distilled

### Phase 2：Claude-mem 集成
- [ ] 实现从 session note 提取稳定知识
- [ ] 实现调用 claude-mem API 写入
- [ ] 添加 `--sync-claude-mem` 参数控制是否同步

### Phase 3：批量优化
- [ ] 实现批量处理汇报
- [ ] 添加进度显示
- [ ] 添加错误处理和重试

## 配置参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--next` | 1 | 处理 session 数量 |
| `--sync-claude-mem` | false | 是否同步到 claude-mem |
| `--template` | default | session note 模板 |
| `--force` | false | 强制重新处理 |

## 使用示例

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
