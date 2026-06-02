## ADDED Requirements

### Requirement: MCP status examples show the shipped triage fields

The MCP spec's status examples SHALL show the shipped `get_project_status`
triage fields directly rather than a partial payload that omits next-step
guidance.

#### Scenario: MCP status example includes phase and slash hint

- **WHEN** maintainers update the MCP status example
- **THEN** the example response includes `phase`, `suggested_slash`, and `reason`
- **AND** repair hints appear directly when the example project still has pending review work
