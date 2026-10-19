# Actual request capture and safe feature reuse, 2026-10-15

Outcome: **partial**. Actual request entities and per-request provider usage are
captured. A call-local scoring optimization preserves the exercised results and
reduces repeated text analysis. Native before/after tasks do **not** establish
overall speed or billed-cost improvement. The smaller host skill budget is
rejected because omitted-skill discovery was not verified.

This supersedes any interpretation of earlier debug prompt exports or MCP
`tools/list` text sizes as actual requests or invoiced consumption. Earlier
measurements and negative evidence remain in their original reports.

## What crossed the provider boundary

Ignored local receipts: `.tmp/request-capture-20261015/report.json`, each run's
`capture/` request/response entities, `wire-proof.json`, native `raw.json` and
`result.json`. Entity SHA256 values are checked. Bodies remain local; reports
publish names, counts, hashes and usage, not prompts or credential headers.

The collector uses a per-invocation provider alias and nonce-protected loopback
listener, forwarding unchanged bodies to the fixed official ChatGPT Codex
endpoint over HTTP/2 with certificate verification. Model remains
`gpt-6.1-sol`, reasoning `high`, using the existing ChatGPT login. Shared MCPs
are disabled only for isolated invocations; ON exposes all twenty fixture tools
through the existing read-only adapter. This proves a controlled native CLI
HTTP path, **not** the unchanged Desktop/WebSocket path. No global provider,
proxy, credential or connection setting was changed.

Every completed request declares twelve core tools: `functions.exec`, `wait`,
`request_user_input`, `request_user_input_async`, `new_context`; `clock.sleep`;
and collaboration `followup_task`, `interrupt_agent`, `list_agents`,
`send_message`, `spawn_agent`, `wait_agent`. They arrive in
`input[].type=additional_tools`, not top-level `tools`. Server attribution assigns
this block **6,126 input tokens per request**. The first ON request contains no
`mcp__task_memory__...` definitions. Later executor outputs contain requested
`search_memory` and `autopilot_search_tick` tool information. Reducing a full
twenty-tool export therefore does not imply reducing an inline twenty-tool
payload on this path.

The normal skill catalog contains **212 metadata entries**, repeated across
completed requests. Server-attributed size varies between approximately
**6,729 and 10,505 tokens per request** in matched tasks: observed host rendering,
not runtime-code savings. Metadata is not the same as reading every skill body.
The task reads the canonical `hm` body through a command; later requests contain
the complete body. Per-request tool names, skill names, catalog hashes,
body-presence and attribution are retained in each `wire-proof.json`.

The Python relay encountered six generation-request TLS failures across two
completed CLI tasks, plus four failed model-list requests.
Those attempts remain recorded and are excluded from speed comparisons;
failed-request usage is unknown, not zero. The Node relay passes ten local
tests: byte-preserving compression, partial/reset streams, client cancellation,
route/auth boundaries and Windows natural shutdown. The CLI normally closes
SSE after `response.completed`, sometimes before HTTP/2 END_STREAM. Reports
separate API completion from HTTP entity completion and retain `ClientAbort`.
Successful per-request usage sums exactly to native CLI usage in all eight tasks.
The verifier also checks the complete summary ledger against metadata/entity
file sets and hashes. Only blank-line-terminated SSE frames count; completion
requires a unique matching created-response ID and `status=completed`. Seven
negative/positive verifier regressions pass, including missing metadata,
unterminated frames, mismatched identity/status and entity tampering. Failed
early collector attempts are retained, not relabeled as complete HTTP captures.
The later Node captures also retain four client-cancelled model-list requests
without response headers. These are separate from the generation requests;
the six native Node tasks have 27 verified generation completions, not a claim
that every HTTP request completed successfully.

## External code examined and adoption

Pinned local source mirrors, not refreshed upstream HEAD claims:

| Reference | Concrete mechanism | Decision |
| --- | --- | --- |
| claude-mem `a90066f9cf82` | `src/servers/mcp-server.ts`, search instructions and `get_observations`: filter then batch full details | Retain conditional whole-fact reading; do not impose three calls on a complete short answer. No further call saving is shown here. |
| Hindsight `b5d8439c8f1b` | `hindsight-integrations/openclaw/src/index.ts:2267`, `before_prompt_build` reuses in-flight recall by bank/query | Borrow elimination of duplicate work, narrowed to pure text features within one retrieval call; no global/in-flight result cache or query normalization. |
| Mem0 `38e47ac2619b` | `mem0/memory/main.py`, `search` / `_search_vector_store`: retrieve then threshold/rerank/limit | No new top-k cutoff or evidence trimming merely for smaller output. |
| PrecisionMemBench `b95d6abb471c` | `src/utils/buildRetrievalReport.ts`, precision/recall and active/structural/empty classification | Compare exact rows/order and separately exercise missing knowledge, supersession and abstention; structural/empty success is not semantic success. |

Production change: `harness_mem/read_knowledge.py` shares exact-text term counters
only during one `search_current_knowledge` invocation, including its bounded
two-topic fallback. Query-specific weights, admission, ranking, scope,
deduplication, limits and error propagation still execute. No persisted cache,
public tool, query cap or knowledge mutation is added.

In the three-fact regression, term analysis falls **20 -> 7 calls**, with identical
rows/order. A 575-row synthetic repeated-field scorer experiment uses thirty
paired repetitions after three warmups: two-topic median **20.35 -> 9.29 ms**,
with **3,833 -> 579** term-analysis calls. Five query classes return identical
rows/order. Empty browsing is logically unchanged and slightly slower in this
sample (0.34 -> 0.37 ms). This deliberately repeated-text fixture measures local
scoring only, not real-store, model or full-task speed.

## Same-task native comparison

Both versions receive identical 180 fictional source sessions (**195,795
`o200k_base` tokens**), seven independently seeded current rows, current-file
override, eighteen-field task, default skill setting and full fixture tool
surface. Construction cost is excluded. Only `read_knowledge.py` differs between
frozen runtime snapshots. Two ON tasks run per version; sequential order is not
a randomized/cache-controlled experiment.

| Measurement | Before | Call-local reuse |
| --- | ---: | ---: |
| Mean complete-task time | 27.06 s | 29.11 s |
| Worst observed time | 29.77 s | 33.36 s |
| Mean provider input + output | 98,606 | 86,582 |
| Mean uncached input + output | 26,734 | 27,574 |
| Completed API requests, each task | 4 / 4 | 3 / 4 |
| MCP calls / terminal calls, each task | 1 / 2 | 1 / 2 |
| Correct requested fields | 36 / 36 | 36 / 36 |

The total-token drop is not attributable to this CPU change: model round count,
catalog rendering and cache behavior differ. Time and uncached input+output do
not improve. No dollar-cost or general acceleration claim follows.

A quality-only task omits the row covering five constraints and changes the
current delivery hour from ten to fourteen. The optimized runtime performs two
memory searches and six terminal calls, falls back to original history, and
returns **18/18 correct fields**, including unknown SLA/archive retention and
exclusion of Gallery policy. It takes 43.96 s and reports 230,023 input / 193,280
cached input / 703 output across eight completed API requests; it is excluded
from speed averages. Accepted-runtime comparisons plus this control pass
**90/90 bounded fields**, not general semantic or write-flow acceptance.

## Rejected catalog candidate and checks

The documented
[`skills.max_context_tokens` setting](https://learn.chatgpt.com/docs/config-file/config-reference)
was tried at 1,500 only for one invocation using the frozen baseline runtime.
The catalog shrinks **212 -> 66 entries**, omitting 146 distinct names; retained
entries also lose their descriptions. Four
requests attribute 2,145 tokens each to that catalog. The task still scores
18/18 because its workspace explicitly points to `hm`; this does not establish
discovery of all omitted skills. The candidate is **not adopted** or saved to
global/user configuration despite smaller input.

Fresh checks: **154 affected-scope tests**, scoped Ruff/Mypy and the configured
`bounded_current_memory_reading` direct outcome pass. New tests cover five query
classes and five limits, exact result equality, unchanged counters,
replacement/deletion between calls, empty features, blank browsing and
propagated source-read errors. This is not the full repository suite.
Independent review and collector qualifications are retained with raw receipts.
The independent read-only reviewer additionally compared 520 exact before/after
cases, three source-error classes and 24 concurrent calls without finding memo
regressions. It reconciled all eight native tasks and all 71 HTTP ledger entries:
37 generation completions (25 client-closed SSE entities, 12 complete HTTP
entities), six failed generation POSTs with unknown usage. Both initial verifier
findings are repaired and independently rechecked; no blocking finding remains.

Consumption across **all eight native CLI tasks**, including TLS-affected and
rejected candidates: **918,610 reported input**, including **694,528 cached
input**, plus **3,825 output tokens**. There are 37 completed API requests and
six failed/incomplete attempts with unknown usage. All answers score 144/144
fields, but only the accepted-runtime subset supports the retained change.
Parent research/review/check consumption is separate, not assumed zero.

The real **575** current rows retain their logical hash; global Codex and
harness-mem configuration hashes match the start. No real-memory maintenance,
global installation, shared MCP reload, natural Hook, other-host model run,
release, commit or push occurred. Raw attempts remain in the ignored directory;
no user evidence was deleted.
