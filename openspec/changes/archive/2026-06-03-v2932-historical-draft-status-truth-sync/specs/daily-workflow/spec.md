## MODIFIED Requirements

### Requirement: Historical design drafts must not masquerade as active roadmap status

When a document under `docs/roadmap/` is retained as a historical design draft
after the related version line has already shipped, its status header MUST make
that archival role explicit instead of exposing a bare `draft` label.

#### Scenario: dream absorption draft is marked as a historical archive

- **WHEN** a reader opens `docs/roadmap/dream-mechanism-absorption-v151-v17.md`
- **THEN** the header states that the file is a historical design draft archive
- **AND** it points to `docs/roadmap-status.md` and `CHANGELOG.md` for current
  version truth
- **AND** it does not use a bare `> 状态：draft` line
