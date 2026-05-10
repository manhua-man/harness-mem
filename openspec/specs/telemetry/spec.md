# telemetry Specification

## Purpose
TBD - created by archiving change v1x-internal-dogfood-hardening. Update Purpose after archive.
## Requirements
### Requirement: local event log

系统 MUST 将 CLI 主链命令写入本地 `events.log`，并且日志必须保留在本地数据目录，不得默认发送到远程服务。

#### Scenario: search 命令写入本地事件
```bash
$ harness-mem search "dark mode"
```

```json
{"event_type":"command_invoked","command":"search"}
```

### Requirement: next-step observability

当系统展示下一步建议，或用户执行属于建议链路中的命令时，系统 MUST 记录对应的 `next_step_shown` 与 `next_step_adopted` 信号。

#### Scenario: doctor 展示下一步建议
```json
{"event_type":"next_step_shown","source_command":"doctor"}
```

### Requirement: learning loop event coverage

系统 MUST 为 `correct`、`confirm-rule`、`reject-rule` 等 learning loop 关键动作记录本地事件，方便内部 dogfooding 时核对闭环是否真的发生。

#### Scenario: confirm-rule 记录 learning loop 完成
```json
{"event_type":"learning_loop_complete","stage":"rule_confirmed"}
```

