## ADDED Requirements

### Requirement: Knowledge-base review is an explicit maintenance audit

The system SHALL treat `/hm:review-kb --next <n>` and its natural-language
equivalents as the formal user-facing audit entry for the session-distill
knowledge base.

#### Scenario: Review classifies entries and records baseline

- **WHEN** the operator runs `/hm:review-kb --next 20`
- **THEN** the system classifies knowledge entries into `stable`,
  `needs-review`, `stale`, or `superseded`
- **AND** it records the review timestamp, total entry count, and per-status
  summary for future reminder decisions

### Requirement: Knowledge-base prune is backup-first and status-confined

The system SHALL treat `/hm:prune-kb --statuses stale,superseded` and its
natural-language equivalents as explicit cleanup for stale/superseded
knowledge-base entries only.

#### Scenario: Prune writes backup before mutating knowledge base

- **GIVEN** at least one knowledge entry is classified as `stale` or `superseded`
- **WHEN** the operator runs `/hm:prune-kb --statuses stale,superseded`
- **THEN** the system writes a backup copy before cleanup
- **AND** it removes only the matching stale/superseded knowledge entries

#### Scenario: Prune does not mutate canonical truth

- **WHEN** knowledge-base prune runs
- **THEN** it does not confirm, reject, supersede, retire, or delete canonical
  rule/memory/fact/skill truth as a side effect
