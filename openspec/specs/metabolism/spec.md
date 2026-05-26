# metabolism Specification

## Purpose
TBD - created by archiving change v230-signals-and-replay-windows. Update Purpose after archive.
## Requirements
### Requirement: Metabolism runs are recorded as auditable artifacts

Every metabolism-related run, including preview-only runs, SHALL persist a
`MetabolismRun` record so users and tests can replay which window drove a
suggestion pass.

#### Scenario: Preview run writes a metabolism record

- **WHEN** a caller invokes the `metabolism_preview` MCP tool for a project
- **THEN** the system creates a `MetabolismRun` record with
  `kind="preview"` and `status="preview"`
- **AND** the record's `input_window` describes the dimensions the
  selector returned
- **AND** the record's `selected_signal_ids` lists the
  `RetrievalSignal` rows that drove selection
- **AND** the record's `output_counts` is `{"suggestions": 0}`

#### Scenario: Selector failure produces an error record

- **GIVEN** the replay window selector raises during a preview run
- **WHEN** the system handles the failure
- **THEN** it persists a `MetabolismRun` with `status="error"` and a
  `notes` entry naming the failure
- **AND** it returns an error payload that points at `harness-mem doctor`
- **AND** it does not raise to the caller

### Requirement: Retrieval and review signals are recorded as a structured stream

The system SHALL persist a `RetrievalSignal` row for each user-observable
retrieval or review event so the metabolism selector can query a structured
event stream rather than reconstruct evidence from scattered counters.

#### Scenario: Wake-surfaced memory entry writes a signal

- **WHEN** the wake renderer surfaces a confirmed memory entry to a user
- **THEN** the system writes a `RetrievalSignal` with
  `signal_type="wake_surfaced"` and `target_kind="memory_entry"`
- **AND** the existing `usage_count` and `last_accessed_at` updates still
  succeed unchanged

#### Scenario: Auto-review applied decisions write signals

- **GIVEN** `auto_review_candidates(apply=True)` produced two decisions:
  one auto_confirm and one auto_reject
- **WHEN** the apply branch finishes
- **THEN** the system writes one `RetrievalSignal` with
  `signal_type="confirmed"` and one with `signal_type="rejected"`
- **AND** each signal references the candidate's id as `target_id`

#### Scenario: Signal write failure does not block the primary mutation

- **GIVEN** the signal table cannot be written (e.g. disk full)
- **WHEN** the wake renderer would emit a `wake_surfaced` signal
- **THEN** the wake output is still produced for the user
- **AND** the failure is logged but does not raise

### Requirement: Replay window selector is read-only and budget-bounded

The replay window selector SHALL only read from observations, candidates,
truths, skills, and signals; it SHALL NOT mutate any record. Each
selection SHALL respect per-dimension budgets and emit explicit
truncation notes when budgets are reached.

#### Scenario: Recent-observations dimension respects its cap

- **GIVEN** a project has 800 recent observations and the request uses
  the default `max_observations=200`
- **WHEN** the selector runs
- **THEN** the returned window contains at most 200 observation ids in
  the recent-observations dimension
- **AND** the window's `notes` includes
  `truncated_within_observations: 200/800`

#### Scenario: Empty project returns an empty window

- **GIVEN** a project has no observations, candidates, truths, skills,
  or signals
- **WHEN** the selector runs with default budgets
- **THEN** it returns a window whose dimensions are all empty
- **AND** the system still persists a `MetabolismRun(status="preview")`
  with zero counts

### Requirement: Metabolism preview does not affect daily user workflow

The `metabolism_preview` MCP tool SHALL be invoked only when explicitly
called. It SHALL NOT be wired into the wake, search, distill, or review
default paths.

#### Scenario: Daily distill flow does not invoke preview

- **WHEN** the user runs `/hm:distill`
- **THEN** the agent does not call `metabolism_preview`
- **AND** the canonical six-counter summary from the daily-workflow spec
  is unchanged

#### Scenario: Preview run does not modify truth

- **WHEN** `metabolism_preview` finishes successfully
- **THEN** no `MemoryEntry`, `RuleCandidate`, `ConfirmedRule`, `Skill`,
  `SupersedeCandidate`, or `ProceduralCandidate` row has its content,
  status, or `valid_to` changed by the preview
- **AND** the only persistence side effect of the preview is the new
  `MetabolismRun` row plus any signals that downstream callers (not the
  preview itself) emit

### Requirement: Metabolism pass produces three audited suggestion candidate types

The system SHALL be able to consume a v2.3.0 replay window and produce
three classes of suggestion candidates — merge, stale-truth, and
supersede — without mutating any confirmed truth. Each suggestion SHALL
trace back to the `MetabolismRun` that produced it and to the
`RetrievalSignal` rows that justified it.

#### Scenario: Metabolism run writes per-type suggestion counts

- **WHEN** the `metabolism_run` MCP tool finishes successfully on a
  project that has at least one merge candidate, one stale candidate,
  and one supersede candidate
- **THEN** the persisted `MetabolismRun` has `kind="metabolism"` and
  `status="completed"`
- **AND** its `output_counts` is
  `{"merge_suggestions": 1, "stale_suggestions": 1, "supersede_suggestions": 1}`
- **AND** each persisted candidate's `metabolism_run_id` matches that
  `MetabolismRun.id`

#### Scenario: Merge candidate is generated from similar truths in the window

- **GIVEN** the replay window contains two confirmed memory entries
  whose embeddings have similarity ≥ the configured threshold
  (default 0.85)
- **WHEN** the metabolism pass runs
- **THEN** the system creates one `MergeSuggestionCandidate` referencing
  both targets
- **AND** the candidate's `evidence_signal_ids` lists the
  `search_hit` / `wake_surfaced` signals that brought the two truths
  into the window
- **AND** the candidate's `status` is `pending` (no apply yet)

#### Scenario: Stale-truth candidate is generated from silent truths

- **GIVEN** a confirmed truth has had zero `wake_surfaced` and zero
  `search_hit` signals in the past 60 days (default `silence_days`)
- **WHEN** the metabolism pass runs
- **THEN** the system creates one `StaleTruthSuggestionCandidate` for
  that truth
- **AND** the candidate's `days_since_last_surface` is at least 60
- **AND** the candidate's `status` is `pending`

#### Scenario: Suggestion apply still respects review gates

- **GIVEN** an `auto_review_candidates(apply=True)` run encounters a
  fresh `MergeSuggestionCandidate` whose similarity score is below the
  auto-confirm threshold
- **WHEN** the auto-review decides
- **THEN** the candidate stays `pending` for the human review path
- **AND** no truth is mutated by the auto-review pass

### Requirement: Replay window token estimate uses content tokens with a documented fallback

The replay window selector SHALL estimate selected content using actual
token counts when a tokenizer is available, fall back to a
character-based heuristic when not, and disclose which path was used in
the window's audit notes.

#### Scenario: tiktoken-backed estimate is reflected in the audit note

- **GIVEN** `tiktoken` is importable and the `cl100k_base` encoding is
  available
- **WHEN** the selector computes the soft-token-budget estimate
- **THEN** the estimate is the sum of `tiktoken` token counts over the
  selected content
- **AND** the window's notes contain a `soft_token_budget: <est>/<max>`
  line whose `<est>` matches the tiktoken total
- **AND** the window's notes do NOT contain a `tokenizer_fallback:` line

#### Scenario: Fallback heuristic discloses itself

- **GIVEN** `tiktoken` cannot be imported in the current environment
- **WHEN** the selector computes the soft-token-budget estimate
- **THEN** the estimate is computed as `len(text) // 4` per content
- **AND** the window's notes include
  `tokenizer_fallback: char-heuristic`
- **AND** the soft-token-budget note still appears with the heuristic
  estimate as `<est>`

### Requirement: Weak-link signals influence wake and search ordering without mutating truth

The wake and search renderers SHALL re-rank confirmed truths and skills
using `RetrievalSignal` history. Re-ranking SHALL never delete records,
modify `valid_to`, change `confidence`, or alter `status`.

#### Scenario: Wake places quiet rules in a 'stable / quiet' group

- **GIVEN** a confirmed rule has had zero `wake_surfaced` and zero
  `search_hit` signals in the past 30 days
- **AND** the project profile has `weak_link_signals=True` (default)
- **WHEN** the wake renderer runs
- **THEN** the rule appears in the `stable_quiet` group beneath the
  `recent_active` group
- **AND** the rule's row in the database has not been changed
- **AND** opting out via `update_project_profile(weak_link_signals=False)`
  causes the rule to render in its v2.2 position on the next wake

#### Scenario: Search boosts repeated targets within the configured window

- **GIVEN** a memory entry has at least 2 `search_hit` signals in the
  past 7 days
- **WHEN** a `search_memory` query returns that entry as one of the
  results
- **THEN** the entry's `final_score` is its base hybrid score plus
  `REPEAT_BOOST_BASE` (default 0.1)
- **AND** an entry that has zero recent `search_hit` signals is scored
  with no boost

#### Scenario: Doctor reports weak-link influence counts

- **WHEN** `harness-mem doctor` runs against a project with at least
  one quieted rule, one experimental skill, and one boosted target in
  the last 7 days
- **THEN** the doctor output includes a "Weak-link signal influence"
  block reporting the counts
- **AND** the block is absent (or zeroed) when `weak_link_signals=False`

### Requirement: MetabolismRun output_counts remains backward compatible

`MetabolismRun.from_dict` SHALL deserialize records produced by v2.3.0
(whose `output_counts` is `{"suggestions": 0}`) without raising and
without losing the explicit zero. New code reading old records SHALL
default any missing per-type count to 0.

#### Scenario: Old preview record round-trips through new from_dict

- **GIVEN** a v2.3.0 `MetabolismRun` JSON blob with
  `output_counts={"suggestions": 0}`
- **WHEN** v2.3.1 code calls `MetabolismRun.from_dict(blob)`
- **THEN** the resulting object has `output_counts={"suggestions": 0}`
- **AND** v2.3.1 helpers that read `merge_suggestions /
  stale_suggestions / supersede_suggestions` treat all three as 0 for
  this record

#### Scenario: New metabolism record uses per-type counts

- **GIVEN** a v2.3.1 metabolism run that produced 2 merge, 1 stale, and
  0 supersede suggestions
- **WHEN** the run is persisted and reloaded
- **THEN** the reloaded record's `output_counts` is
  `{"merge_suggestions": 2, "stale_suggestions": 1, "supersede_suggestions": 0}`
- **AND** the legacy `"suggestions"` key is absent from new records

