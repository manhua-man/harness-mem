# learning-loop Specification

## Purpose

定义"correct → suggest_rule → 候选层 → confirm/reject → wake 命中"这条 learning loop 的 MCP 工具契约。学习闭环的用户入口是 IDE 命令 / Skill / Agent 自然语言；spec scenario 描述的是 MCP 工具间的协作语义。

## Requirements

### Requirement: suggest_rule

系统 MUST 支持 `suggest_rule`，让 Agent 在显式 distill 流程或用户明确要求记录规则时把候选写入 pending 层。

#### Scenario: 建议规则

```json
MCP -> suggest_rule({
  "project_name": "demo",
  "pattern": "User prefers dark mode for code reviews",
  "trigger": "When discussing UI defaults",
  "session_id": "sess_123"
})
Response: { "success": true, "rule_id": "rule_456", "status": "pending" }
```

### Requirement: confirm/reject/suggest 完整闭环

系统 MUST 支持 `confirm_rule` + `reject_rule` + `suggest_rule` 形成完整闭环。

#### Scenario: 完整闭环

```text
1. Agent 调 suggest_rule(project_name=..., pattern=..., trigger=...)
   -> {rule_id: "rule_001", status: "pending"}

2. Agent / auto-review 决定确认
   MCP -> confirm_rule({rule_id: "rule_001"})
   -> {success: true, confirmed_rule_id: "rule_001"}

   或拒绝
   MCP -> reject_rule({rule_id: "rule_001", reason: "duplicate"})
   -> {success: true}
```

### Requirement: scope=project|all

`search_memory` / `search_skills` MUST 支持 `scope=project|all`，让 Agent 跨项目检索 confirmed 记忆。`project_name` 仅在 `scope=project` 时必填。

#### Scenario: 跨项目检索 learning

```json
MCP -> search_memory({
  "query": "dark mode preference",
  "scope": "all"
})
Response: {
  "results": [...],
  "project_count": 3,
  "projects": ["project-a", "project-b", "project-c"]
}
```

### Requirement: 同聊天流完成

Agent SHOULD 让 correct -> review -> confirm/reject 尽量在同一聊天流里完成，不把候选审核工作甩给独立 review 入口。学习闭环命中后，下次 `wake` MUST 在 wake-up 输出里反映该规则。

#### Scenario: 同一会话完成闭环

```text
User: "我们项目的事实是 X，刚才 Agent 的 Y 是错的，记一条 X 的规则。"
Agent:
  1. suggest_rule(project_name=..., pattern="X", trigger="when ...")
  2. confirm_rule(rule_id=...)
Agent 回复:
  Confirmed rule rule_001. Run /hm:wake (or 让我用 harness-mem 唤醒) 即可在新对话看到这条规则。
```

### Requirement: Reflection jobs have a durable lifecycle

The system SHALL persist host-triggered and Agent-triggered reflection work as
durable job records before doing heavyweight memory work. A reflection job SHALL
record its project, source, phase, status, inputs, outputs, lease, attempts, and
timestamps so failed or interrupted work can be inspected and retried.

#### Scenario: Reflection trigger creates a pending job

- **WHEN** a caller invokes the shared reflection business command for a project
- **THEN** the system persists a job with `kind="reflection"`
- **AND** its `source` is one of `user`, `agent`, `ide_hook`, or `scheduler`
- **AND** its initial `status` is `pending` or `processing`
- **AND** its `phase` reflects the first configured step, such as `ingest`
- **AND** no confirmed truth is created, confirmed, deleted, or superseded merely
  because the job was created

#### Scenario: Deferred distill becomes visible

- **GIVEN** reflection ingest and prepare work completed successfully
- **AND** the effective distill mode is `defer_to_agent`
- **WHEN** the job finishes the prepare phase
- **THEN** the job status becomes `needs_distill`
- **AND** the job records the prepared inputs needed by an Agent distill flow
- **AND** the caller receives a payload naming the next action

### Requirement: Reflection jobs use leases for interruption safety

The system SHALL use a processing lease so interrupted jobs can be detected and
retried without creating duplicate jobs or silently blocking the queue.

#### Scenario: Processing lease expires into retryable

- **GIVEN** a job has `status="processing"` and `lease_until` is earlier than now
- **WHEN** the queue is listed, acquired, or checked by doctor
- **THEN** the system treats the job as `retryable`
- **AND** a later acquire may move the same job id back to `processing`
- **AND** the retry increments `attempt_count`

#### Scenario: Completed and failed jobs are terminal

- **GIVEN** a job has `status="completed"` or `status="failed"`
- **WHEN** a worker or business command tries to acquire it
- **THEN** acquisition fails without changing the job

### Requirement: Reflection triggers are idempotent

The reflection business command SHALL avoid duplicate work for the same trigger
inputs by using an idempotency key derived from project, source, phase, selected
sessions or archive paths, and any host-supplied trigger id.

#### Scenario: Duplicate trigger returns existing job

- **GIVEN** a non-terminal reflection job already exists for the same
  idempotency key
- **WHEN** the same trigger is received again
- **THEN** the command returns the existing job id
- **AND** it does not write duplicate observations, prepared artifacts, or
  candidates

### Requirement: Reflection resolves project roots before cwd fallback

The system SHALL resolve a missing `project_root` for the shared reflection
business command by first trying the commands-layer project-root resolver for
the requested `project_name` and only then falling back to the current working
directory when no known project root can be found.

#### Scenario: known project root wins over caller cwd

- **GIVEN** `reflection_once(...)` is called without `project_root`
- **AND** the commands-layer resolver can locate a known root for that
  `project_name`
- **WHEN** the job is created
- **THEN** the persisted `project_root` is that known project root
- **AND** the command does not silently substitute the caller's cwd instead

#### Scenario: cwd remains the last fallback

- **GIVEN** `reflection_once(...)` is called without `project_root`
- **AND** the commands-layer resolver cannot locate any root for that
  `project_name`
- **WHEN** the job is created
- **THEN** the persisted `project_root` falls back to the current working
  directory
