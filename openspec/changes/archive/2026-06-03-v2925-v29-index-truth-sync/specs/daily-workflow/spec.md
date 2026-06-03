## MODIFIED Requirements

### Requirement: Roadmap indexes describe shipped high-visibility workflow truth

High-visibility index documents that summarize shipped workflow/version lines
MUST describe those lines according to current shipped truth, not according to
an earlier seed slice if the line later expanded materially.

#### Scenario: v2.9 summaries reflect the shipped release train

- **WHEN** a reader checks `docs/README.md` or `docs/roadmap-status.md` to learn
  what `roadmap-v29.md` represents
- **THEN** the summary describes `v2.9` as a release train that started with
  PRD sync and then expanded into maintenance / triage / truth-sync slices
- **AND** it does not reduce the whole line to only `PRD sync candidate
  surface`
