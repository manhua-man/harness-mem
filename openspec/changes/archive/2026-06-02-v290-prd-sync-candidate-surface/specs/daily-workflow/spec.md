## ADDED Requirements

### Requirement: PRD sync is an explicit candidate-only maintenance entry

The system SHALL treat `/hm:prd-sync [--apply]` and its natural-language
equivalents as the formal user-facing entry for distilling bundled packets into
candidate PRD/roadmap sync notes.

#### Scenario: Dry-run previews candidate generation without writing files

- **GIVEN** bundled session-distill packets exist
- **WHEN** the operator runs `/hm:prd-sync`
- **THEN** the system reports matching bundled packets and detected topics
- **AND** it does not write `prd-distilled/*.md`

#### Scenario: Apply writes candidate markdown only

- **GIVEN** bundled packets contain PRD/roadmap-related topics
- **WHEN** the operator runs `/hm:prd-sync --apply`
- **THEN** the system writes a candidate markdown file under `prd-distilled/`
- **AND** it does not mutate canonical PRD docs, roadmap docs, knowledge-base
  truth, or confirmed runtime truth as a side effect
