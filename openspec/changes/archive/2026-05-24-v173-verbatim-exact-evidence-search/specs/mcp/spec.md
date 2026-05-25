# MCP Delta

## ADDED Requirements

### Requirement: Search Raw Tool

The MCP server SHALL expose `search_raw`.

#### Scenario: Exact evidence payload

- **WHEN** a client calls `search_raw` with a regex pattern
- **THEN** the response includes exact observation matches, snippets, match spans, and candidate counts

#### Scenario: Invalid regex payload

- **WHEN** a client calls `search_raw` with an invalid regex
- **THEN** the tool returns `success=false` with a regex error message
