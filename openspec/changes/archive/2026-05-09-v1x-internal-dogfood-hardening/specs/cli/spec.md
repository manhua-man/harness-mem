# cli

## Why

内部 dogfooding 时，CLI 仍然是最常见的显式修复和诊断入口；它需要对多项目场景更安全，而不是靠隐式 active project 猜测用户意图。

## ADDED Requirements

### Requirement: structured purge 必须有明确项目上下文

当用户执行 `purge --category structured` 或 `purge --category all` 时，系统 MUST 具备明确的项目上下文；如果既没有 `--project` 也无法解析出当前项目，命令必须失败并提示用户显式给出项目。

#### Scenario: structured purge 缺少项目上下文
```bash
$ harness-mem purge --before 2026-01-01 --category all
Structured memory purge requires a project context. Use --project <name> or activate a project with 'harness-mem use <name>'.
```

### Requirement: project-scoped purge

系统 MUST 支持 `harness-mem purge -p <project>`，并且在给定项目时只影响该项目的 structured memory。

#### Scenario: purge 只清理目标项目的 structured memory
```bash
$ harness-mem purge -p alpha --before 2026-01-01 --category all
Soft-deleted 12 observations for project 'alpha'.
Soft-deleted 3 structured memories for project 'alpha'.
```

### Requirement: next-step 提示应包含可执行项目上下文

当 doctor、status、wake-up 提示用户通过 purge 采取行动时，系统 MUST 在建议命令中附带可执行的项目上下文，减少多项目环境下的歧义。

#### Scenario: doctor 给出带项目名的 purge 建议
```bash
Suggested action: harness-mem purge -p alpha --before 2026-01-01 --category all --dry-run
```
