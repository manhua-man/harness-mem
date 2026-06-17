## 1. Canonical Bootstrap

- [x] 1.1 Add canonical-first backend bootstrap with explicit runtime states for canonical, bootstrapped_from_legacy, and degraded_fallback.
- [x] 1.2 Keep rollback/export compatibility and surface the runtime state through maintenance diagnostics.

## 2. Canonical Runtime Stores

- [x] 2.1 Move structured-store truth reads and writes to canonical SQLite while keeping search indexes derived.
- [x] 2.2 Move verbatim-store truth reads and writes to canonical SQLite while keeping search indexes derived.

## 3. Retrieval Mainline

- [x] 3.1 Make `SearchBackendResponse` the authoritative query contract for MCP search and task-aware context assembly.
- [x] 3.2 Route context-assembly query-driven layers through the backend contract instead of direct shared-search helpers.
- [x] 3.3 Thin `read_api.search_memory` into a compatibility facade over the backend mainline.

## 4. Verification and Truth Writeback

- [x] 4.1 Add migration, canonical runtime, degraded fallback, and backend-consistency tests.
- [x] 4.2 Update change-truth artifacts and task checklist status after implementation.
