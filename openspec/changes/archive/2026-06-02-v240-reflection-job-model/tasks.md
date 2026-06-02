## 1. Job schema and storage

- [x] 1.1 Add canonical reflection job schema with `kind`, `phase`, `status`, `source`, refs, output ids, error, attempt count, lease, and audit timestamps.
- [x] 1.2 Add SQLite index table plus JSON blob persistence for job records.
- [x] 1.3 Add store helpers: save, get, list by project/status/kind, acquire lease, complete, mark retryable, mark failed, mark needs_distill.
- [x] 1.4 Add schema/store round-trip tests and old/missing-field compatibility tests.

## 2. State machine and lease

- [x] 2.1 Enforce allowed status transitions in one helper.
- [x] 2.2 Implement lease acquire with expired-processing recovery to `retryable`.
- [x] 2.3 Keep retry on the same `job_id` and increment `attempt_count`.
- [x] 2.4 Tests: pending -> processing -> needs_distill, processing -> completed, processing -> retryable, expired lease -> retryable -> processing, retry budget -> failed.

## 3. Shared reflection business command

- [x] 3.1 Add `reflection_once(...)` shared implementation under `harness_mem.commands` or service layer.
- [x] 3.2 Resolve project consistently with existing project profile / active project behavior.
- [x] 3.3 Implement idempotency key so duplicate triggers return the existing non-terminal job.
- [x] 3.4 In `distill.mode=defer_to_agent`, finish at `needs_distill` without invoking an LLM.
- [x] 3.5 Tests: duplicate trigger does not duplicate job/candidates; failed ingest writes retryable/failed job without blocking caller.

## 4. MCP job visibility

- [x] 4.1 Add read-only MCP helper to list recent jobs by project/status/kind.
- [x] 4.2 Add read-only MCP helper to fetch one job by id.
- [x] 4.3 Add MCP smoke tests for list/read shape and empty-project behavior.

## 5. Doctor queue health

- [x] 5.1 Extend doctor with queue counts by status.
- [x] 5.2 Report oldest pending/retryable, active leases, failed latest error, and needs-distill next action.
- [x] 5.3 Tests for empty queue, failed/retryable queue, and needs-distill queue.

## 6. Documentation

- [x] 6.1 Update `docs/roadmap-v24.md` if implementation names differ from this change.
- [x] 6.2 Update README / AGENTS only if new user or Agent runtime surface becomes visible.
- [x] 6.3 Document that v2.4.0 still does not install hooks or enable automatic reflection by default.

## 7. Validation

- [x] 7.1 `python -m pytest -q`
- [x] 7.2 `python -m ruff check .`
- [x] 7.3 `python -m mypy harness_mem`
- [x] 7.4 `openspec validate --all --strict`
