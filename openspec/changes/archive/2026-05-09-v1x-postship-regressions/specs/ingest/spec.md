# 增量 ingest

## Why

当前增量 ingest 在第二次运行时会重复导入旧 session，破坏“默认增量同步”的承诺。

## MODIFIED Requirements

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

## ADDED Requirements

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
