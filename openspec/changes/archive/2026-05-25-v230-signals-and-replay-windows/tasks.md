## 1. Schema and storage

- [x] 1.1 Add `MetabolismRun` schema in `harness_mem/core/schemas/metabolism_run.py` with `id / project_name / kind / started_at / completed_at / status / input_window / selected_signal_ids / output_counts / duration_ms / notes`, plus `to_dict / from_dict` round-trip and conservative defaults for missing fields.
- [x] 1.2 Add `RetrievalSignal` schema in `harness_mem/core/schemas/retrieval_signal.py` with `id / project_name / signal_type / target_kind / target_id / recorded_at / value / context`.
- [x] 1.3 Extend `harness_mem/storage/sqlite_index.py` with `metabolism_runs` and `retrieval_signals` tables and their migrations, mirroring the existing `_COLUMN_MIGRATIONS` pattern.
- [x] 1.4 Add JSON blob writers + readers in `harness_mem/storage/local_structured_store.py` for both schemas; include `list_metabolism_runs(project_name, limit, kind=None)` and `query_retrieval_signals(project_name, signal_type=None, since=None, limit=...)`.
- [x] 1.5 Update `harness_mem/core/interfaces/structured_store.py` Protocol with the read-side methods only (writers stay implementation-side, similar to existing `touch_*` helpers).

## 2. Signal write paths

- [x] 2.1 Implement helper `record_retrieval_signal` in `harness_mem/commands/retrieval_signals.py` (new module) — single try/log-and-continue write path.
- [x] 2.2 Wire `wake_surfaced` signal write inside `touch_memory_entry` and `touch_confirmed_rule` callers (do not change the touch helpers themselves; emit at the wake renderer call site so we keep schemas decoupled from storage).
- [x] 2.3 Wire `search_hit` signal write at the `read_api.search_memory` user-visible result path, capped by the existing memory-entry result cap.
- [x] 2.4 Wire `confirmed` / `rejected` signal writes inside `auto_review_candidates`'s apply branch, one per `applied_decisions` row.
- [x] 2.5 Wire `skill_result_success` / `skill_result_failure` signal writes inside `record_skill_result`.
- [x] 2.6 Wire `supersede_completed` signal write inside `confirm_supersede`.
- [x] 2.7 Add a focused unit test per signal type asserting the row is written with the expected `target_kind` / `target_id`, and that the primary mutation still succeeds when the signal write is monkey-patched to raise.

## 3. Replay window selector

- [x] 3.1 Add `harness_mem/commands/replay_window.py` with `ReplayBudget` and `ReplayWindow` dataclasses plus the pure `select_replay_window(...)` function.
- [x] 3.2 Implement five dimensions: recent observations, stale pending candidates, historical truths (where `valid_to is not None`), low-success skills (`success_rate < 0.5` or `usage_count >= 5` with `success_count == 0`), and repeat search hits (signal aggregate by target).
- [x] 3.3 Enforce per-dimension budgets and the soft total-token cap; emit `truncated_within_<dim>: X/Y` notes.
  - Hard per-dimension cap: keep 3.2 truncation; populate `truncated_within_<dim>: <selected>/<pool>` notes where `<pool>` is the true total. For observations: when the `cap+1` probe says truncated, issue `LocalVerbatimStore.count_recent_observations(project_name, since)` (new helper) to get the real pool size and use it as both the note denominator and `total_seen`. Other four dimensions already aggregate the full pool in 3.2 — `total_seen` is already truthful, just emit the note when truncated.
  - repeat_search_hits special case: when `len(signals) == 10000` (the `query_retrieval_signals` cap is hit) emit a single `retrieval_signals_query_capped` note. Do NOT issue a follow-up COUNT.
  - Soft total-token cap: estimate by per-dimension fixed weights (id slot heuristic, no content read). Module constants in `replay_window.py`:
    - `_TOKENS_PER_OBSERVATION = 400`
    - `_TOKENS_PER_PENDING = 350`
    - `_TOKENS_PER_HISTORICAL = 300`
    - `_TOKENS_PER_LOW_SUCCESS_SKILL = 120`
    - `_TOKENS_PER_REPEAT_HIT = 40`
  - `estimate = sum(len(selected_ids[dim]) * weight[dim])`. If `estimate > budget.max_total_tokens`, trim tails in fixed cross-dimension order: `repeat_search_hits → low_success_skills → historical_truths → pending_candidates → observations`. Within a dimension, drop from the tail (matches each dim's existing sort: oldest obs / least-stale pending / oldest supersede / weakest repeat go first).
  - Notes:
    - `soft_token_budget: <estimate>/<max>` always when an estimate was computed (even if no trim happened).
    - `trimmed_for_token_budget: <dim1>,<dim2>` only when the soft cap forced a trim, listing the dimensions whose tails were cut.
  - Constraint: trimming for the soft cap MUST NOT touch `signal_ids` for repeats whose `target_id` survived the trim. If a repeat target_id is dropped, drop its supporting signal ids too.
- [x] 3.4 Tests: build fixtures that exercise each dimension cap individually + one integration test combining all five with realistic counts.
- [x] 3.5 Tests: empty project → empty `ReplayWindow` (selector smoke); preview `MetabolismRun` shape + `to_dict / from_dict` round-trip + store write/read (schema + store only, no selector persistence — selector stays pure read-only per Phase 3 boundary; selector ↔ store wiring is task 4.2 and the integration sequence is 4.4).

## 4. `metabolism_preview` MCP tool

- [x] 4.1 Register tool spec in `harness_mem/mcp/tool_specs.py` with the input schema described in `design.md`.
- [x] 4.2 Implement `tool_metabolism_preview` in `harness_mem/mcp/server.py`: project resolution → budget normalization → `select_replay_window` → persist `MetabolismRun` → return payload.
- [x] 4.3 Selector / persistence failure path writes `MetabolismRun(status="error")` and returns `{success: False, error, doctor_pointer}`; never raises.
- [x] 4.4 MCP tool test: stub backend, two-call sequence — first call returns a window, second call (after seeding more signals) returns a different window; verify run records are persisted in order.

## 5. Documentation alignment

- [x] 5.1 Add a "Memory Metabolism preview" subsection to `tools/session-distill/SKILL.md` clarifying that v2.3.0 only adds an MCP tool, no slash / natural-language entrypoint, and signals are background-only.
- [x] 5.2 Update `AGENTS.md` "AI 协作协议" / runtime read-write section to mention the new background signal layer and `metabolism_preview` tool, while explicitly stating no truth is changed and no daemon is added.
- [x] 5.3 No README change — v2.3.0 has no user-visible entrypoint; users still drive memory through the v2.2 contract. Document this absence in the design doc itself so a future doc audit doesn't re-add a misleading section.

## 6. Validation

- [x] 6.1 `python -m pytest -q`
- [x] 6.2 `python -m ruff check .`
- [x] 6.3 `python -m mypy harness_mem`
- [x] 6.4 `openspec validate --all --strict`
- [x] 6.5 Sanity sweep: `tests/loop_harness/` still passes (no signal write should break the v2.2 closed loop).
