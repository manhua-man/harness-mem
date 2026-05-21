## 1. Schema and storage

- [x] 1.1 Add `SupersedeCandidate` schema
- [x] 1.2 Persist supersede candidates in JSON blobs and SQLite
- [x] 1.3 Include supersede candidates in candidate listing

## 2. Review surfaces

- [x] 2.1 Add MCP `suggest_supersede`
- [x] 2.2 Add MCP `confirm_supersede`
- [x] 2.3 Add MCP `reject_supersede`
- [x] 2.4 Add CLI fallback commands for suggest / confirm / reject

## 3. Confirmation behavior

- [x] 3.1 Confirming a supersede candidate marks target truth historical
- [x] 3.2 Confirming links replacement and target through `supersedes` / `superseded_by`
- [x] 3.3 Rejecting a supersede candidate preserves both truth records

## 4. Validation

- [x] 4.1 Add storage temporal tests
- [x] 4.2 Add CLI learning-loop tests
- [x] 4.3 Add MCP smoke tests
- [x] 4.4 Run focused tests, ruff, mypy, and full pytest
