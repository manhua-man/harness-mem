## ADDED Requirements

### Requirement: AGENTS distill guidance uses the shipped review surface

The repo root `AGENTS.md` SHALL describe
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface.

#### Scenario: AGENTS does not teach the older manual review mainline

- **WHEN** maintainers update `AGENTS.md`
- **THEN** the distill mainline points to `auto_review_candidates(project_name=<project>, apply=true)`
- **AND** `list_candidates` plus `confirm_*` / `reject_*` are reserved for repair or drilldown flows rather than the normal distill path
