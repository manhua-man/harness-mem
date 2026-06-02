## ADDED Requirements

### Requirement: Repo-local doctor helper respects the maintenance-only CLI surface

Repo-local validation helpers SHALL invoke only supported maintenance CLI
commands and SHALL NOT call removed daily-memory subcommands.

#### Scenario: doctor helper succeeds without removed status call

- **WHEN** the operator runs `plugins/harness-mem/scripts/doctor.ps1`
- **THEN** the helper completes without invoking `harness-mem status`
- **AND** it does not emit `invalid choice: 'status'`

#### Scenario: Wake switch prints IDE wake guidance only

- **WHEN** the operator runs `plugins/harness-mem/scripts/doctor.ps1 -Wake`
- **THEN** the helper still runs the doctor maintenance path
- **AND** any extra wake guidance points at `/hm:wake` or equivalent IDE usage
- **AND** it does not reintroduce a CLI `status` or `wake` subcommand
