## 1. Wake skill hints

- [x] 1.1 Add opt-in compact skill hints to default `wake`.
- [x] 1.2 Render hints as id/title/reason only, never full procedural steps.
- [x] 1.3 Keep default wake unchanged when hints are not enabled.

## 2. Explicit expansion

- [x] 2.1 Add an explicit MCP `get_skill` read tool for full skill payloads by id.
- [x] 2.2 Return scope, provenance, portability notes, and disabled assumptions in expanded skill payloads.

## 3. Budget and control

- [x] 3.1 Gate hints by MCP parameter and config.
- [x] 3.2 Keep skill hints on a separate small budget from L0/L1/L2 truth sections.

## 4. Validation

- [x] 4.1 Add MCP wake tests for opt-in hints.
- [x] 4.2 Add regression tests proving default wake output is unchanged.
- [x] 4.3 Add MCP tests for explicit skill expansion.
