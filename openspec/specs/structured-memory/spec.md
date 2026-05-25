# structured-memory Specification

## Purpose
TBD - created by archiving change v170-temporal-schema-current-history. Update Purpose after archive.
## Requirements
### Requirement: Truth entities carry temporal validity metadata

`MemoryEntry`, `RelationFact`, and `ConfirmedRule` SHALL persist temporal
validity metadata: `valid_from`, `valid_to`, `recorded_at`, `supersedes`, and
`superseded_by`.

#### Scenario: Legacy truth loads with current validity

- **GIVEN** a legacy structured truth blob without temporal fields
- **WHEN** the blob is loaded
- **THEN** `valid_from` and `recorded_at` are derived from the entity creation
  or confirmation timestamp
- **AND** `valid_to` is null
- **AND** supersede lists are empty

### Requirement: Structured reads default to current truth

Structured memory reads SHALL exclude historical truth by default.

#### Scenario: Historical memory is hidden by default

- **GIVEN** one memory entry with `valid_to` in the past
- **AND** one memory entry with no `valid_to`
- **WHEN** memory entries are listed or searched without history
- **THEN** only the current entry is returned

#### Scenario: Historical memory is returned explicitly

- **GIVEN** one memory entry with `valid_to` in the past
- **AND** one memory entry with no `valid_to`
- **WHEN** the caller requests history
- **THEN** both entries are returned

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

### Requirement: Relative Time Search Window

Search read paths SHALL support an internal time window filter derived from supported relative query phrases.

#### Scenario: Two months ago narrows results

- **WHEN** a query contains `two months ago`
- **THEN** the read path converts it to the corresponding prior calendar-month UTC window
- **AND** observation results outside that window are excluded
- **AND** structured truth outside that window is excluded by `recorded_at`, `valid_from`, or `created_at`

### Requirement: Bounded Relation Graph Trace

The system SHALL expose bounded relation path traversal over `RelationFact` records.

#### Scenario: Current two-hop trace

- **WHEN** a project has `A --depends_on-> B` and `B --depends_on-> C`
- **AND** a caller traces from `A` with `max_depth=2`
- **THEN** the response includes the one-hop and two-hop paths
- **AND** historical relation facts are excluded unless `include_history=true`

#### Scenario: Depth cap

- **WHEN** a caller requests `max_depth > 3`
- **THEN** the system rejects the request with an explicit error

