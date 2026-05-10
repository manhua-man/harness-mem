# purge Specification

## Purpose
TBD - created by archiving change v1x-retention-stability-reset. Update Purpose after archive.
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
```
$ harness-mem doctor
📍 Phase: Budget Warning (L3)
💡 Run: harness-mem purge --before 2026-04-01 --category observations --dry-run
   to preview what can be archived.
```

### Requirement: wake 集成 purge 建议（L4）

系统在 L4 时 MUST 直接给出 purge 建议和示例命令。

#### Scenario: wake 在 L4 显示 purge 建议
```
$ harness-mem wake
⚠️  Memory budget critical (L4): 94%
💡 Run: harness-mem purge --before 2026-03-01 --category observations --dry-run
   to free up space.
```

### Requirement: purge 后默认不可见

系统 MUST 在 verbatim 和 structured store 的默认读取路径中过滤 `compacted` 数据。

#### Scenario: purge 后 search / wake / timeline 默认不再显示旧数据
```bash
$ harness-mem search "old preference"
[FTS Search]
# no purged matches returned
```

