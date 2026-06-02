## ADDED Requirements

### Requirement: Reflection resolves project roots before cwd fallback

The system SHALL resolve a missing `project_root` for the shared reflection
business command by first trying the commands-layer project-root resolver for
the requested `project_name` and only then falling back to the current working
directory when no known project root can be found.

#### Scenario: known project root wins over caller cwd

- **GIVEN** `reflection_once(...)` is called without `project_root`
- **AND** the commands-layer resolver can locate a known root for that
  `project_name`
- **WHEN** the job is created
- **THEN** the persisted `project_root` is that known project root
- **AND** the command does not silently substitute the caller's cwd instead

#### Scenario: cwd remains the last fallback

- **GIVEN** `reflection_once(...)` is called without `project_root`
- **AND** the commands-layer resolver cannot locate any root for that
  `project_name`
- **WHEN** the job is created
- **THEN** the persisted `project_root` falls back to the current working
  directory
