## ADDED Requirements

### Requirement: Stale CLI surface guard tracks the current maintenance console

Focused stale-surface regression checks SHALL treat `config` and `integration`
as supported maintenance commands when scanning user-facing docs for removed
business CLI verbs.

#### Scenario: supported maintenance verbs are not treated as stale CLI

- **WHEN** user-facing docs mention `harness-mem config` or
  `harness-mem integration` as maintenance flows
- **THEN** the stale CLI surface guard does not report them as removed daily
  commands
- **AND** it continues to reject `harness-mem wake`, `harness-mem search`,
  `harness-mem timeline`, `harness-mem candidates`, and `harness-mem distill`
