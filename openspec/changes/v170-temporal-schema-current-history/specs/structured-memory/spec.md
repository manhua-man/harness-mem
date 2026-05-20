## ADDED Requirements

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
