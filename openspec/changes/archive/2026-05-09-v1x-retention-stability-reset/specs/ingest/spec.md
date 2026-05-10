# 增量 ingest

## Why

当前的 ingest 每次都全量扫描 session 历史，效率低且浪费资源。需要引入 ingest cursor 支持增量同步。

## ADDED Requirements

### Requirement: ingest cursor

系统 MUST 支持每项目 ingest cursor，默认增量 ingest，只处理新 session。提供 --full-rescan 作为显式回退。

接口: `harness-mem ingest [--full-rescan]`

#### Scenario: 增量 ingest
```
$ harness-mem ingest
[Incremental] Processed 3 new sessions since last ingest (sess_789)
Last cursor: sess_789 at 2026-04-24T15:30:00Z
```

#### Scenario: 全量回退
```
$ harness-mem ingest --full-rescan
[Full Rescan] Processing all sessions...
This may take a while for large histories.
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
