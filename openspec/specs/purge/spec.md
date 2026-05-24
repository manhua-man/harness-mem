# purge Specification

## Purpose

Purge 是显式 cleanup 操作（soft-delete 老 observation / memory entry），属于 CLI 维护控制台范畴。其副作用必须在 MCP 读路径上一致：被 purge 的数据默认不出现在 `wake` / `search_memory` / `timeline` 结果里。

## Requirements

### Requirement: purge 命令

系统 MUST 用 UTC-aware cutoff 解释 `--before <DATE>`，并且 dry-run 与真实执行必须共用同一套筛选逻辑。

#### Scenario: persisted timestamp 可正常比较

```bash
$ harness-mem purge --before 2026-01-01 --category observations --dry-run
[DRY RUN] Would soft-delete 47 observations before 2026-01-01
```

系统 MUST 为 `observations` 和 `memory_entries` 持久化 soft-delete 状态，并对已有 SQLite 数据库自动补齐 `compacted` 列迁移。

#### Scenario: 旧数据库自动迁移 compacted 列

```bash
$ harness-mem purge --before 2026-01-01 --category all
Soft-deleted 47 observations.
Soft-deleted 12 structured memories.
```

### Requirement: doctor 集成 purge 建议（L3/L4）

系统在 L3/L4+ 时 MUST 直接给出 purge 建议和示例命令。

#### Scenario: doctor 在 L3 显示 purge 建议

```text
$ harness-mem doctor
📍 Phase: Budget Warning (L3)
💡 Run: harness-mem purge -p <project> --before 2026-04-01 --category observations --dry-run
   to preview what can be archived.
```

### Requirement: wake 集成 purge 建议（L4）

`wake` MCP 工具在 L4 wake-up budget 高水位时 MUST 在输出文本里附带 purge 建议（指向 CLI，因为 purge 是显式维护操作）。

#### Scenario: wake 在 L4 显示 purge 建议

```text
Agent 调 wake(project_name="demo")
→ 返回 output 含:
   "⚠️  Memory budget critical (L4): 94%
    💡 Run from terminal:
       harness-mem purge -p demo --before 2026-03-01 --category observations --dry-run"
```

### Requirement: purge 后默认不可见

系统 MUST 在 verbatim 和 structured store 的默认读取路径中过滤 `compacted` 数据，包括 MCP `search_memory` / `timeline` / `wake`。

#### Scenario: purge 后 search 默认不再返回旧数据

```text
Agent 调 search_memory(project_name="demo", query="old preference")
→ 返回 results=[]（被 purge 的旧 preference 不再出现）
```
