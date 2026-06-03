## MODIFIED Requirements

### Requirement: Historical roadmap status lines reflect shipped completion truth

When a historical roadmap line has already been fully shipped and documented in
current-truth status artifacts, its own roadmap status header and slice status
notes MUST reflect completion rather than preserving a now-stale in-progress or
pending-release label.

#### Scenario: roadmap-v25 header and file-context section reflect shipped truth

- **WHEN** a reader opens `docs/roadmap-v25.md`
- **THEN** the header states `v2.5.0 / v2.5.1 / v2.5.2 已完成`
- **AND** the `v2.5.2` section does not say the slice is still pending release
