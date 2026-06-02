## ADDED Requirements

### Requirement: Historical roadmap distill contract matches the shipped review surface

Historical roadmap writeups that still describe the active distill closed loop
SHALL point to `auto_review_candidates(apply=true)` rather than the older
manual-review chain.

#### Scenario: v2.2 roadmap does not teach the older distill mainline

- **WHEN** maintainers update `docs/roadmap-v22x.md`
- **THEN** its distill closed-loop wording points to `auto_review_candidates(apply=true)`
- **AND** it does not teach `suggest_* -> list_candidates -> auto-review/confirm/reject` as the active contract
