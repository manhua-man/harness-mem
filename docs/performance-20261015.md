# Speed and token experiment, 2026-10-15

Subsequent longer-history results and a separate package fingerprint are in
[the long-history follow-up](performance-long-history-20261015.md). They do not
replace this experiment's short-history negative result.

Overall result: **partial**. The selected correction sample became faster and
used fewer total input/output tokens, with verification retained. Short-history
reading did **not** establish an end-to-end saving, and billed-cost reduction
has not been proved. Do not advertise a general speedup or saving percentage.

Baseline source: `a909b3579b6f43743d56145a841ac551b63ddcba`. First candidate package
fingerprint: `2aaf5e3e248ae22c86e9a9b53e815c733dc1b6c8cb06c021dbbd21d093b96964`.
Version remains `0.9.28`; these changes are unreleased. Raw attempts, frozen
runtime snapshots, corpus, plans, timing/usage records and the derived receipt
are local-only under `.tmp/performance-20261015/`; `report.json` is the first
summary, retained unchanged. `report-final.json` records the subsequent query-only
fix and its separate evidence boundary under final package fingerprint
`71cabf243b2487adcda79802edcba61892b0bc11445eba8282565e43a9933c0a`.

## Measurement contract

- Same fictional task, current files and searchable original history in OFF
  and ON; OFF is not deprived of the historical answers. Same installed Codex,
  configured model/reasoning, read-only task sandbox and common instructions.
- ON exposes the real twenty-tool MCP catalog, not a cheaper search-only
  replacement. Its test adapter admits only the scoped operations required by
  each experiment; it does not implement alternative memory semantics.
- Isolated fixture SQLite contains declared pre-existing knowledge. Its seed
  is not model extraction and is not a zero-cost memory-construction claim.
- Report wall time, complete CLI-reported input/cache/output, calls and actual
  final answers. Cache is a subset of input; reasoning output is not added a
  second time. No character/4 estimate or inferred dollar bill is used.
- Task quality checks six fields, including source precedence, a changed
  historical decision, unrelated-project noise and explicit unknown values.
  Grading reads the final native message, not concatenated progress commentary.
- New attempts have new files. Failed parser/adapter attempts and unhelpful
  performance results remain available rather than being relabeled or replaced.

## Findings before optimization

The no-model baseline prompt rendering is about 14.6K tokens before tool
definitions; the full MCP catalog is separately 7,571 `o200k_base` tokens.
These are measured text surfaces, not additive invoices or proof of the
provider's internal prompt layout. A three-fact search response is only 191
tokens. The clearest optimization lead is fixed context repeated across Agent
round trips, not merely trimming a few fact characters or SQLite CPU time.

The first eight availability-only tasks returned correct answers but made no
memory calls. They measure the cost of having a connected catalog, not memory
use. The next four explicitly requested historical lookups; the Agent invented
a project-only filter, missed decisions stored under `global`, then searched
the raw history. These are observable wasted-work cases, not valid memory-hit
benefits. The first candidate's four tasks retained that problem and did not
improve end-to-end consumption.

The final scope-corrected comparison explicitly uses `hm` and tells **both**
arms the existing all-project contract. The task and source information remain
equal. This is a protocol refinement, not an unchanged preregistered series;
there is only one OFF/ON pair per version in this final comparison.

| Final short-history read | Wall seconds | Input tokens | Cached input | Output | Actual memory hits |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline OFF | 15.978 | 112,479 | 79,360 | 319 | 0 |
| Baseline ON | 18.191 | 102,535 | 75,392 | 245 | 1, three facts |
| Candidate OFF | 21.155 | 100,716 | 85,888 | 323 | 0 |
| Candidate ON | 22.436 | 107,826 | 91,136 | 342 | 1, three facts |

All four final answers satisfy all six fields. Candidate ON is slower and uses
more input than its contemporary OFF control; it also does not beat baseline ON.
Thus this small task does **not** justify a read-speed or read-token-saving claim.
The earlier waves are retained separately, not averaged into a favorable result.
Across the twenty task attempts, the native final answers pass 120/120 field
checks; that is bounded synthetic task quality, not general semantic accuracy.

## Changes and the native correction sample

1. Compact only JSON envelope whitespace. Original strings, source content,
   digests, fields, validation and continuation remain intact. The same three
   facts measure 191 -> 143 `o200k_base` returned-text tokens, a 25.1% reduction.
   That is a response-size result, not a whole-Agent token saving.
2. Shorten repeated tool prose, expose existing suggestion parameter names
   (`canonical_title`, not `title`) and keep every existing validation rule.
   Full twenty-tool descriptor text measures 7,571 -> 7,414 tokens, only 2.1%
   smaller after the additional corrective guidance is included.
3. Return `readback_verified=true` only after fresh SQLite/current-search checks
   on completed saved changes. `hm` can reuse those returned changes instead
   of another model/tool round trip. Missing/failed checks still stop success;
   no-write results do not receive this assertion. Partial organization and
   unfinished work remain distinct from verified saved content.
4. An empty explicit project filter offers a conditional, reusable all-project
   retry. It does not execute that retry or read other projects automatically;
   an explicit user-only-project restriction must still be respected.

The native manual test reuses two selected, previously recorded **actual Codex
test conversations**, not fabricated native transcripts. Separate isolated
stores start with the original source preference, then organize its explicit
eleven-to-twelve-day correction through the real MCP/verification/SQLite/Note
path. The compared correction prompt and source are identical.

| One native correction per version | Wall seconds | Input | Cached input | Output | MCP calls | Searches after finalize |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Baseline | 55.746 | 272,584 | 249,984 | 1,481 | 8 | 2 |
| Candidate | 40.138 | 235,656 | 202,880 | 1,331 | 6 | 0 |

Observed wall time decreases 28.0%, and total input+output decreases 13.5%.
This is **one pair**, not a latency distribution or a general improvement.
Uncached input+output instead rises from 24,081 to 34,107 (+41.6%) because the
observed cache-hit ratios differ. Without actual tariff/billing data, it would
be wrong to say the candidate costs less money. Do not mix these separate
write/correction samples into the read fixture's amortized-cost calculation.

The baseline's initial-save sample contains a rejected `title` argument and
an experimental adapter denial; it is retained as negative evidence and is
excluded from the clean correction comparison. Candidate initial save takes
33.224 seconds, makes five MCP calls, and has no rejected call. Candidate
correction also has no rejected call. Its independent new Codex recall takes
21.687 seconds and finds TSV plus twelve days, not eleven days.

## Query-only follow-up and its limit

The independent reviewer found that the first native recall's combined Chinese
query returned empty before two separate searches succeeded. A bounded lexical
fallback now runs only on an empty original ranking, for two unquoted CJK
phrases with one explicit conjunction. Both phrases must independently match
through the unchanged ranker; literals, existing nonempty rankings and selected
project scope stay unchanged. It is not a semantic parser or recursive split.

An independent fresh MCP replay of that exact query now returns the two complete
current facts, while a query with an unsupported second topic stays empty. A
fresh native Codex session on final code also recalls TSV/twelve days correctly
in 19.159 seconds, but chooses **two independent searches**, not the combined
path. It reports 111,802 input, 81,792 cached input and 204 output tokens. Do not
describe this as a natural one-call replay or an end-to-end token saving. Earlier
save/correction evidence retains its recorded first-candidate fingerprint;
only this fresh recall and the final direct probes exercise the later bytes.

## Quality, safety and remaining work

The final candidate has two independent current facts. Reopened SQLite, an
independent MCP stdio process and a separate native Codex session agree. Both
selected jobs have complete source coverage, retained original/frozen sources,
verified revision hashes and meaningful hash-matching Notes/latest copies.
This is a selected CLI/manual path, not natural Stop or seven live hosts.

Final affected-scope regression: **711 passed, zero failures/errors/skips**.
The bounded reading, clean retrieval and manual batch outcome probes pass.
Ruff, mirrors and descriptors pass; the three original scoped Mypy files and
the query-only follow-up module pass. Adding the
search handler to Mypy exposes the same pre-existing dict-inference error at
baseline line 269/current line 274; this iteration does not claim a clean
whole-repository type check or change that unrelated branch.

The real 575 current memories retain their original logical hash, and global
Codex/harness-mem configuration retains its original byte hashes. No shared
MCP restart, global command installation, other-host model attempt, version
bump, commit, push or Release is part of this experiment. Twenty-six native
model invocations are counted in the experiment; parent-agent/research/review
and local-check overhead is separate and is not silently treated as zero.

Next performance work should address fixed host/tool context and unnecessary
Agent round trips, then repeat matched tasks under controlled cache conditions.
Larger historical workloads and real memory construction/maintenance costs
still need measurement before claiming a complete user's workflow is cheaper.
Do not weaken source validation, discard facts, hide missing memory or compare
our full CLI task against another project's search-only number to obtain a win.

External claim definitions and the methods worth borrowing are recorded in
[the reference comparison](reference-projects/performance-comparison.md).
