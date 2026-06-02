## ADDED Requirements

### Requirement: Session-distill skill guidance uses the shipped review surface

The repo-local `session-distill` skill SHALL describe
`auto_review_candidates(project_name=<project>, apply=true)` as the default
low-risk review surface.

#### Scenario: Session-distill skill does not teach the older manual review chain

- **WHEN** maintainers update `tools/session-distill/SKILL.md`
- **THEN** the default distill review step names `auto_review_candidates(project_name=<project>, apply=true)`
- **AND** `list_candidates` plus `confirm_*` / `reject_*` are reserved for explicit drilldown or repair flows rather than the normal distill path
