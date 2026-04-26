# harness-mem 最佳实践

## 核心理念

**Local-first memory**: 你的 AI 记忆完全存储在本地，不依赖云服务。数据路径 `~/.harness-mem/data/`。

**增量优于全量**: 默认增量 ingest，避免重复导入已有 session。

**规则学习闭环**: correct → candidate → confirm → recall，持续积累项目知识。

---

## 日常使用流程

### 第一步：启动自检

```bash
harness-mem doctor
```

`doctor` 会根据当前项目状态，直接告诉你下一步应该做什么（ingest / distill / wake）。

### 第二步：接入新 Session

```bash
# Claude Code sessions（增量）
harness-mem ingest claude-code -n 5

# Codex sessions
harness-mem ingest codex -n 5

# 完全重新扫描（忽略 cursor）
harness-mem ingest claude-code --full-rescan
```

### 第三步：提取结构化记忆

```bash
harness-mem distill
```

从 session 中提取 MemoryEntry、TaskHandoff、RuleCandidate。

### 第四步：生成唤醒上下文

```bash
harness-mem wake
```

启动新 session 时带上项目上下文，快速恢复工作状态。

### 第五步：搜索记忆

```bash
# 自动模式（优先 hybrid，回退 FTS）
harness-mem search "authentication" --mode auto

# 纯全文搜索
harness-mem search "bug fix" --mode fts

# 混合搜索（需要 pip install -e ".[hybrid]"）
harness-mem search "architecture" --mode hybrid
```

---

## 项目隔离

### 设置活动项目

```bash
harness-mem use my-project
```

### 查看项目状态

```bash
harness-mem status
```

### 清理旧数据

```bash
# 干跑检查
harness-mem purge -p my-project --before 2026-01-01 --category all --dry-run

# 实际执行
harness-mem purge -p my-project --before 2026-01-01 --category observations
```

---

## 规则学习循环

### 创建候选规则

```bash
# 完全交互式
harness-mem correct

# 半交互式
harness-mem correct <observation-id> \
  -r "Always validate JWT expiry before API calls" \
  -t "Before any authenticated API call"
```

### 管理规则

```bash
# 列出候选
harness-mem candidates

# 确认规则
harness-mem confirm <candidate-id>

# 拒绝规则
harness-mem reject <candidate-id>

# 列出已确认规则
harness-mem rules
```

---

## 任务交接

```bash
# 交互式
harness-mem handoff

# 参数式
harness-mem handoff -t <task-id> -s "Fix auth bug" \
  -n "Check JWT validation logic" \
  -b "Waiting for token samples"
```

---

## Claude Code 集成（MCP）

### 安装 MCP Server

```bash
claude mcp add harness-mem -- python -m harness_mem.mcp.server
```

### 可用工具

| 工具 | 说明 |
|------|------|
| `search_memory` | 搜索记忆，支持 scope/mode |
| `timeline` | 时间线视图 |
| `get_observations` | 获取观察记录 |
| `get_task_handoffs` | 获取任务交接 |
| `get_confirmed_rules` | 获取已确认规则 |
| `get_project_profile` | 获取项目 Profile |
| `create_rule_candidate` | 创建候选规则 |
| `confirm_rule` | 确认规则 |
| `reject_rule` | 拒绝规则 |

---

## 项目 Profile 管理

```bash
# 编辑项目 Profile
harness-mem profile --edit

# 查看当前 Profile
harness-mem profile
```

Profile 包含：description、stacks（技术栈）、key_files、conventions。

---

## REST API

```bash
# 启动 API Server
harness-mem api -p 8000

# 搜索 API
curl "http://localhost:8000/search?q=authentication&scope=project&mode=auto"
```

---

## 常见问题

### Q: hybrid search 是什么？

hybrid = FTS（全文）+ 向量嵌入。embedding 不可用时自动回退到纯 FTS，CLI 会显示 `mode: fts (fallback)`。

### Q: purge 会删除数据吗？

purge 使用 soft-delete，数据标记为 `compacted` 不再显示，但文件仍保留。可用 `--category all` 或 `--category structured` 选择删除范围。

### Q: 如何查看完整时间线？

```bash
harness-mem tl 50   # 最近 50 条
harness-mem tl      # 默认最近 3 条
```

### Q: Codex sessions 和 Claude Code sessions 区别？

- Claude Code: 项目 scoped，存储在 `~/.claude/projects/{project}/`
- Codex: 全局 across projects，需要手动 review 后再 ingest

---

## 最佳实践总结

| 场景 | 推荐命令 |
|------|----------|
| 每日开始 | `harness-mem doctor` → `harness-mem wake` |
| 编码时学到规则 | `harness-mem correct` |
| 任务切换 | `harness-mem handoff` |
| 搜索记忆 | `harness-mem search -q "关键词" --mode auto` |
| 清理旧数据 | `harness-mem purge --dry-run` 先检查 |
| 启动 API | `harness-mem api -p 8080` |
