# CLI 清晰度

## Why

状态型命令的输出格式不一致，影响用户体验和可预测性。需要统一格式让 CLI 更可预测。

## ADDED Requirements

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
