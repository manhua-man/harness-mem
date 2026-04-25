# v1x-retention-stability-reset Specs

## ADDED Requirements

### purge 子命令

**接口**: `harness-mem purge --before <DATE> [--dry-run] [--category]`

软删除/compact 标记，不做物理清除。doctor 和 wake 在 L3/L4+ 时直接给出 purge 建议和示例命令。

#### Scenario: dry-run 模式
```
$ harness-mem purge --before 2026-01-01 --category observations --dry-run
[DRY RUN] Would soft-delete 47 observations before 2026-01-01
```

#### Scenario: 执行模式
```
$ harness-mem purge --before 2026-01-01 --category observations
Soft-deleted 47 observations. Run 'harness-mem doctor' to check new budget.
```

### show -o/--observation-id

**接口**: `harness-mem show -o <observation-id>`

新增 `-o/--observation-id`，保留 `-i/--id` 作为 v1.4 前兼容别名。

#### Scenario: 使用新标志
```
$ harness-mem show -o obs_123
=== Observation ===
Content: ...
```

### timeline --help 真实默认值

**接口**: `harness-mem timeline --help`

显示真实默认值，不只显示 argparse 默认。

#### Scenario: 帮助信息
```
$ harness-mem timeline --help
usage: harness-mem timeline [-n N] [--format FORMAT]

Options:
  -n N          Number of entries (default: 20)
```

### search 引导式提示

**接口**: `harness-mem search [QUERY]`

无 query 时给出引导式提示，不抛 argparse error。

#### Scenario: 无 query
```
$ harness-mem search
No query provided. Try:
  harness-mem search "your search terms"
  harness-mem search --scope project "terms"
```

### MCP reject_rule_candidate

**接口**: MCP tool `reject_rule_candidate`

补齐 reject_rule_candidate，与 confirm_rule_candidate 对称。

#### Scenario: 拒绝规则候选
```
MCP → reject_rule_candidate({ rule_id: "rule_123", reason: "outdated" })
✓ Rule rejected
```

### HybridSearchLayer

**接口**: `search --mode auto|fts|hybrid`

引入本地向量检索层。向量模型懒加载，未安装 embedding 依赖时自动退化为纯 FTS。

#### Scenario: auto 模式（embedding 可用）
```
$ harness-mem search "dark mode" --mode auto
[Hybrid Search] score=0.94
```

#### Scenario: auto 模式（embedding 不可用）
```
$ harness-mem search "dark mode" --mode auto
[FTS Search] (embedding not available, using full-text search)
```

### MCP suggest_rule

**接口**: MCP tool `suggest_rule`

用户建议规则，完成 confirm/reject/suggest 完整闭环。

#### Scenario: 建议新规则
```
MCP → suggest_rule({ rule_text: "User prefers dark mode", context: "..." })
✓ Suggestion recorded
```

### scope=project|all

**接口**: MCP 查询 `scope=project|all`

MCP 查询增加 scope=project|all，支持跨项目检索。project_name 仅在 scope=project 时必填。

#### Scenario: 跨项目检索
```
MCP → search_memories({ query: "dark mode", scope: "all" })
```

### Provenance 字段

**接口**: MemoryEntry/ConfirmedRule/TaskHandoff

为 MemoryEntry、ConfirmedRule、TaskHandoff 增加来源 observation/session 信息。

#### Scenario: 查看来源
```
$ harness-mem show -o obs_123
=== Observation ===
Content: User prefers dark mode...
💡 Source: from session sess_456 (2026-04-20)
```

### ingest cursor

**接口**: `harness-mem ingest [--full-rescan]`

每项目 ingest cursor，默认增量 ingest，只处理新 session。提供 --full-rescan 作为显式回退。

#### Scenario: 增量 ingest
```
$ harness-mem ingest
[Incremental] Processed 3 new sessions since last ingest (sess_789)
```

#### Scenario: 全量回退
```
$ harness-mem ingest --full-rescan
[Full Rescan] Processing all sessions...
```

---

## MODIFIED Requirements

### 状态型命令格式

**影响命令**: quickstart, doctor, status, profile, wake

所有状态型命令统一尾部格式：Phase / Next step / Why。

#### Scenario: doctor 输出格式
```
📍 Phase: Budget Warning (L3)
→ Next: Run 'harness-mem purge --before <DATE> --dry-run'
   Why: Memory budget at 87%, archiving old observations can help
```

### wake-up 截断标记

**影响**: wake 命令输出

统一加 `[...truncated]`。

#### Scenario: wake 输出
```
$ harness-mem wake
Rule: User prefers dark mode for code reviews [...truncated]
💡 Source: obs_123 from session sess_456
```

### search 结果 score

**影响**: search 命令输出

搜索结果统一展示排序依据或 score。

#### Scenario: 搜索结果
```
$ harness-mem search "dark mode"
1. obs_456 "User prefers dark mode" (score: 0.94)
2. obs_123 "Dark theme for IDE" (score: 0.87)
```

---

## REMOVED Requirements

### 物理删除

**移除**: 任何直接物理删除 observation/structured memory 的命令

purge 命令只做软删除/compact 标记，不做物理清除。

---

## RENAMED Requirements

### CLI/MCP 语义对齐

原"控制面"概念重命名为"控制面迁移轴"，明确 CLI 和 MCP 各自角色。

| 版本 | CLI 角色 | MCP 角色 |
|------|----------|----------|
| v1.3-v1.4 | 一等 bootstrap 和诊断入口 | 补齐生命周期 |
| v1.5-v1.6 | 辅助/诊断/运维 | 主入口 |
| v2.0 | debug/admin surface | invisible memory |
