## ADDED Requirements

### Requirement: Status guidance uses the shipped triage surface

User-facing `/hm:status` guidance SHALL use
`get_project_status(project_name=<project>)` as the default project-memory
triage surface.

#### Scenario: Status docs do not teach manual low-level assembly

- **WHEN** maintainers update `/hm:status` command docs
- **THEN** they instruct the agent to call `get_project_status(project_name=<project>)`
- **AND** they summarize the returned triage fields directly
- **AND** they do not teach `get_project_profile` + `list_candidates` + `timeline` as the default status path
