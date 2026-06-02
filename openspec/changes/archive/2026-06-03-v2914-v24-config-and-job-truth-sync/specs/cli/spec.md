## ADDED Requirements

### Requirement: current docs describe the shipped config-loader scope

Current-truth operator and roadmap docs SHALL describe
`load_merged_config(project_root)` using the shipped recognized-key set and
MUST NOT claim that the loader resolves project naming through
`active_project.txt` or a config `project_name` field.

#### Scenario: docs keep the shipped merged-config scope

- **WHEN** maintainers update current operator or roadmap docs for the v2.4 config loader
- **THEN** those docs describe the recognized keys `triggers.after_agent`, `triggers.scheduler`, `distill.mode`, and `worker.mode`
- **AND** they do not claim `load_merged_config(project_root)` resolves `project_name`
- **AND** they do not mention `active_project.txt` as part of the merged-config loader contract
