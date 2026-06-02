## ADDED Requirements

### Requirement: README distill workflow diagram matches the shipped review path

The README's distill workflow diagram SHALL describe
`auto_review_candidates(apply=true)` as the review step for the default
distill path.

#### Scenario: README does not teach the older manual review chain

- **WHEN** maintainers update the README distill workflow diagram
- **THEN** it points to `auto_review_candidates(apply=true)`
- **AND** it does not teach `list_candidates -> auto-review / confirm / reject` as the default path
