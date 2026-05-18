# cli Specification

## Purpose
TBD - created by archiving change v1x-retention-stability-reset. Update Purpose after archive.
## Requirements
### Requirement: 状态型命令统一格式

系统 MUST 支持所有状态型命令统一尾部格式：Phase / Next step / Why。

接口: quickstart, doctor, status, profile, wake

#### Scenario: doctor 输出格式
```
$ harness-mem doctor
📍 Phase: Budget Warning (L3)
→ Next: Run 'harness-mem purge --before <DATE> --dry-run'
   Why: Memory budget at 87%, archiving old observations can help
```

#### Scenario: status 输出格式
```
$ harness-mem status
📍 Phase: Healthy
→ Next: Run 'harness-mem ingest' to add new memories
   Why: No recent activity detected
```

### Requirement: timeline --help 真实默认值

系统 SHALL 显示 timeline --help 真实默认值。

接口: `harness-mem timeline --help`

#### Scenario: 帮助信息显示默认值
```
$ harness-mem timeline --help
usage: harness-mem timeline [-n N] [--format FORMAT]

Options:
  -n N          Number of entries (default: 20)
  --format      Output format (default: compact)
```

### Requirement: search 引导式提示

系统 SHALL 在 search 无 query 时给出引导式提示，不抛 argparse error。

接口: `harness-mem search [QUERY]`

#### Scenario: 无 query 时引导
```
$ harness-mem search
No query provided. Try:
  harness-mem search "your search terms"
  harness-mem search --scope project "terms"
```

### Requirement: correct/handoff 交互式标注

系统 SHALL 在 correct 和 handoff 的 help 中明确标注交互式行为。

接口: correct --help, handoff --help

#### Scenario: correct 帮助
```
$ harness-mem correct --help
usage: harness-mem correct <observation>

Interactively correct a memory observation.
(Interactive: will prompt for confirmation)
```

#### Scenario: handoff 帮助
```
$ harness-mem handoff --help
usage: harness-mem handoff <task>

Interactively hand off a task to the next session.
(Interactive: will prompt for confirmation)
```

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

