## Why

`harness-mem` 已经具备 canonical SQLite、SearchBackend contract、Rust hot path 和 benchmark evidence，但默认运行时仍主要依赖 legacy JSON blob truth 与旧检索主链路。继续在这个状态上叠加新 backend 或更多 retrieval features，会让 truth 语义、迁移路径和运行时入口长期双轨化。

## What Changes

- Make canonical SQLite the default truth store for structured memory and verbatim observations.
- Add canonical-first bootstrap with automatic first-run migration, explicit degraded fallback visibility, and rollback/export maintenance paths.
- Keep FTS, vector, trigram, graph, and other generated indexes as derived runtime indexes rather than truth.
- Move MCP `search_memory`, MCP `wake` query-aware retrieval, context sufficiency, and context-assembly query-driven layers onto the `SearchBackend` runtime contract.
- **BREAKING**: legacy JSON blobs stop being the default runtime read path and become migration / export / rollback inputs and outputs only.

## Capabilities

### New Capabilities
- `storage-runtime`: canonical SQLite bootstrap, default truth runtime, degraded fallback visibility, and rollback/export compatibility.

### Modified Capabilities
- `retrieval`: runtime retrieval MUST use one authoritative `SearchBackend` contract for mode, fallback, budget, and truncation semantics.
- `mcp`: `search_memory` and query-aware `wake` payloads MUST expose backend-consistent retrieval semantics without changing their public schema.
- `cli`: maintenance and doctor surfaces MUST report the active truth-store runtime state and recovery path.

## Impact

- Affected code: local backend bootstrap, structured/verbatim stores, canonical store helpers, MCP search/wake tools, context sufficiency, context assembly, doctor/status reporting, and benchmark/runtime tests.
- Affected storage: `store_v2/canonical.sqlite` becomes the default truth source; legacy JSON becomes compatibility data.
- Affected runtime semantics: default search/wake retrieval paths stop hand-building backend payloads and use one shared backend contract.
