## ADDED Requirements

### Requirement: MCP supersede review tools

The MCP server SHALL expose `suggest_supersede`, `confirm_supersede`, and `reject_supersede`.

#### Scenario: Suggest supersede

- **WHEN** `suggest_supersede` is called with target and replacement truth ids
- **THEN** the server returns `success=true`
- **AND** a pending supersede candidate id

#### Scenario: Confirm supersede

- **GIVEN** a pending supersede candidate
- **WHEN** `confirm_supersede` is called
- **THEN** the server returns `success=true`
- **AND** the candidate status becomes `accepted`
- **AND** the target truth becomes historical

#### Scenario: Reject supersede

- **GIVEN** a pending supersede candidate
- **WHEN** `reject_supersede` is called
- **THEN** the server returns `success=true`
- **AND** the candidate status becomes `rejected`
- **AND** target and replacement truth remain current

### Requirement: MCP candidate listing includes supersede candidates

`list_candidates` SHALL include supersede candidates and return `supersede_count`.

#### Scenario: Mixed candidate list

- **GIVEN** one rule candidate, one memory entry candidate, one relation fact candidate, and one supersede candidate
- **WHEN** `list_candidates` is called
- **THEN** the response count is 4
- **AND** the supersede candidate has `confirm_tool=confirm_supersede`
