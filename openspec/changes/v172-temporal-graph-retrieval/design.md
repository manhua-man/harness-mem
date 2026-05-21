# Design

## Temporal Window

`read_api.parse_relative_time_window()` recognizes conservative phrases such as `yesterday`, `last week`, `last month`, and `two months ago`. It returns:

- the cleaned FTS query;
- the UTC start/end window;
- the matched phrase for logging and MCP payloads.

The window is applied to:

- observation `timestamp`;
- structured truth `recorded_at`, then `valid_from`, then `created_at`.

If no phrase is recognized, search behaves as before.

## Relation Graph

`read_api.trace_relation_paths()` performs breadth-first traversal over accepted relation facts.

- Default `max_depth`: 2
- Hard cap: 3
- Current-only by default through existing `list_relation_facts(... include_history=False)`
- Optional relation type and confidence filters
- Output includes path entities, depth, edge evidence, validity fields, and minimum path confidence

Cycles are avoided by tracking entities already present in the current path.

## Wake

Wake relation summaries continue to use current-only `list_relation_facts`, but now gate facts at confidence >= 0.7 before applying the existing limit.
