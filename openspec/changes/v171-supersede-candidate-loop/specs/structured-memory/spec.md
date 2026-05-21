## ADDED Requirements

### Requirement: Supersede candidates

The structured store SHALL persist supersede candidates with `project_name`, `target_type`, `target_id`, `replacement_type`, `replacement_id`, `reason`, `evidence`, `confidence`, `status`, `source`, `created_at`, `reviewed_at`, and `reviewer_id`.

#### Scenario: Supersede candidate round trip

- **GIVEN** a pending supersede candidate
- **WHEN** it is saved and loaded
- **THEN** all target, replacement, reason, evidence, status, and review fields are preserved

### Requirement: Supersede confirmation marks old truth historical

Confirming a pending supersede candidate SHALL mark the target truth historical and link it to the replacement truth.

#### Scenario: Confirmed rule replacement

- **GIVEN** a current confirmed rule `rule-old`
- **AND** a current confirmed rule `rule-new`
- **AND** a pending supersede candidate from `rule-old` to `rule-new`
- **WHEN** the candidate is confirmed
- **THEN** `rule-old.valid_to` is set
- **AND** `rule-old.superseded_by` contains `rule-new`
- **AND** `rule-new.supersedes` contains `rule-old`
- **AND** the supersede candidate status is `accepted`

### Requirement: Supersede rejection preserves truth

Rejecting a pending supersede candidate SHALL NOT mutate the target or replacement truth records.

#### Scenario: Rejected replacement

- **GIVEN** a pending supersede candidate from `rule-old` to `rule-new`
- **WHEN** the candidate is rejected
- **THEN** `rule-old.valid_to` remains null
- **AND** `rule-new.supersedes` remains unchanged
- **AND** the supersede candidate status is `rejected`
