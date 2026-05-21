# CLI Delta

## ADDED Requirements

### Requirement: Raw Evidence Search Command

The CLI SHALL expose exact evidence search as `harness-mem search-raw`.

#### Scenario: Regex output

- **WHEN** a user runs `harness-mem search-raw --regex "ERROR-\d+" -p demo`
- **THEN** output includes observation id, session id, snippet, span, and candidate count

### Requirement: Rebuild Verbatim Index

The CLI SHALL expose `harness-mem maintenance rebuild-verbatim-index`.

#### Scenario: Rebuild old store

- **WHEN** a project has observations but missing exact postings
- **THEN** the rebuild command restores regex search candidates
