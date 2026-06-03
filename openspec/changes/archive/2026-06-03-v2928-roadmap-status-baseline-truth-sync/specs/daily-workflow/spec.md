## MODIFIED Requirements

### Requirement: High-visibility baseline summaries reflect the shipped line

When a high-visibility baseline summary describes a shipped roadmap line, it
MUST reflect the current shipped cutoff instead of stopping at an earlier point
that was later superseded by additional shipped slices.

#### Scenario: roadmap-status baseline summary reflects v2.9.0-v2.9.27

- **WHEN** a reader checks the high-visibility baseline summary near the top of
  `docs/roadmap-status.md`
- **THEN** the summary treats `v2.9.0–v2.9.27` as a completed release train
- **AND** it does not stop its shipped summary at `v2.9.11`
