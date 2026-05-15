# Tasks: AI-led Distillation Bridge

- [x] Update Schemas (`MemoryEntry`, `RelationFact`) to support `status` field.
- [x] Implement Storage-layer filtering (search/list default to `accepted`).
- [x] Implement SQLite index migrations for the new `status` column.
- [x] Build `ImportBridge` tool and CLI `import` command.
- [x] Upgrade MCP Server with `suggest_*` and `confirm/reject` tools.
- [x] Make CLI `confirm/reject/candidates` polymorphic for all memory types.
- [x] Fix `StructuredStore` Protocol and sync with implementation.
- [x] Update MCP Smoke tests with new tool counts (17).
- [x] Remove trailing whitespaces and fix OpenSpec paths.
- [x] Add OpenSpec MCP deltas for AI candidate suggestions and accepted-only consumption.
- [x] Version the agent collaboration truth in repo-root `AGENTS.md`.
- [x] Add minimal MCP candidate lifecycle tests.
- [x] Final validation.
- [ ] Merge or archive after review.
