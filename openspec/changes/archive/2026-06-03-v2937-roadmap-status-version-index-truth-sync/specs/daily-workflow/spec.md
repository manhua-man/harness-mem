## MODIFIED Requirements

### Requirement: Roadmap-status version index must match the page's full historical scope

When `docs/roadmap-status.md` exposes a high-visibility version index, that
index MUST cover the same completed historical range that the rest of the page
claims rather than starting at a later subset of versions.

#### Scenario: version index covers v1.5.x through v2.9.x

- **WHEN** a reader opens the version-index section in `docs/roadmap-status.md`
- **THEN** the section label is `版本索引`
- **AND** the table includes entries from `v1.5.x` through `v2.9.x`
- **AND** it does not present the section as `后续 Roadmap`
