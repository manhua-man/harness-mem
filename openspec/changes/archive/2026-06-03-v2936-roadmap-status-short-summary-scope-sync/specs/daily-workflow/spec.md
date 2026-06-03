## MODIFIED Requirements

### Requirement: Roadmap-status short conclusion must match the page's full completed range

When `docs/roadmap-status.md` provides a short conclusion, that conclusion MUST
match the completed historical scope represented by the page's index and matrix
rather than starting from a later subset of versions.

#### Scenario: short conclusion includes the full completed range

- **WHEN** a reader opens the `## 短结论` section in `docs/roadmap-status.md`
- **THEN** it summarizes the completed line from `v1.5` through `v2.9`
- **AND** it does not frame the completed history as starting only at `v2.2`
