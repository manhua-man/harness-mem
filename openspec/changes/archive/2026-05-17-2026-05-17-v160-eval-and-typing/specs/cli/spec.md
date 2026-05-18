# cli

## Why

v1.6.0 引入 `MemoryEntry.memory_type` 字段后，CLI 需要做两件事：

1. 提供 `harness-mem maintenance assign-memory-types` 命令把已存在的 entry backfill 上类型
2. CLI `search` 输出格式增加 `memory_type` 列，便于人工审查

不引入按类型 filter 的子命令（v1.6.1 才做）。

## ADDED Requirements

### Requirement: maintenance 命名空间下的 assign-memory-types 子命令

CLI MUST 提供 `harness-mem maintenance assign-memory-types`，参数语义如下：

- `--dry-run`（默认）：只打印待写入的 `(id, category, derived memory_type)` 与汇总，**不落盘**
- `--apply`：实际写入 `memory_type` 字段；与 `--dry-run` 互斥
- `--project <name>` / 活动项目：必须有项目上下文，否则命令必须以非零退出码失败并提示用户用 `use` 或 `--project`

命令 MUST 幂等：连续 `--apply` 后再次 `--dry-run` 显示 0 条待变更。

#### Scenario: dry-run 不写盘并显示待变更数
```bash
$ harness-mem maintenance assign-memory-types --dry-run
Would update 18 MemoryEntry rows (0 already typed).
- mem_123 (category=convention) -> semantic
- mem_456 (category=bug)        -> semantic
- mem_789 (category=raw_note)   -> episodic
No changes written. Use --apply to commit.
```

#### Scenario: apply 后再次 dry-run 显示 0 条
```bash
$ harness-mem maintenance assign-memory-types --apply
Updated 18 MemoryEntry rows.

$ harness-mem maintenance assign-memory-types --dry-run
Would update 0 MemoryEntry rows (18 already typed).
```

#### Scenario: 缺项目上下文时失败而非静默
```bash
$ harness-mem maintenance assign-memory-types --apply
Error: maintenance commands require a project context. Use 'harness-mem use <name>' or pass --project.
```

### Requirement: search 输出展示 memory_type 列

CLI `harness-mem search` 在每条 memory entry 行上 MUST 显示 `memory_type`，列宽紧跟 `category`，避免破坏现有 score / id 列对齐。

#### Scenario: search 输出含 memory_type
```bash
$ harness-mem search "single quote"
[Hybrid Search]
- mem_123 [convention/semantic] "use single quote" (score: 0.92)
- mem_456 [bug/semantic]        "trailing comma breaks parser" (score: 0.81)
```

#### Scenario: observation 行不强制显示 memory_type
```bash
$ harness-mem search "auth"
- obs_456 "User login fails when token expired" (score: 0.78)
- mem_001 [bug/semantic] "Validate JWT expiry" (score: 0.71)
```
