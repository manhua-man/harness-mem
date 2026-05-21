# Structured Memory Delta

## ADDED Requirements

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
