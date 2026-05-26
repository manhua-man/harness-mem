## Design

v2.3.1 把 v2.3.0 的"窗口 + 信号"地基升级成"建议 + 应用"。本文件锁定三块：

1. Suggestion pass 的算法、候选 schema、MCP 工具划分。
2. Content-based token trim 的 tokenizer 选型与降级路径。
3. Weak-link signal application 在 wake / search 排序里的接入点与 opt-out。

### Suggestion pass

#### 候选 schema 决策

| 类型 | 复用既有 | 新增 |
| :--- | :--- | :--- |
| Merge | — | `MergeSuggestionCandidate` |
| Stale truth | — | `StaleTruthSuggestionCandidate` |
| Supersede | `SupersedeCandidate`（v1.7.1） | — |

**为什么不把 merge / stale 也塞进 `SupersedeCandidate`**：supersede 的语义是
"A 被 B 替代，A 标历史"，merge 是"A 和 B 合成 C，二者都标历史"，stale 是
"A 自然过期，无替代"。三种 valid_to 后果不同，apply 时的 SQL 路径也不同。
塞一起会让 `confirm_supersede_candidate` 的逻辑分支爆炸。

#### `MergeSuggestionCandidate`

```python
class MergeSuggestionCandidate(BaseModel):
    id: str
    project_name: str
    target_a_id: str          # min(id) of the pair — see "Pair ordering"
    target_a_kind: Literal["memory_entry", "confirmed_rule"]
    target_b_id: str          # max(id) of the pair
    target_b_kind: Literal["memory_entry", "confirmed_rule"]
    proposed_content: str     # see "proposed_content authorship" — `""` from pass
    similarity_score: float   # 0..1, the embedding similarity that triggered it
    evidence_signal_ids: list[str]  # may be empty (similarity is the trigger)
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    metabolism_run_id: str    # back-reference to the run that produced it
```

apply：confirm 后 `target_a` / `target_b` 都 `valid_to=now`,
`supersedes` / `superseded_by` 链指向新建 `MemoryEntry(content=proposed_content)`.

##### proposed_content authorship

The metabolism pass is a pure local algorithm — it does NOT call an LLM.
`_propose_merges` therefore writes `proposed_content=""` when persisting
a candidate. The Agent generates the merged content during the
`confirm_merge_candidate` flow (or `auto_review_candidates` apply
branch), reading both targets and producing the final string before the
new `MemoryEntry` is created. This keeps the pass deterministic and
LLM-free; LLM cost shifts to confirm time, where it already lives.

##### Pair ordering / dedupe

Merges are unordered: `(A=x, B=y)` and `(A=y, B=x)` describe the same
candidate. To prevent duplicate persistence the proposer normalizes
each pair so `target_a_id < target_b_id` lexicographically. Any
deduplication query can use the natural primary key
`(project_name, target_a_id, target_b_id)`.

##### Scope: entry + rule, not relation_fact

`target_*_kind` is restricted to `memory_entry` and `confirmed_rule` in
v2.3.1. Fact merges involve picking a winning `(source, target,
relation_type)` triple, which is a richer semantic decision than entry
or rule merge. We defer fact merges to v2.3.2+. The Literal staying
narrow is intentional — adding a third kind later is a Pydantic
ENUM-tier change, not a breaking schema migration.

#### `StaleTruthSuggestionCandidate`

```python
class StaleTruthSuggestionCandidate(BaseModel):
    id: str
    project_name: str
    target_id: str
    target_kind: Literal["memory_entry", "confirmed_rule", "relation_fact"]
    last_surfaced_at: datetime | None  # 来自 RetrievalSignal 聚合
    days_since_last_surface: int
    evidence_signal_ids: list[str]     # 通常是空（沉默正是它的理由）
    status: Literal["pending", "accepted", "rejected"]
    created_at: datetime
    metabolism_run_id: str
```

apply：confirm 后只设 `valid_to=now`，不新建替代。被 stale 的 truth
仍可通过 `include_history=True` 查询。

##### last_surfaced_at data source

The selector reads `last_surfaced_at` as the **newer** of two sources:
- v2.2 fields: `MemoryEntry.last_accessed_at` / `ConfirmedRule.last_surfaced_at`
- v2.3.0 `RetrievalSignal` rows: latest `recorded_at` where
  `signal_type in ("wake_surfaced", "search_hit")` and `target_id`
  matches.

`days_since_last_surface = (now - newer_of_the_two).days`. Using the
newer value is the conservative choice: a truth that was surfaced via
v2.2 wake (which still bumps `last_accessed_at`) is not falsely flagged
stale just because v2.3.0 hadn't been deployed yet when the surface
happened. When neither source has a value, `last_surfaced_at` is
`None` and `days_since_last_surface` is computed from `created_at`.

##### Scope: entry + rule supported, fact deferred

`target_kind` keeps `relation_fact` in the Literal so future versions
can extend without a schema migration, but the v2.3.1 algorithm only
processes `memory_entry` and `confirmed_rule`. Reason: `RelationFact`
has no `last_accessed_at` field in v2.2 (adding one would touch the
v2.2 schema, out of scope). Once v2.3.0 signals accumulate enough
fact `wake_surfaced` / `search_hit` history we can revisit.

#### Suggestion 选择算法

输入：`select_replay_window(...)` 返回的 `ReplayWindow`。

```python
async def select_metabolism_pass(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    budget: ReplayBudget,
    similarity_threshold: float = 0.85,
    stale_silence_days: int = 60,
    max_merge_pairs: int = 20,
    max_stale_suggestions: int = 50,
) -> MetabolismPass:
    window = await select_replay_window(backend, project_name=project_name, budget=budget)
    # window-seeded: merges run on a pool drawn from the replay window
    merge = await _propose_merges(
        backend,
        window,
        threshold=similarity_threshold,
        max_pairs=max_merge_pairs,
    )
    # project-scoped: stale must scan current truth that's NOT in the
    # replay window (silent truth is exactly what's missing from the
    # window), so it does not take the window as its scope.
    stale = await _propose_stale(
        backend,
        project_name=project_name,
        silence_days=stale_silence_days,
        max_suggestions=max_stale_suggestions,
    )
    # window-bound: orphan supersede chains live on historical_truths.
    supersede = await _propose_supersedes(backend, window)
    return MetabolismPass(window=window, merge=merge, stale=stale, supersede=supersede)
```

`_propose_merges`: **entry-entry only in v2.3.1**. The pool is the
union of:

1. `window.repeat_search_hits` targets where `target_kind == "memory_entry"`
   (deduped).
2. Current `MemoryEntry` rows (`valid_to is null`) whose `created_at`
   or `last_accessed_at` falls inside `window.time_range` —
   "co-active during the replay window's lookback band". Cap this leg
   at `max_merge_pool_entries` (default = `budget.max_observations`,
   i.e. 200) so the pool stays small and the N² similarity step stays
   bounded.

The earlier draft of this design said "co-surfaced in
`window.observations`" — that wording is misleading because there is
no stable observation→entry edge in v2.3.0 (`Observation.metadata`
has no fixed field linking back to a memory entry). The honest
contract is "current entries co-active in the same time band as the
window", as written above.

**Historical truths and confirmed rules stay out of the merge pool.**
Rationale:

- Two truths that are both already historical merging into a third
  historical entry has near-zero replay value — that's a job for
  supersede chains, not merge.
- `vec_embeddings` keys on `entry_id` and is only populated by
  `save_memory_entry`. `confirmed_rule` has no persisted vector, so
  rule-rule and rule-entry similarity would either need on-the-fly
  encoding (a lot of CPU during a "preview-adjacent" run) or a
  storage migration. Both are out of scope; rule merges are deferred
  to v2.3.2+.

Similarity computation reuses the existing embedding loader in a
**model-consistent** way:

- For each id in the pool, read `vec_embeddings` only when its
  `model_id` matches the active `get_embedding_model_id()`. This
  matches how `hybrid_search._read_persisted_embeddings` already
  filters.
- On a miss (or `model_id` mismatch from an older model), encode
  `entry.content` in memory with the same loader. Do **NOT** write to
  `vec_embeddings` from the pass — the metabolism pass stays a
  read-only computation; vec backfills belong in
  `commands/maintenance.py`.
- All vectors used in the cosine matrix are then guaranteed to share
  one `model_id`. Optionally emit
  `merge_embeddings_reencoded: <count>` in the run notes for audit
  visibility on how many on-the-fly encodes happened.

Pair every distinct `(target_a_id, target_b_id)` with
`target_a_id < target_b_id`, filter `similarity >= threshold`, cap at
`max_pairs` (default 20) to avoid N² candidate explosion. Each
candidate's `evidence_signal_ids` carries the `search_hit` signal
ids supporting the repeat-targets that contributed to the pair (when
applicable; can be empty).

`_propose_stale`: **project-scoped, NOT window-scoped**. Stale
detection asks "which current truths have nobody touched in
`silence_days`?" — by definition the silent ones are the ones missing
from the replay window, so anchoring stale on `window.historical_truths`
would systematically miss the answer.

The proposer scans current truth (`valid_to is null`) for
`memory_entry` and `confirmed_rule` (relation_fact deferred per the
schema scope decision), computes `last_surfaced_at` as the **newer of**
the v2.2 field (`last_accessed_at` / `last_surfaced_at`) and the most
recent `RetrievalSignal` row of type `wake_surfaced` / `search_hit`
for that target id, derives `days_since_last_surface`, and selects
truths where `days_since_last_surface >= silence_days`. Sort by
`days_since` descending and cap at `max_suggestions` (default 50). When
the cap fires, emit `stale_scan_truncated: <selected>/<pool>` in the
`MetabolismRun.notes` for audit (mirrors the v2.3.0
`truncated_within_<dim>` convention).

The window's `repeat_search_hits` may **upweight** a stale candidate
that also appears there (a target is repeatedly searched but never
surfaced in wake — strong signal of staleness in a different
dimension). v2.3.1 doesn't implement that boost; it's noted here as
a v2.3.2 idea.

`_propose_supersedes`: **deferred in v2.3.1**. Returns empty list. The
proposer slot exists so `MetabolismPass.supersede` and
`MetabolismRun.output_counts["supersede_suggestions"]` keep their
shape, but no algorithm runs. Rationale:

- The original "orphan supersede chain" framing (look for A linked to
  B where B isn't yet confirmed) doesn't survive contact with the
  v2.3.0 schema: `historical_truths` is the slice of truths that
  already have `valid_to` set — by definition they are *not* missing
  the supersede half. The chain framing reads backwards.
- The remaining options for auto-supersede generation all collapse to
  the same input as merge (high embedding similarity), so they would
  produce duplicate candidates with a different label. Without a
  separate signal that says "B should replace A" rather than "A and B
  should merge", auto-supersede over-generates.
- v1.7.1 already exposes manual supersede via `tool_propose_supersede`.
  Users do not lose the capability; the only thing v2.3.1 declines is
  *automating* it.

Auto-supersede returns when one of these signals is in scope:
1. A reliable "user searched A, accepted B" feedback loop (out of
   scope until the search-correction layer ships).
2. A schema field on `MemoryEntry` that flags "I supersede X"
   intentionally, written at create time by a corrector.
3. A separate similarity threshold band (e.g. 0.95+) calibrated on
   real review accept/reject data — calibration data is what v2.3.1's
   first deployment will gather.

Until then `_propose_supersedes` stays a stub.

#### MCP 工具划分

- `metabolism_preview`（v2.3.0，**保持只读不变**）：跑 selector，写
  `MetabolismRun(kind="preview", status="preview")`，不产候选。
- `metabolism_run`（v2.3.1 新）：跑 `select_metabolism_pass`，写
  `MetabolismRun(kind="metabolism", status="completed")`，产出三类候选。
  失败时写 `status="error"` 并返回 doctor pointer，与 v2.3.0 一致。

两个工具的 input_schema 完全相同（project_name + budget），便于 Agent
统一调用。区别仅在副作用。

### Content-based token trim

#### Tokenizer 选型

候选：
1. `tiktoken`（OpenAI）— 跨 GPT-4 / GPT-4o 准；约 8MB 安装包；本仓已可选依赖。
2. `transformers.AutoTokenizer`（HuggingFace）— 灵活但安装重；本仓没用。
3. 字符数 / 4 启发式 — 准确度差但零依赖。

**决策**：用 `tiktoken` 作为可选依赖；缺失时降级到字符数 / 4 启发式并在
`MetabolismRun.notes` 里写一条 `tokenizer_fallback: char-heuristic`。
这样既不强求所有部署都装 tiktoken，又能让有需要的环境拿到准确数。

#### 接入点

`select_replay_window` 在选完 ids 后多走一步：

```python
estimate = 0
for dim_name, dim in dimensions.items():
    for selected_id in dim.selected_ids:
        content = await _fetch_content_for(backend, dim_name, selected_id)
        estimate += _count_tokens(content)
```

`_fetch_content_for` 只读 window 里的 ids 对应的内容（不扫全库），且做
batch IO（一个 `list_memory_entries(ids=[...])` 比逐条快）。

砍尾算法 (`_TRIM_ORDER`、维内删 tail) 复用 v2.3.0；唯一的差别是 `estimate`
减量从常数换成实际 token 数。

#### 兼容性 / 降级

- `_DIM_TOKEN_WEIGHT` v2.3.0 启发式仍保留，作为 tiktoken 缺失时的 fallback
  路径之一（fallback 顺序：tiktoken → 字符 / 4 → 常数权重）。
- `ReplayBudget.max_total_tokens` 的语义在 v2.3.1 起明确为"精确 token"。
  设过 v2.3.0 默认值 16000 的调用方无需改代码——v2.3.0 的启发式比真值偏大
  约 1.5×，所以从启发式过到精确等于 budget 实际"扩容"了，更松而非更紧。

### Weak-link signal application

#### Wake re-ranking

`wake` rendering wraps the existing rules path with one optional
re-grouping step. When `ProjectProfile.weak_link_signals` is `True`,
`cmd_wake_up` calls `pull_recent_signals(project, target_ids,
since=now-30d)` between the existing `list_confirmed_rules(...)` step
and the existing `[:5]` budget cut. Rules whose target had **at least
one** `wake_surfaced` or `search_hit` signal in the last 30 days flow
into a `Recent active` group; the rest flow into a `Stable / quiet`
group. Within each group the existing sort key (`confirmed_at DESC`)
is preserved. The total budget stays at 5 rules — `Recent active`
fills first, `Stable / quiet` fills the remainder. The output gains
two markdown subheads (`### Recent active` / `### Stable / quiet`)
under the existing `# Confirmed Rules` block; everything else (item
formatting, usage counters, validity markers) is unchanged.

When `weak_link_signals` is `False` (the v2.3.1 default), the wake
output is bit-for-bit identical to v2.2. No call to
`pull_recent_signals` happens; the touch / ingest / budget main
chain is untouched.

`Experimental skills` (v2.3.1's third group) is **deferred to
v2.3.2**: v2.2 wake output does not surface skills today (skills are
read via `search_skills` MCP), and a third group on the wake itself
crosses the line from "weak-link tweak" into "new user surface".
v2.3.1 limits its wake change to splitting confirmed rules.

#### Search ranker

`read_api.search_memory` adds a single post-processing step over the
hybrid score list when `weak_link_signals` is on. For each result
whose `target_kind == "memory_entry"`, the helper
`pull_recent_signals(project, [target_id], since=now-7d)` is called
(or batched once across all results) and a `repeat_boost = 0.1` is
added to `final_score` whenever `search_hit_count >= 2`. Re-sort,
return. Constants `REPEAT_BOOST_BASE = 0.1` and
`REPEAT_BOOST_WINDOW_DAYS = 7` live in the same module; v2.3.1 does
not parameterize them — first deployments use the defaults; v2.3.2
revisits if calibration data shows a need.

When `weak_link_signals` is off, no boost step runs. Result order is
v2.2-identical for the same query against the same index.

#### Profile field + MCP exposure

`ProjectProfile.weak_link_signals: bool = False` (explicit field, not
`extra="allow"` overflow — explicit is needed for `update_project_profile`
to typecheck the override and for tests to assert on default-off).
`update_project_profile` MCP tool takes `weak_link_signals` as an
optional bool kwarg; when omitted, the existing field value is
preserved. The single profile flag controls **both** wake re-grouping
and search boost — one switch, two effects, fewer surprises.

Default off is a deliberate "ship dark, document recommendation"
posture: v2.3.1 release notes will recommend turning it on after a
project has accumulated enough `RetrievalSignal` rows for the
re-ranking to mean something. Default on would change wake output
on every existing project the moment v2.3.1 lands, which violates
the v2.2 contract that loop_harness tests pin against.

#### Doctor transparency block

`harness-mem doctor` output gains a new block. When
`weak_link_signals` is `False`:

```
Weak-link signal influence: disabled (set weak_link_signals=true in project profile)
```

When `True`:

```
Weak-link signal influence (v2.3.1):
  rules pushed to 'Stable / quiet' group:    12 / 47
  search results boosted (last 7 days):      8 distinct targets
  experimental skills:                       — (deferred to v2.3.2)
```

The disabled-line variant lets users see they have an opt-in to flip
without reading the project profile manually.

### Non-goals (v2.3.1)

- **README 无 v2.3.x 营销文案**。README 架构图"领域模型"已列出 `MergeSuggestionCandidate, StaleTruthSuggestionCandidate`；无需额外 candidate-types 列表或版本公告。
- 不引入后台 daemon。`metabolism_run` 仍由 Agent 显式触发（一次代谢一次调用）。
- 不引入 cross-project 信号聚合或建议生成。
- 不让信号修改 truth 的 confidence / valid_to / status——那些只有
  `confirm_*` candidate apply 才能动。
- 不把 suggestion 自动 apply。`auto_review_candidates` 接入这三类候选时
  仍按 v2.2 的 risk gate（merge 默认拒绝低相似度、stale 默认 pending
  待人确认、supersede 走原 v1.7.1 风险逻辑）。
- 不替换 `usage_count` / `last_accessed_at`：它们继续被 wake / search 写入，
  weak-link 应用读它们 + RetrievalSignal 双源数据。

### Open questions

- Tiktoken 选 model encoding（`cl100k_base` vs `o200k_base`）？默认 cl100k 比
  o200k 老但稳，o200k 更准确反映新模型。倾向 cl100k 直到 v2.4 确定主消费方。
- Stale silence_days 应该 30 / 60 / 90？默认 30 给得激进，可能产生很多假阳
  stale 候选。建议第一版默认 60，观察 review 拒绝率再调。
- Weak-link 应用是否应该按项目可关？目前设计里 opt-out 走 `project_profile`，
  但是否应该全局 env 开关 `HARNESS_MEM_WEAK_LINK_SIGNALS=0`？看部署反馈再定。
