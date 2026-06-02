## ADDED Requirements

### Requirement: MCP distill examples use the shared auto-review surface

The MCP spec's distill closed-loop examples SHALL show the shipped
`auto_review_candidates` summary surface rather than manual per-item
confirm/reject choreography.

#### Scenario: MCP distill example calls auto_review_candidates

- **WHEN** maintainers update the MCP distill closed-loop example
- **THEN** the example calls `auto_review_candidates(project_name=<project>, apply=true)`
- **AND** the response summary includes canonical auto-review fields such as `auto_confirmed`, `auto_rejected`, and `applied_decisions`
