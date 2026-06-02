## ADDED Requirements

### Requirement: MCP exposes skill improvement detection and review

The MCP server SHALL expose a detector and review tools for low-success skill
improvement suggestions.

#### Scenario: Detector creates reviewable suggestions

- **GIVEN** a project has a low-success skill
- **WHEN** `detect_skill_improvements(project_name)` runs
- **THEN** the response reports created candidate ids
- **AND** `list_candidates(project_name, status="pending")` includes the new
  `skill_revision_suggestion`

#### Scenario: Confirm suggestion without rewrite

- **GIVEN** a pending `skill_revision_suggestion`
- **WHEN** `confirm_skill_revision(candidate_id)` runs
- **THEN** the candidate status becomes accepted
- **AND** the returned source skill payload remains unchanged

### Requirement: MCP exposes shared-skill deprecation review

The MCP server SHALL expose detection and review tools for retiring stale or
conflicting shared skills.

#### Scenario: Detector creates reviewable deprecation suggestion

- **GIVEN** a project owns a stale shared skill
- **WHEN** `detect_skill_deprecations(project_name)` runs
- **THEN** the response reports created candidate ids
- **AND** `list_candidates(project_name, status="pending")` includes the new
  `skill_deprecation_suggestion`

#### Scenario: Confirm deprecation retires skill

- **GIVEN** a pending `skill_deprecation_suggestion`
- **WHEN** `confirm_skill_deprecation(candidate_id)` runs
- **THEN** the candidate status becomes accepted
- **AND** the returned skill payload has `status="retired"`
