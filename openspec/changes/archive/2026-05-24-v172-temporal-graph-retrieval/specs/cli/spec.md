# CLI Delta

## ADDED Requirements

### Requirement: Trace Relations Command

The CLI SHALL provide `harness-mem trace-relations` for bounded relation graph inspection.

#### Scenario: Two-hop path output

- **WHEN** the user runs `harness-mem trace-relations Parser --relation-type feeds --max-depth 2`
- **THEN** the output includes bounded relation paths and edge evidence

### Requirement: Search Time Window Disclosure

The CLI search command SHALL disclose parsed relative time windows.

#### Scenario: Parsed time phrase

- **WHEN** the query includes a supported phrase such as `last week`
- **THEN** the output includes the applied UTC time window
