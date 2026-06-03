## MODIFIED Requirements

### Requirement: Historical roadmap status headers reflect shipped completion truth

When a historical roadmap line has already been fully shipped and documented in
current-truth status artifacts, its own roadmap status header MUST reflect
completion rather than preserving a now-stale planning label.

#### Scenario: roadmap-v22x header reflects shipped truth

- **WHEN** a reader opens `docs/roadmap-v22x.md`
- **THEN** the header states `v2.2.0 已完成`
- **AND** it does not say `规划中`
