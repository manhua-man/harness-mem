# purge

## Why

post-ship review 发现 purge 虽已发布，但在真实持久化数据上无法稳定执行，也不能保证 purge 后数据真正从用户可见路径消失。

## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: purge 后默认不可见

系统 MUST 在 verbatim 和 structured store 的默认读取路径中过滤 `compacted` 数据。

#### Scenario: purge 后 search / wake / timeline 默认不再显示旧数据
```bash
$ harness-mem search "old preference"
[FTS Search]
# no purged matches returned
```
