## Why

v2.6.1 introduced generated wiki-bridge artifacts (`claims.json`,
`topics.json`, `entities.json`) and v2.6.2 kept generated evidence out of
default truth surfaces while making cleanup suggestions reviewable. The next
small v2.6 step is to let Agents explicitly request a low-token wake view that
uses those generated artifacts without pretending they are canonical truth.

## What Changes

- Add an opt-in compact renderer for MCP `wake(renderer="compact")`.
- Load compact material from project-scoped generated wiki bridge outputs.
- Render short claims, topics, entities, and source ids with an explicit
  generated-summary authority label.
- Keep the default `wake` renderer unchanged.
- Keep generated claims out of default `wake` and `search_memory` truth reads.

## Impact

- Agents can use a lower-token wake view when they only need source-attributed
  orientation.
- The compact renderer remains read-only and renderer-only.
- Missing generated wiki artifacts fail clearly instead of falling back to
  hidden truth mutation or silent fabrication.
