## ADDED Requirements

### Requirement: MCP wake accepts a renderer selector

MCP `wake` SHALL accept an optional `renderer` parameter with values
`default` and `compact`.

#### Scenario: compact renderer selected explicitly

- **WHEN** a client calls `wake(renderer="compact")`
- **THEN** the server returns `renderer="compact"`
- **AND** the payload includes the rendered compact output
- **AND** the payload includes structured compact metadata for claims, topics,
  entities, and source ids

#### Scenario: invalid renderer is rejected

- **WHEN** a client calls `wake(renderer="unknown")`
- **THEN** the server returns `success=false`
- **AND** the error lists the valid renderer names
