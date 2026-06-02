# telemetry Specification

## Purpose

定义 harness-mem 本地事件日志（`events.log`）的契约。Telemetry 是内部 dogfood 工具，覆盖**仍然在 CLI 控制台路径上的命令**（init / quickstart / qs / doctor / purge / maintenance / import / config / integration）以及**MCP 工具调用**。日常用户路径（IDE 命令 / Slash / Agent 自然语言）是否记 telemetry 由具体 MCP 工具实现决定，本规格不强制 IDE 客户端打点。

所有 telemetry 默认只写本地数据目录，不发送任何远程服务。

## Requirements

### Requirement: local event log

系统 MUST 把 CLI 控制台命令（`init` / `quickstart` / `qs` / `doctor` / `purge` / `maintenance` / `import` / `config` / `integration`）以及关键 MCP 工具调用写入本地 `events.log`，并且日志必须保留在本地数据目录，不得默认发送到远程服务。

#### Scenario: doctor 命令写入本地事件

```bash
$ harness-mem doctor
```

```json
{"event_type":"command_invoked","command":"doctor"}
```

#### Scenario: search_memory MCP 工具调用写入本地事件

```text
Agent 调 search_memory(project_name="demo", query="dark mode")
```

```json
{"event_type":"mcp_tool_invoked","tool":"search_memory","project_name":"demo"}
```

### Requirement: next-step observability

当 `doctor` 展示下一步建议，或用户后续执行属于建议链路中的命令 / MCP 工具时，系统 MUST 记录对应的 `next_step_shown` 与 `next_step_adopted` 信号。

#### Scenario: doctor 展示下一步建议

```json
{"event_type":"next_step_shown","source_command":"doctor","next_step":"harness-mem purge -p alpha --before 2026-04-01 --category all --dry-run"}
```

#### Scenario: 用户采纳建议

```json
{"event_type":"next_step_adopted","source_command":"doctor","executed":"harness-mem purge"}
```

### Requirement: learning loop event coverage

系统 MUST 为关键 learning loop 动作（`suggest_rule` / `confirm_rule` / `reject_rule` / `suggest_correction` / `auto_review_candidates(apply=true)`）记录本地事件，方便核对闭环是否真的发生。

#### Scenario: confirm_rule 记录 learning loop 完成

```json
{"event_type":"learning_loop_complete","stage":"rule_confirmed","rule_id":"rule_123","project_name":"demo"}
```

#### Scenario: auto_review apply 记录批量结果

```json
{"event_type":"auto_review_applied","project_name":"demo","auto_confirmed":3,"auto_rejected":1,"kept_pending":0}
```
