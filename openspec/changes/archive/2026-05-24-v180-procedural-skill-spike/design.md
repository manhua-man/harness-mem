## Design

### Minimal procedural candidate model

The first step treats procedural memory as a reviewable candidate. The candidate is not a live skill until it is explicitly confirmed.

Each candidate should carry:

- `activation_condition`
- `steps` in execution order
- `termination_condition`
- `success_examples`
- `source_session_id` or another provenance pointer
- `confidence`
- `status`

### Confirmed Skill model

Confirming a pending procedural candidate creates a confirmed `Skill` with:

- `name`
- `activation_condition`
- `steps`
- `termination_condition`
- `success_examples`
- `source_candidate_id`
- `source_session_id`
- `confidence`
- `usage_count`
- `success_count`
- `failure_count`
- `success_rate`
- `last_used_at`

Confirmed skills are searchable through `search_skills(task_description)` and can record execution outcomes. This is a procedural layer, not semantic truth.

### Read-only boundary

The v1.8.x loop may extract candidates from repeated sessions, present them for review, promote confirmed candidates to `Skill`, and update skill success counters. It must not:

- write into current truth stores
- change wake selection
- bypass human review
- auto-learn or auto-confirm new skills

### Fixture strategy

The fixture set should use short, repo-relevant workflows such as:

- focused test loops
- review-before-merge loops
- maintenance command sequences

These fixtures validate the shape and boundary before heavier procedural extraction work.

### Non-goals

- No procedural retrieval in wake yet
- No cross-project skill sharing
- No background daemon or autonomous learning loop
