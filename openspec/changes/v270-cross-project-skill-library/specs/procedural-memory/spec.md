## ADDED Requirements

### Requirement: Confirmed skills have explicit scope

Confirmed procedural skills SHALL carry an explicit scope value of `project`,
`workspace`, or `global`.

#### Scenario: Existing project skills migrate to project scope

- **GIVEN** a database has confirmed skills created before v2.7
- **WHEN** the schema migration runs
- **THEN** each existing skill is treated as `scope="project"`
- **AND** its project ownership and usage counters are preserved

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
