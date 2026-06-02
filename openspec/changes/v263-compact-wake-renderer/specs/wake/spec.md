## ADDED Requirements

### Requirement: Opt-in compact wake renderer

The system SHALL support an explicit compact wake renderer that reads generated
wiki-bridge artifacts and returns a low-token, source-attributed summary.

#### Scenario: compact wake renders generated claims with source ids

- **GIVEN** a project has rebuilt wiki-bridge artifacts
- **WHEN** MCP `wake(project_name="demo", renderer="compact")` runs
- **THEN** the response includes compact claim, topic, entity, and source-id material
- **AND** the output labels itself as generated summary, not confirmed truth

### Requirement: Compact wake does not replace default wake truth

The compact renderer SHALL be opt-in and SHALL NOT change the default wake
renderer or promote generated wiki claims into confirmed truth surfaces.

#### Scenario: default wake remains unchanged

- **GIVEN** a project has generated wiki-bridge artifacts
- **WHEN** MCP `wake(project_name="demo")` runs without a renderer override
- **THEN** the existing default wake renderer is used
- **AND** generated wiki claims are not rendered as confirmed truth

#### Scenario: generated-only compact material is not searchable as truth

- **GIVEN** a token appears only in generated wiki bridge material
- **WHEN** default `search_memory` runs for that token
- **THEN** no confirmed memory entry or observation is returned for that generated-only token
