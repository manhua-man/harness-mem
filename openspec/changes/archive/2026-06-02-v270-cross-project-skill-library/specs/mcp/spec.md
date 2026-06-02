## ADDED Requirements

### Requirement: MCP exposes reviewed shared-skill promotion

The MCP server SHALL expose tools or candidate flows for suggesting,
confirming, rejecting, and listing shared-skill promotion candidates.

#### Scenario: Promotion candidate appears in review surface

- **GIVEN** a project skill has a pending shared-scope promotion candidate
- **WHEN** `list_candidates(project_name, status="pending")` runs
- **THEN** the candidate appears with type `skill_promotion`
- **AND** it includes the requested scope, source skill id, origin project, and
  portability notes

### Requirement: MCP search_skills supports explicit shared search

MCP `search_skills` SHALL remain project-scoped by default and SHALL support an
explicit parameter for including shared skills.

#### Scenario: Default search excludes shared skills

- **WHEN** `search_skills(project_name="demo", query="release hygiene")` runs
- **THEN** only project-scoped skills for `demo` are returned

#### Scenario: Shared-inclusive search includes provenance

- **WHEN** `search_skills(project_name="demo", query="release hygiene", include_shared=true)` runs
- **THEN** matching workspace/global skills may be returned
- **AND** each shared skill result includes scope, origin project, source ids,
  portability notes, and disabled assumptions

#### Scenario: Invalid shared search mode is rejected

- **WHEN** a client requests an unsupported shared search mode
- **THEN** the server returns `success=false`
- **AND** the error lists the valid modes
