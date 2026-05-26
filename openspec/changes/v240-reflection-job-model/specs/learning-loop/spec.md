## ADDED Requirements

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

### Requirement: Reflection job visibility is available to Agents

The system SHALL expose read-only MCP helpers for Agents to list recent jobs and
fetch a single job by id. These helpers SHALL NOT perform job repair or retry as
a side effect.

#### Scenario: Agent lists recent jobs

- **WHEN** an Agent asks for recent jobs for a project
- **THEN** the response includes each job's id, kind, phase, status, source,
  attempt count, updated time, and short error summary when present
- **AND** the helper supports filtering by status and kind

#### Scenario: Agent reads one job

- **WHEN** an Agent asks for a job by id
- **THEN** the response includes the full persisted job payload
- **AND** unknown ids return a structured not-found response rather than raising

### Requirement: Doctor reports reflection queue health

The doctor command SHALL report reflection queue health without mutating jobs.
The report SHALL make stuck, failed, retryable, and needs-distill jobs visible
without blocking the current coding task.

#### Scenario: Doctor reports queue counts and next actions

- **WHEN** doctor runs for a project
- **THEN** it reports counts for `pending`, `processing`, `retryable`, `failed`,
  and `needs_distill` jobs
- **AND** it reports the oldest pending or retryable age when present
- **AND** it reports active processing leases and failed job errors when present
- **AND** it names `/hm:distill` or the equivalent MCP Agent flow as the next
  action for `needs_distill` jobs
