## MODIFIED Requirements

### Requirement: Roadmap headers reflect the shipped line, not only the seed slice

When a roadmap line later expands materially beyond its initial seed slice, the
top-level roadmap header and goal summary MUST describe the shipped line truth
instead of continuing to summarize the whole line only by that first slice.

#### Scenario: roadmap-v29 header reflects the release train

- **WHEN** a reader opens `docs/roadmap-v29.md`
- **THEN** the top-level theme describes `v2.9` as having started with PRD sync
  and then expanded into a maintenance / triage / truth-sync release train
- **AND** it does not summarize the whole line only as `PRD Sync Candidate
  Surface`
