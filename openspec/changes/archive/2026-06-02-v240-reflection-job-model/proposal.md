## Why

v2.3.1 can record signals, replay windows, and metabolism suggestions, but heavier
memory work still lacks a durable job lifecycle. If a host hook, scheduler, or
Agent workflow starts reflection and then crashes, users cannot reliably tell
whether the run completed, needs distill, can retry, or failed permanently.

v2.4.0 adds the smallest safe foundation for host-triggered reflection: explicit
job records, leases, provenance, idempotent trigger behavior, MCP job visibility,
and doctor queue health. It does not install IDE hooks yet and does not make
reflection automatic by default.

## What Changes

- Add a durable job model for reflection/review work, implemented as one
  canonical job record with `kind` / `phase` rather than separate ad hoc queues.
- Define the job state machine, including lease expiry from `processing` to
  `retryable`.
- Add a shared `reflection_once` business command boundary that future MCP and
  `python -m` host entries will call.
- Expose read-only MCP helpers for listing and reading recent jobs.
- Extend doctor with queue health for pending, processing, retryable, failed,
  and needs-distill jobs.
- Preserve candidate-before-truth: reflection jobs may write observations,
  prepared distill artifacts, and candidates, but MUST NOT silently confirm or
  mutate confirmed truth.

## Impact

- No default daemon, no default IDE hook, and no turn-end auto-learning.
- CLI remains a maintenance surface. v2.4.0 does not add a user-facing
  `harness-mem reflection` command.
- Job storage becomes a new persistence surface and must be backward compatible
  with existing local data directories.
- Later v2.4.x slices can add config and integration installers on top of this
  job model without redefining lifecycle semantics.
