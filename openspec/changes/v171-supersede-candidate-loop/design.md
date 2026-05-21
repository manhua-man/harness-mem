## Design

### Candidate layer

`SupersedeCandidate` is a review-layer object. It records which truth record should become historical and which current truth record replaces it. It does not mutate truth until a reviewer confirms it.

### Confirmation semantics

Confirming a candidate:

- sets `valid_to` on the target truth
- appends the replacement id to the target `superseded_by`
- appends the target id to the replacement `supersedes`
- marks the candidate `accepted` with `reviewed_at`

The operation never deletes the old truth record.

### Surface area

The CLI and MCP surfaces expose explicit suggest, confirm, and reject commands. The general candidate list includes supersede candidates so human review does not need a separate queue.

### Non-goals

- No AI auto-confirm
- No physical deletion
- No graph traversal
- No automatic ontology merge
