## ADDED Requirements

### Requirement: current docs describe one reflection job type

Current-truth roadmap and operator docs SHALL describe the v2.4 queue model as
one durable `ReflectionJob` type whose lifecycle may enter a `review` phase,
rather than as separate `ReflectionJob` and `ReviewJob` schema types.

#### Scenario: docs keep the shipped reflection-job model

- **WHEN** maintainers update current roadmap or operator docs for the v2.4 queue model
- **THEN** those docs describe a single `ReflectionJob` schema
- **AND** they may describe `review` as a phase of that job
- **AND** they do not claim a separate shipped `ReviewJob` schema exists
