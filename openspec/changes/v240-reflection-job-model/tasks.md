## 1. Job schema and storage

- [ ] 1.1 Add canonical reflection job schema with `kind`, `phase`, `status`, `source`, refs, output ids, error, attempt count, lease, and audit timestamps.
- [ ] 1.2 Add SQLite index table plus JSON blob persistence for job records.
- [ ] 1.3 Add store helpers: save, get, list by project/status/kind, acquire lease, complete, mark retryable, mark failed, mark needs_distill.
- [ ] 1.4 Add schema/store round-trip tests and old/missing-field compatibility tests.

## 2. State machine and lease

- [ ] 2.1 Enforce allowed status transitions in one helper.
- [ ] 2.2 Implement lease acquire with expired-processing recovery to `retryable`.
- [ ] 2.3 Keep retry on the same `job_id` and increment `attempt_count`.
- [ ] 2.4 Tests: pending -> processing -> needs_distill, processing -> completed, processing -> retryable, expired lease -> retryable -> processing, retry budget -> failed.

## 3. Shared reflection business command

- [ ] 3.1 Add `reflection_once(...)` shared implementation under `harness_mem.commands` or service layer.
- [ ] 3.2 Resolve project consistently with existing project profile / active project behavior.
- [ ] 3.3 Implement idempotency key so duplicate triggers return the existing non-terminal job.
- [ ] 3.4 In `distill.mode=defer_to_agent`, finish at `needs_distill` without invoking an LLM.
- [ ] 3.5 Tests: duplicate trigger does not duplicate job/candidates; failed ingest writes retryable/failed job without blocking caller.

## 4. MCP job visibility

- [ ] 4.1 Add read-only MCP helper to list recent jobs by project/status/kind.
- [ ] 4.2 Add read-only MCP helper to fetch one job by id.
- [ ] 4.3 Add MCP smoke tests for list/read shape and empty-project behavior.

## 5. Doctor queue health

- [ ] 5.1 Extend doctor with queue counts by status.
- [ ] 5.2 Report oldest pending/retryable, active leases, failed latest error, and needs-distill next action.
- [ ] 5.3 Tests for empty queue, failed/retryable queue, and needs-distill queue.

## 6. Documentation

- [ ] 6.1 Update `docs/roadmap-v24.md` if implementation names differ from this change.
- [ ] 6.2 Update README / AGENTS only if new user or Agent runtime surface becomes visible.
- [ ] 6.3 Document that v2.4.0 still does not install hooks or enable automatic reflection by default.

## 7. Validation

- [ ] 7.1 `python -m pytest -q`
- [ ] 7.2 `python -m ruff check .`
- [ ] 7.3 `python -m mypy harness_mem`
- [ ] 7.4 `openspec validate --all --strict`
