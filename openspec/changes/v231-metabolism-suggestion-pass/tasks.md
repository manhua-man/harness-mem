## 1. Suggestion candidate schemas

- [ ] 1.1 Add `MergeSuggestionCandidate` schema in `harness_mem/core/schemas/merge_suggestion_candidate.py` with `target_a_id / target_a_kind / target_b_id / target_b_kind / proposed_content / similarity_score / evidence_signal_ids / status / metabolism_run_id`, plus `to_dict / from_dict`.
- [ ] 1.2 Add `StaleTruthSuggestionCandidate` schema in `harness_mem/core/schemas/stale_truth_suggestion_candidate.py` with `target_id / target_kind / last_surfaced_at / days_since_last_surface / evidence_signal_ids / status / metabolism_run_id`.
- [ ] 1.3 Extend `harness_mem/storage/sqlite_index.py` and `local_structured_store.py` with the two new candidate tables, mirroring `_COLUMN_MIGRATIONS` and existing candidate save/list/update_status helpers.
- [ ] 1.4 Update `StructuredStore` Protocol with the two new candidate read paths only (writers stay implementation-side, mirroring v2.3.0).

## 2. Suggestion pass selector

- [ ] 2.1 Add `harness_mem/commands/metabolism_pass.py` with `MetabolismPass` dataclass + pure async `select_metabolism_pass(...)` that wraps `select_replay_window` and returns `(window, merge_candidates, stale_candidates, supersede_candidates)` without persisting.
- [ ] 2.2 Implement `_propose_merges` using existing embedding / vector layer (`harness_mem.search`) over window targets in `repeat_search_hits` ∪ `historical_truths`; threshold default 0.85.
- [ ] 2.3 Implement `_propose_stale` from `historical_truths` + truths with no `wake_surfaced` / `search_hit` in `silence_days` (default 60 per design open question).
- [ ] 2.4 Implement `_propose_supersedes` over `historical_truths` for orphan supersede chains.
- [ ] 2.5 Tests: per-proposer fixture that exercises each algorithm independently; one integration test producing all three suggestion types from a seeded window.

## 3. Content-based token trim

- [ ] 3.1 Add `harness_mem/commands/token_estimator.py` with `count_tokens(text: str) -> int` using `tiktoken` (cl100k_base) when available, `len(text) // 4` fallback when not, mark fallback with a single module-level flag the caller can read.
- [ ] 3.2 Wire content-based estimate into `select_replay_window`: after dim selection, batch-fetch contents via `list_memory_entries(ids=...)`-style helpers, sum `count_tokens`. Keep `_DIM_TOKEN_WEIGHT` as third-tier fallback when neither tiktoken nor content read works.
- [ ] 3.3 Emit `tokenizer_fallback: char-heuristic` (or `tokenizer_fallback: dim-weight`) in `window.notes` when not using tiktoken so the audit trail is honest.
- [ ] 3.4 Tests: verify tiktoken path matches a hand-computed sum on a known text; verify char-heuristic fallback path triggers when tiktoken is unimported (monkeypatch); verify dim-weight fallback triggers when content fetch fails.

## 4. Weak-link signal application

- [ ] 4.1 Add helper `harness_mem/commands/signal_influence.py` exposing `pull_recent_signals(project_name, target_ids, since)` returning a per-target signal counter to drive ranking decisions.
- [ ] 4.2 Wake renderer: split confirmed rules into 3 groups (`recent_active` / `stable_quiet` / `experimental_skills`) using the helper. No truth mutation. Default on; off via `update_project_profile(weak_link_signals=False)`.
- [ ] 4.3 Search ranker: add `repeat_boost = 0.1` (module constant) to results whose `target_id` had ≥2 `search_hit` signals in the last 7 days. Boost is additive on `final_score`, applied after hybrid scoring.
- [ ] 4.4 Doctor: extend `harness-mem doctor` output with a "Weak-link signal influence" block reporting how many rules / skills / targets were re-ranked.
- [ ] 4.5 Tests: wake renders correct 3-group split; search boost moves repeated targets up exactly the boost amount; opt-out flag disables both; doctor block matches counts.

## 5. MCP tool: metabolism_run

- [ ] 5.1 Register `metabolism_run` tool spec in `harness_mem/mcp/tool_specs.py` (schema identical to `metabolism_preview`).
- [ ] 5.2 Implement `tool_metabolism_run` in `harness_mem/mcp/server.py`: calls `select_metabolism_pass`, persists `MetabolismRun(kind="metabolism", status="completed")` with `output_counts={"merge_suggestions": ..., "stale_suggestions": ..., "supersede_suggestions": ...}`, persists each candidate via the existing save_*_candidate path, returns payload + per-type counts.
- [ ] 5.3 Error path mirrors v2.3.0: persist `MetabolismRun(status="error")` + return `{success: False, error, doctor_pointer}` without raising.
- [ ] 5.4 MetabolismRun.from_dict back-compat: assert old `output_counts={"suggestions": 0}` still round-trips; new code reads missing per-type keys as 0.
- [ ] 5.5 MCP tool test: stub backend, two-call sequence; verify candidates persisted, run record kind="metabolism" / status="completed", and that `metabolism_preview` still works alongside.

## 6. Documentation

- [ ] 6.1 Update `tools/session-distill/SKILL.md` "Memory Metabolism preview" subsection to mention `metabolism_run` as the v2.3.1 sibling and clarify `metabolism_preview` stays read-only.
- [ ] 6.2 Update `AGENTS.md` runtime read-write section to mention `metabolism_run` + the three new candidate types + weak-link ranking influence (with opt-out).
- [ ] 6.3 README: still no v2.3.x marketing; update only the candidate-types reference list if any user-facing doc enumerates them. Note explicitly in design.md if we choose to skip.

## 7. Validation

- [ ] 7.1 `python -m pytest -q`
- [ ] 7.2 `python -m ruff check .`
- [ ] 7.3 `python -m mypy harness_mem`
- [ ] 7.4 `openspec validate --all --strict`
- [ ] 7.5 Loop harness sanity: `tests/loop_harness/` still passes after weak-link wake / search re-ranking changes (confirm v2.2 contract is not broken by ranking-only mutations).
- [ ] 7.6 Calibration sweep: with seeded fixture data, verify suggestion thresholds (similarity 0.85, silence 60d, repeat boost 0.1) produce expected counts. Document results in `tests/metabolism/calibration.md`.
