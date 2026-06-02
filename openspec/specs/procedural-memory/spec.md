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

### Requirement: Confirmed skills have explicit scope

Confirmed procedural skills SHALL carry an explicit scope value of `project`,
`workspace`, or `global`.

#### Scenario: New confirmed skill defaults to project scope

- **GIVEN** an Agent confirms or records a skill through the existing project skill flow
- **WHEN** no reviewed shared-scope promotion is being applied
- **THEN** the stored skill has `scope="project"`
- **AND** default project skill search behavior remains unchanged

#### Scenario: Existing project skills migrate to project scope

- **GIVEN** a database has confirmed skills created before v2.7
- **WHEN** the schema migration runs
- **THEN** each existing skill is treated as `scope="project"`
- **AND** its project ownership and usage counters are preserved
- **AND** default wake and default project skill search outputs remain equivalent to the pre-migration behavior

### Requirement: Shared skills preserve provenance and portability notes

Shared skills SHALL record origin project, source ids, portability notes,
disabled assumptions, and any known project-specific caveats.

#### Scenario: Shared skill carries reusable context

- **GIVEN** a project skill is promoted to shared scope
- **WHEN** the shared skill is read or searched
- **THEN** the payload includes origin project, source ids, portability notes,
  disabled assumptions, and confirm history

### Requirement: Project skill promotion is review-gated

Project skills SHALL NOT become shared skills without a pending promotion
candidate being explicitly confirmed.

#### Scenario: Suggest shared promotion

- **GIVEN** a confirmed project skill
- **WHEN** an Agent suggests promoting it to `workspace` or `global`
- **THEN** the system creates a pending promotion candidate
- **AND** the original project skill remains unchanged

#### Scenario: Confirm shared promotion

- **GIVEN** a pending promotion candidate
- **WHEN** it is confirmed
- **THEN** a shared skill is created or updated with explicit provenance
- **AND** the promotion candidate status becomes accepted
- **AND** unrelated project skills are not mutated

#### Scenario: Reject shared promotion

- **GIVEN** a pending promotion candidate
- **WHEN** it is rejected
- **THEN** the candidate status becomes rejected
- **AND** no shared skill is created
- **AND** the source project skill remains unchanged

### Requirement: Shared skills stay out of default consumption

Shared skills SHALL NOT enter default wake or default project skill search.

#### Scenario: Default skill search remains project scoped

- **GIVEN** a project has no matching project skill
- **AND** a matching global shared skill exists
- **WHEN** default `search_skills(project_name, query)` runs
- **THEN** the global shared skill is not returned

#### Scenario: Explicit shared search can include shared skills

- **GIVEN** a matching global shared skill exists
- **WHEN** an Agent explicitly requests shared skill search
- **THEN** the result can include the global shared skill with scope and origin metadata

### Requirement: Project-specific skills take precedence over shared skills

Project-specific skills SHALL rank ahead of shared skills when both match a
task unless the caller explicitly asks for shared-only results.

#### Scenario: Project skill outranks shared skill

- **GIVEN** a project skill and a global shared skill both match the query
- **WHEN** explicit shared-inclusive search runs
- **THEN** the project skill is ranked before the shared skill
- **AND** the shared result displays portability warnings before activation

### Requirement: Low-success skills produce reviewed improvement suggestions

The system SHALL turn low-success skills into reviewed improvement suggestions
instead of rewriting confirmed skills directly.

#### Scenario: Detector creates pending suggestion for low-success skill

- **GIVEN** a confirmed skill has `success_rate < 0.5` or repeated zero-success use
- **WHEN** the detector runs
- **THEN** a pending `skill_revision_suggestion` candidate is created
- **AND** the confirmed skill remains unchanged

### Requirement: Revision suggestions preserve provenance

Revision suggestions SHALL carry current skill metrics and supporting recent
success/failure signal ids.

#### Scenario: Suggestion includes failure evidence

- **GIVEN** a low-success skill has recent `skill_result_failure` signals
- **WHEN** a revision suggestion is created
- **THEN** the candidate includes the current success/failure counters
- **AND** the recent supporting signal ids

### Requirement: Accepting a suggestion does not rewrite the skill

Accepting or rejecting a revision suggestion SHALL only change the candidate's
review status.

#### Scenario: Confirm suggestion without rewriting

- **GIVEN** a pending revision suggestion
- **WHEN** it is confirmed
- **THEN** the candidate status becomes accepted
- **AND** the source skill body remains unchanged

### Requirement: Duplicate pending revision suggestions are suppressed

The detector SHALL NOT create a second pending revision suggestion for the same
skill while an earlier pending suggestion already exists.

#### Scenario: Re-running detector does not duplicate pending review

- **GIVEN** a low-success skill already has a pending revision suggestion
- **WHEN** the detector runs again
- **THEN** no second pending revision suggestion is created for that skill

### Requirement: Shared-skill deprecation is review-gated

Stale or conflicting shared skills SHALL produce reviewed deprecation
suggestions rather than being retired automatically.

#### Scenario: Detect stale shared skill

- **GIVEN** a shared skill is inactive beyond the configured stale window
- **WHEN** the deprecation detector runs
- **THEN** a pending `skill_deprecation_suggestion` candidate is created
- **AND** the shared skill remains active until reviewed

#### Scenario: Confirm deprecation retires shared skill

- **GIVEN** a pending `skill_deprecation_suggestion`
- **WHEN** it is confirmed
- **THEN** the candidate status becomes accepted
- **AND** the shared skill status becomes `retired`
