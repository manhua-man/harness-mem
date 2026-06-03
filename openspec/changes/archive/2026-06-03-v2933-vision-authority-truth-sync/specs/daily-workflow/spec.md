## MODIFIED Requirements

### Requirement: Historical vision documents must not act as current roadmap authority

When a vision or reference document reflects historical planning for already
shipped version lines, it MUST make that historical role explicit and MUST
point readers to the current-truth status artifacts instead of implying that
the historical vision remains the active roadmap authority.

#### Scenario: vision and reference docs point to current truth

- **WHEN** a reader opens `docs/roadmap-vision-v16-v18.md`
- **THEN** the header states it is a historical vision archive
- **AND** it points to `docs/roadmap-status.md` and `CHANGELOG.md` for current
  version truth

#### Scenario: reference-projects no longer treats vision as current authority

- **WHEN** a reader opens `docs/reference-projects.md`
- **THEN** it says current version truth comes from `docs/roadmap-status.md` and
  `CHANGELOG.md`
- **AND** it may cite historical roadmap docs only as historical design context
