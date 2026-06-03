## MODIFIED Requirements

### Requirement: Docs index must describe the full current roadmap-status range

When `docs/README.md` summarizes `roadmap-status.md`, it MUST reflect the full
historical range that the current completion matrix covers rather than omitting
already-completed earlier lines.

#### Scenario: docs README includes v1.5 in roadmap-status range

- **WHEN** a reader opens `docs/README.md`
- **THEN** the `roadmap-status.md` index line says it covers `v1.5` through
  `v2.9`
- **AND** it does not say the range starts at `v1.6`
