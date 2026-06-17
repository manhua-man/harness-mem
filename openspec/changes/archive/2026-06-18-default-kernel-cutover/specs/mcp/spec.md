## ADDED Requirements

### Requirement: MCP search and query-aware wake share backend retrieval semantics
The MCP server SHALL use the authoritative runtime `SearchBackendResponse` for
`search_memory` and for query-aware wake support payloads, while preserving the
existing MCP input and output schema.

#### Scenario: search_memory consumes authoritative backend response
- **WHEN** `search_memory(project_name="demo", query="storage v2")` runs
- **THEN** the server returns memory entries and observations derived from the runtime backend response
- **AND** the response exposes requested mode, effective mode, fallback reason, budget, and truncation metadata from that backend response

#### Scenario: wake packet retrieval semantics match MCP search
- **WHEN** `wake(project_name="demo", current_task="storage v2")` runs
- **THEN** the query-aware wake packet is assembled from the same backend retrieval contract used by `search_memory`
- **AND** the public wake output format remains unchanged
- **AND** the query-aware packet does not synthesize a second independent retrieval interpretation
