# purge

## Why

v1.3 需要让用户能对预算预警采取行动。purge 命令让用户主动清理旧数据，而不是被动等待。

## ADDED Requirements

### Requirement: purge 命令

系统 MUST 支持软删除/compact 标记 observations/structured memory，不做物理清除。

接口: `harness-mem purge --before <DATE> [--dry-run] [--category]`

#### Scenario: dry-run 显示将要删除的内容
```
$ harness-mem purge --before 2026-01-01 --category observations --dry-run
[DRY RUN] Would soft-delete 47 observations before 2026-01-01
Observations that would be affected:
  - obs_001: "old observation 1"
  - obs_002: "old observation 2"
  ... (47 total)
```

#### Scenario: 执行软删除
```
$ harness-mem purge --before 2026-01-01 --category observations
Soft-deleted 47 observations.
Run 'harness-mem doctor' to check new memory budget.
```

#### Scenario: 全 category
```
$ harness-mem purge --before 2026-01-01 --category all --dry-run
[DRY RUN] Would soft-delete:
  - 47 observations
  - 12 structured memories
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
