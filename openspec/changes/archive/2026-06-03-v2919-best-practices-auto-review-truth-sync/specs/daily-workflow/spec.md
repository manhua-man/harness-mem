## ADDED Requirements

### Requirement: Best-practices docs use the shared auto-review surface

The best-practices guide SHALL describe
`auto_review_candidates(project_name=<project>, apply=true)` as the default
low-risk distill review surface.

#### Scenario: best-practices distill guidance matches the shipped review path

- **WHEN** maintainers update `docs/best-practices.md`
- **THEN** the distill/review guidance names `auto_review_candidates(project_name=<project>, apply=true)` as the default review surface
- **AND** `list_candidates` is reserved for explicit review drilldown or user-correction flows rather than the normal distill path
