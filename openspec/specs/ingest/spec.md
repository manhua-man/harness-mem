# ingest Specification

## Purpose

Ingest 是把原始会话日志（Claude Code `~/.claude/projects/*/...jsonl`、Codex archive `rollout-*.jsonl` 等）转成 Observation、写入 verbatim 层的步骤。它**不是用户日常操作**——日常 ingest 由 IDE 命令 / Skill 在 `prepare_session_distill` 主链里隐式触发。Spec 描述的契约面对 MCP 工具与 Agent 编排层；CLI 层 v2.1 已不再暴露 `harness-mem ingest` 子命令。

> 等价 MCP 工具：`ingest_sessions(project_name, client, limit, scope, project_root, full_rescan)`、`prepare_session_distill(...)`（一次性 ingest + evidence packet）。

## Requirements

### Requirement: ingest cursor

系统 MUST 将 `last_ingest_session_id` 解释为"上次 ingest 完成后看到的最新 session id"，并且在倒序 session 列表中只处理 cursor 之前的前缀新会话。

#### Scenario: 第二次 ingest 不重复导入旧 session

```text
Agent 调 ingest_sessions(project_name="demo", client="claude-code", limit=10)
→ 第一次返回: ingested=3 sessions_found=3
Agent 再调一次 ingest_sessions(project_name="demo", client="claude-code", limit=10)
→ 第二次返回: incremental_cursor="sess-3" ingested=0 sessions_found=3 skipped_existing=0
```

### Requirement: auto ingest uses the current agent environment

系统 MUST 在 `client="auto"` 或省略 client 参数时，根据当前运行环境选择会话来源。显式 `HARNESS_MEM_CLIENT` 配置优先；Codex runtime MUST 选择 `codex-archive`；Claude Code runtime MUST 选择 `claude-code`。

#### Scenario: Codex 环境默认使用 Codex archive

```text
Agent 在 Codex CLI 内调 ingest_sessions(project_name="demo", client="auto", limit=5)
→ 返回: client="codex-archive" auto_detected=true
```

#### Scenario: Claude Code 环境默认使用 Claude Code 项目会话

```text
Agent 在 Claude Code 内调 ingest_sessions(project_name="demo", client="auto", limit=5)
→ 返回: client="claude-code" auto_detected=true
```

### Requirement: global session stores are project-scoped by default

系统 MUST 对用户级全局会话源默认使用 `scope=project`，按 `project_root` 参数（缺省时 fallback 到当前工作目录）匹配 session 的 `cwd`，只导入属于当前项目路径的会话。系统 MUST NOT 在未显式请求时把其它项目的 Codex archive session 灌入当前 project。

#### Scenario: Codex archive 默认只导入当前 project root 下的 session

```text
Agent 调 ingest_sessions(
    project_name="demo",
    client="codex-archive",
    limit=10,
    project_root="F:\\demo",
    scope="project",
)
→ 返回: scope="project" sessions_found=12 project_scope_sessions=2 ingested=2
```

#### Scenario: 跨项目导入必须显式 scope all

```text
Agent 调 ingest_sessions(
    project_name="demo",
    client="codex-archive",
    limit=10,
    scope="all",
)
→ 返回: scope="all" sessions_found=12 ingested=10
```

### Requirement: 项目 ingest 状态

系统 MUST 为每项目记录 ingest cursor 状态。

```python
@dataclass
class IngestCursor:
    project_name: str
    last_session_id: str
    last_ingest_timestamp: datetime
```

#### Scenario: Agent 查看 ingest 状态

```text
Agent 调 get_project_status(project_name="demo")
→ 返回包含: ingest_status={last_session_id: "sess_789",
                         last_ingest_timestamp: "2026-04-24T15:30:00Z",
                         pending_sessions: 3}
```

### Requirement: full-rescan 绕过 cursor

系统 MUST 让 `full_rescan=true` 显式忽略 ingest cursor，并在 ingest 返回 payload 上标 `full_rescan=true`，以便上层 UI 提示。

#### Scenario: full-rescan 强制重新扫描

```text
Agent 调 ingest_sessions(
    project_name="demo",
    client="claude-code",
    full_rescan=true,
)
→ 返回: full_rescan=true output 含 "[Full Rescan] Processing all sessions without cursor shortcuts."
```

### Requirement: 缺失 cursor 的回退行为

当 cursor 对应 session 已不存在时，系统 MUST 在返回 payload 写明 warning，并回退到基于 `last_ingest_at` 的受限扫描，而不是静默重复导入。

#### Scenario: cursor 丢失

```text
Agent 调 ingest_sessions(project_name="demo", client="claude-code")
→ 返回: warning="ingest cursor sess-3 not found; falling back to sessions newer than last ingest timestamp."
```
