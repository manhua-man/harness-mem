## MODIFIED Requirements

### Requirement: High-visibility status summaries reflect current shipped truth

High-visibility status summaries MUST reflect the current shipped release line
instead of stopping at an earlier completed slice when later release slices have
already been shipped and documented elsewhere in the same file.

#### Scenario: roadmap-status short conclusion mentions v2.9

- **WHEN** a reader reaches the short conclusion at the bottom of
  `docs/roadmap-status.md`
- **THEN** the summary states that the versioned roadmap line has progressed
  through `v2.9`
- **AND** it does not summarize the shipped line as only completed through
  `v2.8`
