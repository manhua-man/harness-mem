# Design: v2.4.0 Reflection Job Model

## Decision

Use one canonical `MemoryJob` / `ReflectionJob` record with a `kind` field
instead of separate tables for reflection, review, and future queue work.
The first shipped kind is `reflection`; future kinds may include `review` or
`metabolism`, but v2.4.0 only implements the reflection path.

## Job Fields

Minimum persisted fields:

| Field | Meaning |
|---|---|
| `id` | Stable job id. |
| `project_name` | Resolved project. |
| `project_root` | Optional root used by host-triggered flows. |
| `kind` | `reflection` in v2.4.0. |
| `phase` | `ingest`, `prepare`, `distill`, `review`, `metabolism`, or `done`. |
| `status` | `pending`, `processing`, `completed`, `failed`, `retryable`, `needs_distill`. |
| `source` | `user`, `agent`, `ide_hook`, or `scheduler`. |
| `input_refs` | JSON refs such as session ids, archive paths, or trigger ids. |
| `output_candidate_ids` | Candidate ids produced by the job. |
| `error` | Short structured error string or null. |
| `attempt_count` | Number of processing attempts. |
| `lease_owner` | Host or process id for the active lease. |
| `lease_until` | Lease expiry timestamp. |
| `created_at` / `updated_at` / `completed_at` | Audit timestamps. |

`needs_distill` is a `status`, not a separate boolean. It means ingest/prepare
finished and the remaining step requires an LLM-capable Agent flow such as
`/hm:distill`.

## State Machine

Allowed transitions:

| From | To | Trigger |
|---|---|---|
| `pending` | `processing` | Worker or business command acquires lease. |
| `retryable` | `processing` | Retry acquires a new lease. |
| `processing` | `needs_distill` | Ingest/prepare succeeded with `distill.mode=defer_to_agent`. |
| `processing` | `completed` | All configured work finished. |
| `processing` | `failed` | Non-retryable error or retry budget exhausted. |
| `processing` | `retryable` | Retryable failure. |
| `processing` | `retryable` | Lease expired. |
| `needs_distill` | `processing` | Agent resumes distill/review work. |
| `needs_distill` | `completed` | Agent completes distill/review without separate processing lease. |

Terminal states are `completed` and `failed`. `needs_distill` is not terminal;
it is a visible handoff point.

## Lease Semantics

Lease acquisition is compare-and-set over job status and `lease_until`.
A job can be acquired when:

- status is `pending` or `retryable`; or
- status is `processing` and `lease_until < now`.

When an expired processing job is observed, the store marks it `retryable`
before or during acquisition. The retry keeps the same `job_id` and increments
`attempt_count`; it does not create a duplicate job.

## Idempotency

`reflection_once` must compute an idempotency key from:

- `project_name`;
- source and phase;
- selected session ids or archive paths;
- trigger id when supplied by a host integration.

If a non-terminal job with the same idempotency key already exists, the command
returns the existing job instead of writing duplicate observations or
candidates. Completed jobs are not retried unless a caller explicitly requests
a new trigger id.

## Shared Business Boundary

The shared implementation should live under `harness_mem.commands` or a service
module, for example:

```text
harness_mem.commands.reflection_jobs.reflection_once(...)
```

MCP handlers and future `python -m harness_mem.host ...` entries must call this
same implementation. `cli.py` must not implement reflection business logic.

v2.4.0 may add the business function and MCP tool without adding host hook
installers. Host entry and integration installers belong to later v2.4.x slices
unless needed as a thin smoke wrapper for the shared contract.

## Doctor Health

Doctor queue health should report:

- counts by status;
- oldest pending / retryable age;
- active processing jobs with lease expiry;
- failed jobs with latest error;
- needs-distill jobs with the next action.

Doctor output is diagnostic only. It must not mutate jobs unless a future
maintenance command explicitly asks for repair.
