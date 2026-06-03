## MODIFIED Requirements

### Requirement: Roadmap-status baseline summary must reflect the full current v2.9 release train

When `docs/roadmap-status.md` summarizes the current v2.9 release train at the
top of the file, the range MUST include the current shipped v2.9 version rather
than stopping at an older historical tail.

#### Scenario: baseline summary tail matches current version

- **WHEN** a reader opens `docs/roadmap-status.md`
- **THEN** the top baseline summary states `v2.9.0–v<current version>`
- **AND** it does not stop at an older tail such as `v2.9.27`
