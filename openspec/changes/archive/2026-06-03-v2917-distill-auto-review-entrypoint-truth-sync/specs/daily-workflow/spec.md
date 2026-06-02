## ADDED Requirements

### Requirement: Distill guidance uses the shared auto-review surface

User-facing `/hm:distill` guidance and repo-local skill instructions SHALL use
`auto_review_candidates(project_name=<project>, apply=true)` as the default
low-risk review surface.

#### Scenario: Distill docs and skill match the shipped auto-review path

- **WHEN** maintainers update `/hm:distill` command docs or repo-local skill guidance
- **THEN** they instruct the agent to call `auto_review_candidates(project_name=<project>, apply=true)`
- **AND** they do not teach manual `list_candidates` plus per-item `confirm_*` / `reject_*` as the default distill path
