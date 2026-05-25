# procedural-memory Specification

## Purpose
TBD - created by archiving change v180-procedural-skill-spike. Update Purpose after archive.
## Requirements
### Requirement: Procedural candidates

The structured store SHALL persist procedural candidates as reviewable workflow records with activation condition, ordered steps, termination condition, provenance, confidence, and review status.

#### Scenario: Procedural candidate round trip

- **GIVEN** a pending procedural candidate with ordered steps and provenance
- **WHEN** it is saved and loaded
- **THEN** the activation condition, steps, termination condition, provenance, confidence, and status are preserved

#### Scenario: Procedural fixtures load as candidates

- **GIVEN** a procedural fixture file
- **WHEN** it is loaded
- **THEN** the result is a procedural candidate rather than a confirmed skill or semantic memory entry

### Requirement: Confirmed skills

Confirming a procedural candidate SHALL create a confirmed Skill record with searchable workflow fields and usage counters.

#### Scenario: Confirm candidate to skill

- **GIVEN** a pending procedural candidate
- **WHEN** the candidate is confirmed
- **THEN** a Skill is created from the candidate workflow
- **AND** the candidate status becomes accepted
- **AND** no semantic memory entry is created by the confirmation

#### Scenario: Record skill result

- **GIVEN** a confirmed Skill
- **WHEN** a success or failure result is recorded
- **THEN** the usage counters and success rate are updated

### Requirement: Procedural review tools

The CLI and MCP server SHALL expose fallback tools for suggesting, confirming, rejecting, searching, and recording results for procedural skills.

#### Scenario: MCP procedural review flow

- **WHEN** an MCP client suggests a procedural skill candidate, confirms it, searches skills, and records a result
- **THEN** each tool returns success
- **AND** the confirmed skill is discoverable through skill search

#### Scenario: CLI procedural review flow

- **WHEN** a local operator uses the procedural skill CLI commands
- **THEN** the commands can create, confirm, reject, search, and record skill results as local fallback operations

### Requirement: Procedural skills stay outside default memory consumption

Procedural candidates and confirmed skills SHALL NOT mutate current semantic truth or enter default wake selection.

#### Scenario: Confirmed skill does not change wake

- **GIVEN** a confirmed Skill
- **WHEN** default wake context is built
- **THEN** the Skill is not included by the semantic wake selection path

#### Scenario: Procedural review preserves human gate

- **GIVEN** a procedural candidate
- **WHEN** it is suggested or loaded from fixtures
- **THEN** it remains pending until an explicit confirm or reject operation reviews it

