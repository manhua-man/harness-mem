## Design

### Core data shapes

#### `MetabolismRun`

Append-only record of one metabolism / dream-style run, including
preview-only runs. Persisted as JSON blob under
`~/.harness-mem/data/structured/metabolism_runs/` and indexed in SQLite
under `metabolism_runs(id, project_name, started_at, status, kind)`.

Fields:

- `id: str` — UUID
- `project_name: str` — required; cross-project runs are out of scope here
- `kind: Literal["preview", "metabolism"]` — `preview` reads only and never
  produces candidates; `metabolism` is reserved for v2.3.1+ and is the
  status the spec acknowledges as future work
- `started_at / completed_at: datetime`
- `status: Literal["preview", "completed", "error"]` — preview runs end
  with status `preview`; later versions add `completed` after suggestions
  are written; `error` is reserved for selector failure
- `input_window: dict` — selector output, see below
- `selected_signal_ids: list[str]` — primary keys of `RetrievalSignal`
  entries that drove selection; small (≤ window budget)
- `output_counts: dict[str, int]` — placeholder; populated by future
  metabolism slices. v2.3.0 always writes `{"suggestions": 0}` for
  preview runs
- `duration_ms: int`
- `notes: str | None` — optional human-readable summary; selector populates
  with `truncated_within_<dim>` annotations when budgets cap output

`MetabolismRun.from_dict` defends against missing fields the same way
`MemoryEntry.from_dict` does — empty list / `None` / `0` defaults; this
keeps later schema additions non-breaking.

#### `RetrievalSignal`

A single observable event in the retrieval / review loop. The signal
itself is **not** truth — it's evidence about how memory has been used.
We already write some of these to `events.log` (auto-sync, wake errors),
but they're not structured for selector queries. v2.3.0 introduces a
dedicated table.

Fields:

- `id: str` — UUID
- `project_name: str`
- `signal_type: Literal[...]` (see below)
- `target_kind: Literal["memory_entry", "rule", "skill", "candidate", "observation", "supersede"]`
- `target_id: str`
- `recorded_at: datetime`
- `value: float | None` — optional numeric weight (e.g. score, success rate
  delta); kept generic so the same row can describe heterogeneous signals
- `context: dict | None` — optional small bag (`session_id`, `query`,
  `wake_run_id`, etc.)

Initial `signal_type` whitelist (extendable):

- `confirmed` / `rejected` (candidate review outcome)
- `wake_surfaced` (entry / rule / skill rendered into a wake output)
- `search_hit` (result returned by `search_memory`)
- `skill_result_success` / `skill_result_failure`
- `supersede_completed` (a supersede candidate became confirmed)

Storage:

- JSON blobs under `~/.harness-mem/data/structured/retrieval_signals/`
- SQLite index `retrieval_signals(id, project_name, signal_type,
  target_kind, target_id, recorded_at)` for efficient time-window /
  type filtering by the selector
- Existing `usage_count` / `last_accessed_at` writers keep working
  unchanged; the new signal stream is additive evidence, not a
  replacement for the rolled-up counters

### Signal write paths

We resist a refactor and patch the existing single-line touch points so
the signal becomes a shadow write. All writes go through one helper:

```python
async def record_retrieval_signal(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    signal_type: str,
    target_kind: str,
    target_id: str,
    value: float | None = None,
    context: dict | None = None,
) -> RetrievalSignal:
    ...
```

Write call sites in v2.3.0:

- `LocalStructuredStore.touch_memory_entry` → emits `wake_surfaced` when
  called from wake; the caller provides `signal_type` argument so the
  helper doesn't have to guess.
- `LocalStructuredStore.touch_confirmed_rule` → same with
  `signal_type="wake_surfaced"`.
- `read_api.search_memory` → emits one `search_hit` per result that
  actually flows back to the user; capped by the read API's existing
  result limit so we don't explode the signal table on broad queries.
- `auto_review_candidates` apply branch → `confirmed` / `rejected` per
  applied decision (the `applied_decisions` list is already iterated, we
  just add a write).
- `record_skill_result` → `skill_result_success` /
  `skill_result_failure`.
- `confirm_supersede` → `supersede_completed`.

Each signal write is wrapped in a try / log-and-continue: if the signal
table cannot be written, the user-visible primary mutation must still
succeed. That preserves the `Main task must not be held hostage` rule
from `docs/roadmap-v23.md`.

### Replay window selector

Pure, read-only function:

```python
async def select_replay_window(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: ReplayBudget,
) -> ReplayWindow:
    ...
```

`ReplayBudget` defines hard caps per dimension so the selector cannot
flood downstream passes:

- `max_observations: int = 200`
- `max_pending_candidates: int = 100`
- `max_historical_truths: int = 50`
- `max_low_success_skills: int = 20`
- `max_repeat_search_hits: int = 50`
- `max_total_tokens: int = 16000` — soft limit. v2.3.0 enforces this
  via a heuristic per-id slot per dimension (no content read), trimming
  the tail of dimensions in fixed cross-dimension order:
  `repeat_search_hits → low_success_skills → historical_truths →
  pending_candidates → observations`. Content-based trimming ("read the
  body, count tokens, drop oldest") is deferred to v2.3.1+ so v2.3.0
  stays a pure read-id selector.

`ReplayWindow` carries enough info to be reconstructed and audited:

- `time_range: tuple[datetime, datetime]` — covers the recent
  observation slice; older categories are time-bounded by recency of
  *signal* (last 30 days by default) rather than recency of authoring
- `dimensions: dict[str, ReplayDimension]` where `ReplayDimension`
  contains `selected_ids: list[str]`, `truncated: bool`, `total_seen:
  int`
- `signal_ids: list[str]` — the `RetrievalSignal.id` rows that drove
  selection (so the run record can replay)
- `notes: list[str]` — `["truncated_within_observations: 200/847", ...]`
  for hard per-dimension caps, plus
  `soft_token_budget: <estimate>/<max>` whenever the heuristic
  estimate is computed, plus `trimmed_for_token_budget: <dim>,<dim>,...`
  whenever the soft cap forced a tail trim. Hard-cap denominators are
  always the true pool size (the `observations` dimension issues a
  follow-up `COUNT` when the `cap+1` probe says it overflowed; other
  dimensions already aggregate the full pool in 3.2).

### `metabolism_preview` MCP tool

Single new tool, no CLI surface. Schema:

```jsonc
{
  "name": "metabolism_preview",
  "description": "Preview the next metabolism run's input window without writing suggestions or mutating truth.",
  "input_schema": {
    "type": "object",
    "properties": {
      "project_name": {"type": "string"},
      "budget": {
        "type": "object",
        "properties": {
          "max_observations": {"type": "integer", "minimum": 0},
          "max_pending_candidates": {"type": "integer", "minimum": 0},
          "max_historical_truths": {"type": "integer", "minimum": 0},
          "max_low_success_skills": {"type": "integer", "minimum": 0},
          "max_repeat_search_hits": {"type": "integer", "minimum": 0},
          "max_total_tokens": {"type": "integer", "minimum": 0}
        }
      }
    },
    "required": []
  }
}
```

Behaviour:

1. Resolve `project_name` (active project fallback), same rules as
   `/hm:distill`.
2. Build `ReplayBudget` from defaults overridden by request fields.
3. Call `select_replay_window(...)`.
4. Persist a `MetabolismRun(kind="preview", status="preview")` with the
   resulting window.
5. Return `{run_id, project_name, time_range, dimensions, notes,
   signals_used}` to the caller.
6. On selector failure: write `MetabolismRun(status="error")` with
   `notes=["selector failed: <message>"]` and return an error payload
   pointing at `harness-mem doctor`. Do not raise.

Tool stays out of the daily wake / distill flow. The user-visible
contract from v2.2 (canonical six counters, `/hm:review` repair-only)
is unaffected.

### Why this isn't bigger

It would be tempting to ship merge suggestions or stale detection in the
same slice. We deliberately don't, for three reasons:

- **Auditability**: signals + run records are observable from day one. If
  v2.3.1's suggestion pass produces noise, we can replay the same window
  and inspect which signals justified the selection.
- **Reversibility**: v2.3.0 makes zero truth changes. Rolling back is
  deleting two tables and removing a tool. v2.3.1's suggestion writers
  can use that escape hatch if they go wrong.
- **Test surface**: testing "selector picks the right window for
  fixtures" is independently meaningful. Bundling suggestion generation
  into the same diff would make calibration tests load-bearing for two
  unrelated correctness questions.

### Non-goals (v2.3.0)

- No merge / stale / supersede suggestion generation
- No weak-link signal application (signals collect, but nothing weakens
  truth yet)
- No background scheduler — `metabolism_preview` only runs when called
- No cross-project signal aggregation
- No automatic procedural skill regeneration
- No mutation of `usage_count` / `last_accessed_at` semantics
- No new wake / search behaviour change visible to end users

### No README change (v2.3.0)

v2.3.0 ships no slash command, no natural-language trigger, no CLI
subcommand, and no UI surface. The single API addition — the
`metabolism_preview` MCP tool — is Agent-invoked on user request, not
something users reach for directly. The user-facing README therefore
intentionally has no v2.3.0 section.

If a future doc audit notices the README "missing" v2.3.x and reaches
for an edit, **stop**. Do not add a README section until v2.3.1+ lands
a real user-facing entrypoint (suggestion application, scheduled run,
or similar). The v2.2 contract — canonical six counters, `/hm:review`
repair-only, `/hm:distill` six-step loop — remains the truth surface
for users; v2.3.0 only adds background plumbing.
