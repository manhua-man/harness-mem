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

