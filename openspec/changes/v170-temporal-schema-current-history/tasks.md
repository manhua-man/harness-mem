## 1. Schema

- [x] 1.1 Add temporal fields to `MemoryEntry`
- [x] 1.2 Add temporal fields to `RelationFact`
- [x] 1.3 Add temporal fields to `ConfirmedRule`
- [x] 1.4 Preserve legacy JSON loading with derived defaults

## 2. Storage

- [x] 2.1 Add SQLite columns and migrations for temporal fields
- [x] 2.2 Persist temporal fields on save
- [x] 2.3 Default structured list/search reads to current-only
- [x] 2.4 Add `include_history` read path for structured stores

## 3. Surfaces

- [x] 3.1 Add CLI `--include-history` for search and confirmed-rule listing
- [x] 3.2 Add MCP / REST `include_history` parameters where relevant
- [x] 3.3 Mark historical results in output as `[historical valid_to=...]`

## 4. Validation

- [x] 4.1 Add schema round-trip tests
- [x] 4.2 Add current-only vs include-history storage tests
- [x] 4.3 Run focused temporal tests
- [x] 4.4 Run full `pytest / ruff / mypy`
