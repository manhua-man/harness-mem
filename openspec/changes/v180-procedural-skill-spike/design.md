## Design

### Minimal procedural candidate model

The first spike treats procedural memory as a reviewable candidate, not a live runtime primitive.

Each candidate should carry:

- `activation_condition`
- `steps` in execution order
- `termination_condition`
- `success_examples`
- `source_session_id` or another provenance pointer
- `confidence`
- `status`

### Read-only boundary

The spike may extract candidates from repeated sessions and present them for review, but it must not:

- auto-promote skills
- write into current truth stores
- change wake selection
- bypass human review

### Fixture strategy

The fixture set should use short, repo-relevant workflows such as:

- focused test loops
- review-before-merge loops
- maintenance command sequences

These fixtures are only for shape validation and future parser work.

### Non-goals

- No procedural retrieval in wake yet
- No cross-project skill sharing
- No background daemon or autonomous learning loop
