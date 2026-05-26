## 1. Suggestion candidate schemas

- [x] 1.1 Add `MergeSuggestionCandidate` schema in `harness_mem/core/schemas/merge_suggestion_candidate.py` with `target_a_id / target_a_kind / target_b_id / target_b_kind / proposed_content / similarity_score / evidence_signal_ids / status / metabolism_run_id`, plus `to_dict / from_dict`.
- [x] 1.2 Add `StaleTruthSuggestionCandidate` schema in `harness_mem/core/schemas/stale_truth_suggestion_candidate.py` with `target_id / target_kind / last_surfaced_at / days_since_last_surface / evidence_signal_ids / status / metabolism_run_id`.
- [x] 1.3 Extend `harness_mem/storage/sqlite_index.py` and `local_structured_store.py` with the two new candidate tables, mirroring `_COLUMN_MIGRATIONS` and existing candidate save/list/update_status helpers.
- [x] 1.4 Update `StructuredStore` Protocol with the two new candidate read paths only (writers stay implementation-side, mirroring v2.3.0).

## 2. Suggestion pass selector

- [x] 2.1 Add `harness_mem/commands/metabolism_pass.py` with `MetabolismPass` dataclass + pure async `select_metabolism_pass(...)`. Wraps `select_replay_window` for merge / supersede (and the run record); stale is project-scoped with signal/field aggregation and a result cap (does NOT take the window as its scope — see design.md "Suggestion 选择算法").
- [x] 2.2 Implement `_propose_merges` over **entry-entry only**. Pool = `window.repeat_search_hits` targets that resolve to `memory_entry` ∪ current `MemoryEntry` rows (`valid_to is null`) whose `created_at` / `last_accessed_at` falls inside `window.time_range`, capped at `max_merge_pool_entries` (default = `budget.max_observations`). Historical truths and confirmed rules stay out of the pool (rule merges deferred to v2.3.2+ per design.md). Similarity reuses the existing embedding loader in a model-consistent way: read `vec_embeddings` only when `model_id == get_embedding_model_id()`; on miss or mismatch, encode `entry.content` in memory (no writes to `vec_embeddings` from the pass). Threshold 0.85, max 20 pairs per run, normalize each pair so `target_a_id < target_b_id`. Each candidate's `evidence_signal_ids` carries supporting `search_hit` signal ids when applicable.
- [x] 2.3 Implement `_propose_stale` as a **project-scoped scan** of current truth (`valid_to is null`) for `memory_entry` and `confirmed_rule` (`relation_fact` deferred). For each target, `last_surfaced_at = newer_of(v2.2 field, latest RetrievalSignal of type wake_surfaced/search_hit)`. Filter `days_since_last_surface >= silence_days` (default 60). Sort by `days_since` descending, cap at `max_stale_suggestions` (default 50), emit `stale_scan_truncated: <selected>/<pool>` in run notes when capped.
- [x] 2.4 `_propose_supersedes` returns empty list — v2.3.1 deferred. Auto-supersede needs a reliable signal that distinguishes "two truths to merge into one" from "A is replaced by B" — embedding similarity alone over-generates supersede candidates. Manual supersede via `tool_propose_supersede` (v1.7.1) remains the supported path. Add ONE contract test asserting the proposer returns `[]` and `MetabolismPass.supersede == []` even when `historical_truths` has entries; lock in the deferral so a future PR can't accidentally reactivate it without spec'ing the signal first.
- [x] 2.5 Tests: per-proposer fixture that exercises each algorithm independently; one integration test producing all three suggestion types from a seeded window.

## 3. Content-based token trim

- [x] 3.1 Add `harness_mem/commands/token_estimator.py` with `count_tokens(text: str) -> int` using `tiktoken` (cl100k_base) when available, `len(text) // 4` fallback when not, mark fallback with a single module-level flag the caller can read.
- [x] 3.2 Wire content-based estimate into `select_replay_window`: after dim selection, batch-fetch contents via `list_memory_entries(ids=...)`-style helpers, sum `count_tokens`. Keep `_DIM_TOKEN_WEIGHT` as third-tier fallback when neither tiktoken nor content read works.
- [x] 3.3 Emit `tokenizer_fallback: char-heuristic` (or `tokenizer_fallback: dim-weight`) in `window.notes` when not using tiktoken so the audit trail is honest. **Done as part of 3.2** — the selector emits `tokenizer_fallback: char-heuristic` before the `soft_token_budget` line whenever this run actually hit the fallback path (gated on `count_tokens_calls > 0` so a sticky module flag doesn't pollute fresh runs).
- [x] 3.4 Tests: verify tiktoken path matches a hand-computed sum on a known text; verify char-heuristic fallback path triggers when tiktoken is unimported (monkeypatch); verify dim-weight fallback triggers when content fetch fails.

## 4. Weak-link signal application

- [x] 4.1 Add helper `harness_mem/commands/signal_influence.py` exposing `pull_recent_signals(project_name, target_ids, since)` returning a per-target `TargetSignalSummary` (frozen dataclass with `wake_surfaced_count: int`, `search_hit_count: int`, `last_signal_at: datetime | None`). Internally runs **two** `query_retrieval_signals` calls (one per signal_type — the API is single-type) and merges per-target. Caller passes `since`; helper does not pick a default.
- [x] 4.2 Wake renderer: behind `ProjectProfile.weak_link_signals` (default `False`), wrap the existing `list_confirmed_rules` → `[:5]` path with one re-grouping step using `pull_recent_signals(..., since=now-30d)`. Emit `### Recent active` and `### Stable / quiet` markdown subheads under the existing `# Confirmed Rules` block; total budget stays at 5 rules (recent fills first). When the flag is `False`, output is bit-for-bit v2.2-identical. **Experimental skills group deferred to v2.3.2** (v2.2 wake doesn't surface skills today; adding a third group crosses the "weak-link tweak" line). Add `weak_link_signals: bool = False` to `ProjectProfile` schema; update `update_project_profile` MCP to accept it.
- [x] 4.3 Search ranker: behind the same `weak_link_signals` flag, post-process `read_api.search_memory` results by adding `REPEAT_BOOST_BASE = 0.1` to the `final_score` of any `memory_entry` result whose `search_hit_count >= 2` in the last 7 days (`REPEAT_BOOST_WINDOW_DAYS = 7`). Constants module-level, not parameterized. When off, ranking is v2.2-identical. One profile flag controls both 4.2 and 4.3 — single user surface.
- [x] 4.4 Doctor: extend `harness-mem doctor` output. When `weak_link_signals=False`: print one line `Weak-link signal influence: disabled (set weak_link_signals=true in project profile)`. When `True`: print 3 lines reporting (a) rules in `Stable / quiet`, (b) boosted search targets in last 7 days, (c) experimental skills line as `— (deferred to v2.3.2)`.
- [x] 4.5 Tests:
  - 4.1: helper aggregates two signal types into one `TargetSignalSummary` per target_id.
  - 4.2: `weak_link_signals=True` → wake output has both group subheads + total ≤5; `weak_link_signals=False` → wake output is bit-for-bit identical to v2.2 (golden assertion).
  - 4.3: `weak_link_signals=True` + 2 search_hits in last 7d → entry's `final_score` rises by `REPEAT_BOOST_BASE`; `False` → no change.
  - 4.4: doctor output has expected disabled / enabled block per profile state.

## 5. MCP tool: metabolism_run

- [x] 5.1 Register `metabolism_run` tool spec in `harness_mem/mcp/tool_specs.py` (schema identical to `metabolism_preview`).
- [x] 5.2 Implement `tool_metabolism_run` in `harness_mem/mcp/server.py`: calls `select_metabolism_pass`, persists `MetabolismRun(kind="metabolism", status="completed")` with `output_counts={"merge_suggestions": ..., "stale_suggestions": ..., "supersede_suggestions": ...}`, persists each candidate via the existing save_*_candidate path, returns payload + per-type counts.
- [x] 5.3 Error path mirrors v2.3.0: persist `MetabolismRun(status="error")` + return `{success: False, error, doctor_pointer}` without raising.
- [x] 5.4 MetabolismRun.from_dict back-compat: assert old `output_counts={"suggestions": 0}` still round-trips; new code reads missing per-type keys as 0.
- [x] 5.5 MCP tool test: stub backend, two-call sequence; verify candidates persisted, run record kind="metabolism" / status="completed", and that `metabolism_preview` still works alongside.

## 6. Documentation

- [x] 6.1 Update `tools/session-distill/SKILL.md` "Memory Metabolism preview" subsection to mention `metabolism_run` as the v2.3.1 sibling and clarify `metabolism_preview` stays read-only.
- [x] 6.2 Update `AGENTS.md` runtime read-write section to mention `metabolism_run` + the three new candidate types + weak-link ranking influence (with opt-out).
- [x] 6.3 README: still no v2.3.x marketing; update only the candidate-types reference list if any user-facing doc enumerates them. Note explicitly in design.md if we choose to skip.

## 7. Validation

- [x] 7.1 `python -m pytest -q`
- [x] 7.2 `python -m ruff check .`
- [x] 7.3 `python -m mypy harness_mem`
- [x] 7.4 `openspec validate --all --strict`
- [x] 7.5 Loop harness sanity: `tests/loop_harness/` still passes after weak-link wake / search re-ranking changes (confirm v2.2 contract is not broken by ranking-only mutations).
- [x] 7.6 Calibration sweep: with seeded fixture data, verify suggestion thresholds (similarity 0.85, silence 60d, repeat boost 0.1) produce expected counts. Document results in `tests/metabolism/calibration.md`.
