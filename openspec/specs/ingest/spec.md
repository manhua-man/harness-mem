# ingest Specification

## Purpose
TBD - created by archiving change v1x-retention-stability-reset. Update Purpose after archive.
## Requirements
### Requirement: ingest cursor

系统 MUST 将 `last_ingest_session_id` 解释为“上次 ingest 完成后看到的最新 session id”，并且在倒序 session 列表中只处理 cursor 之前的前缀新会话。

#### Scenario: 第二次 ingest 不重复导入旧 session
```bash
$ harness-mem ingest claude-code -p demo
Sessions found: 3
Ingested: 3 sessions

$ harness-mem ingest claude-code -p demo
[Incremental] Processing sessions newer than cursor: sess-3
Ingested: 0 sessions
Skipped existing: 0 sessions
```

### Requirement: auto ingest uses the current agent environment

系统 MUST 让 `harness-mem ingest` 默认等价于 `harness-mem ingest auto`，并根据当前运行环境选择会话来源。显式 `HARNESS_MEM_CLIENT` 配置优先；Codex runtime MUST 选择 `codex-archive`；Claude Code runtime MUST 选择 `claude-code`。

#### Scenario: Codex 环境默认使用 Codex archive
```bash
$ harness-mem ingest -p demo -n 5
Auto-detected ingest client: codex-archive
Ingesting codex-archive sessions for project: demo
```

#### Scenario: Claude Code 环境默认使用 Claude Code 项目会话
```bash
$ harness-mem ingest -p demo -n 5
Auto-detected ingest client: claude-code
Ingesting claude-code sessions for project: demo
```

### Requirement: global session stores are project-scoped by default

系统 MUST 对用户级全局会话源默认使用 `scope=project`，按当前工作目录或 `--project-root` 匹配 session 的 `cwd`，只导入属于当前项目路径的会话。系统 MUST NOT 在未显式请求时把其它项目的 Codex archive session 灌入当前 project。

#### Scenario: Codex archive 默认只导入当前 project root 下的 session
```bash
$ harness-mem ingest codex-archive -p demo -n 10 --project-root F:\demo
Scope: project
Project root: F:\demo
Sessions found: 12
Project-scope sessions: 2
Ingested: 2 sessions
```

#### Scenario: 跨项目导入必须显式 scope all
```bash
$ harness-mem ingest codex-archive -p demo -n 10 --scope all
Scope: all
Sessions found: 12
Ingested: 10 sessions
```

### Requirement: 项目 ingest 状态

系统 MUST 为每项目记录 ingest cursor 状态。

接口: 项目状态

```python
@dataclass
class IngestCursor:
    project_name: str
    last_session_id: str
    last_ingest_timestamp: datetime
```

#### Scenario: 查看 ingest 状态
```
$ harness-mem status
...
Ingest Status:
  Last ingest: sess_789 (2026-04-24T15:30:00Z)
  Sessions pending: 3
```

### Requirement: CLI 帮助信息

系统 SHALL 在 `harness-mem ingest --help` 显示增量 ingest 和全量回退选项。

#### Scenario: ingest 帮助
```
$ harness-mem ingest --help
usage: harness-mem ingest [--full-rescan]

Options:
  --full-rescan    Force full rescan of all sessions

Default: incremental (only new sessions since last ingest)
```

### Requirement: full-rescan 绕过 cursor

系统 MUST 让 `--full-rescan` 显式忽略 ingest cursor，并向用户输出 full-rescan 提示。

#### Scenario: full-rescan 强制重新扫描
```bash
$ harness-mem ingest claude-code -p demo --full-rescan
[Full Rescan] Processing all sessions without cursor shortcuts.
```

### Requirement: 缺失 cursor 的回退行为

当 cursor 对应 session 已不存在时，系统 MUST 打印 warning，并回退到基于 `last_ingest_at` 的受限扫描，而不是静默重复导入。

#### Scenario: cursor 丢失
```bash
$ harness-mem ingest claude-code -p demo
Warning: ingest cursor sess-3 not found; falling back to sessions newer than last ingest timestamp.
```
