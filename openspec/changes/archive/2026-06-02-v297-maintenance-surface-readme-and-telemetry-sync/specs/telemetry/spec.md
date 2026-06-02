## MODIFIED Requirements

### Requirement: local event log

The system MUST write current maintenance-console commands and key MCP tool
calls to the local `events.log`, and the maintenance-console command set named
in the telemetry spec MUST stay aligned with the shipped CLI surface.

#### Scenario: telemetry collateral names the current maintenance console

- **WHEN** the telemetry spec enumerates CLI command coverage
- **THEN** it names `init`, `quickstart`, `qs`, `doctor`, `import`, `purge`,
  `maintenance`, `config`, and `integration`
- **AND** it does not present removed daily-memory CLI verbs as telemetry
  command coverage
