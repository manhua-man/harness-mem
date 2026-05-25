## Design

### Minimal temporal model

Truth-like structured entities carry:

- `valid_from`: when the truth starts applying
- `valid_to`: when it stops applying; `null` means current
- `recorded_at`: when harness-mem recorded the truth
- `supersedes`: ids replaced by this truth
- `superseded_by`: ids that replaced this truth

Legacy JSON that lacks the fields is loaded with:

- `valid_from = created_at` for `MemoryEntry` and `RelationFact`
- `valid_from = confirmed_at` for `ConfirmedRule`
- `recorded_at` mirrors the same timestamp
- `valid_to = null`
- supersede lists empty

### Read contract

`LocalStructuredStore` defaults to current-only reads for memory entries,
confirmed rules, and relation facts. Callers can pass `include_history=True`
to opt into historical records.

The first implementation keeps the public behavior conservative: existing
callers do not need to pass the new flag and automatically get current truth.

### Non-goals

- No automatic conflict detection in v1.7.0
- No automatic supersede confirmation
- No physical deletion of old truth
- No graph traversal yet
