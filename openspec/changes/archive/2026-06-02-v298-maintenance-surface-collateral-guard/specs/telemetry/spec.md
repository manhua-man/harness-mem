## ADDED Requirements

### Requirement: Maintenance-surface collateral stays aligned

High-visibility collateral that summarizes the maintenance console SHALL keep
the current maintenance command set aligned across README, MCP spec, telemetry
spec, and the v2 user-test packet.

#### Scenario: collateral retains config and integration

- **WHEN** maintainers update README or spec collateral
- **THEN** those summaries keep `config` and `integration` in the maintenance
  surface
- **AND** regression tests fail if the collateral drifts back to an older
  command subset
