## MODIFIED Requirements

### Requirement: MCP is the daily runtime surface while CLI stays maintenance-only

MCP SHALL remain the daily runtime entrypoint for wake, search, distill,
timeline, and candidate review flows, while the terminal CLI remains limited to
the shipped maintenance command set.

#### Scenario: maintenance CLI set stays aligned in MCP collateral

- **WHEN** the MCP spec describes the remaining terminal console
- **THEN** it names the current maintenance surface as `init`, `quickstart`,
  `qs`, `doctor`, `import`, `purge`, `maintenance`, `config`, and `integration`
- **AND** it does not present removed daily-memory verbs as supported CLI flows
