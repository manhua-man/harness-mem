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

