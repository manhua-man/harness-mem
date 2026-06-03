## MODIFIED Requirements

### Requirement: Roadmap-status baseline summary must match the page's full completed scope

When `docs/roadmap-status.md` provides its top baseline summary, that summary
MUST reflect the same completed historical scope represented by the page's
other summary surfaces rather than starting at a later subset of versions.

#### Scenario: baseline summary includes v1.5 through v2.9

- **WHEN** a reader opens the top baseline summary in `docs/roadmap-status.md`
- **THEN** it summarizes the completed line from `v1.5` through `v2.9`
- **AND** it does not frame the completed baseline as starting only at `v2.5`
