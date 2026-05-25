# v1.7.2 Temporal Graph Retrieval

## Why

Temporal truth exists after v1.7.0 and supersede review exists after v1.7.1, but read paths still need two operator-facing upgrades:

- relative time questions should narrow candidate windows before ranking;
- relation facts should be explainable as bounded paths rather than flat search hits.

## What Changes

- Parse a small deterministic set of relative time phrases from search queries.
- Thread the resulting UTC window through observation search and structured truth search.
- Add bounded relation traversal with default depth 2 and hard cap 3.
- Expose relation tracing through CLI and MCP.
- Keep wake relation summaries current-only and confidence-gated.

## Out Of Scope

- Free-form natural-language date parsing beyond the explicit supported phrases.
- Unbounded graph traversal or ontology merge.
- Procedural memory behavior, which belongs to v1.8.
