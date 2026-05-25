# MCP Delta

## ADDED Requirements

### Requirement: Trace Relations Tool

The MCP server SHALL expose a `trace_relations` tool.

#### Scenario: Bounded trace payload

- **WHEN** a client calls `trace_relations`
- **THEN** the payload includes serialized paths with entities, depth, confidence, and edge evidence

### Requirement: Search Memory Time Window Metadata

The MCP `search_memory` tool SHALL return parsed time-window metadata when a supported phrase is present.

#### Scenario: Relative time search

- **WHEN** `search_memory` receives a query containing `two months ago`
- **THEN** the response includes the original query, cleaned effective query, and UTC window metadata
