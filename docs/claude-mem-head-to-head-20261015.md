# Isolated Claude-mem pilot — 2026-10-15 (incomplete)

## Result

Subsequent bounded repair: [first-source construction and non-promotion
replay](memory-construction-repair-20261015.md). It fixes the known-session
inventory and false `no_write` deferrals and records a fresh native run; it
does not complete or replace this unfinished full comparison.

No accepted end-to-end head-to-head result. Both products began empty and made
real model-generated writes from the same first fictional conversation. The
180-session construction did not finish; correction and the common retrieval
task were not run. Do not interpret those unrun stages as zero-cost successes,
reuse the earlier pre-seeded ON/OFF result, or claim a speed, billing or quality
winner from this pilot.

The operator requested identical original conversations and a common task,
self-generated memory on both sides, construction/correction/retrieval costs,
and no global configuration or real-memory changes. This outcome remains
partial against that request.

## Frozen inputs and native paths

- 180 original fictional history files, 994,655 UTF-8 bytes. Corpus seal:
  `7bee5ab1525d5fc79425a380839c4d497063d684f02e69d10fd104115cdf2b28`.
  Only original files were reused; none of the earlier seven semantic answer
  rows were seeded. A separate 23-to-27-day correction remained held back.
- Both arms received byte-identical history files and current workspace
  overrides. The common task has 18 fields and requires explicit unknowns.
  The evaluator answer key was not given to either model.
- HM used a frozen workspace runtime, the existing path-guarded native MCP
  adapter, and all 20 public tools. Python-source fingerprint:
  `e0c2a5c51ca81acb47ac1466d023b1088d99687c0180c2bbbec850d044886220`.
  Native manual distillation kept all 239 sealed skill/body/policy contracts
  (212 implicit, 27 explicit-only). No skills were removed to lower cost.
- Claude-mem used the official `13.39.0` checkout at
  [`fef3402e674bebbf72a23aeb735e91c92cd34afd`](https://github.com/thedotmack/claude-mem/tree/fef3402e674bebbf72a23aeb735e91c92cd34afd),
  its bundled worker and native Codex provider, private data/profile/cache
  roots, and loopback port 52646. Its default local Chroma path was retained.
  No global installer, existing global daemon, or import of distilled answers
  was used.
- The observer received each entire original file as an official native `Read`
  observation. Reopened SQLite and the original captured HTTP replies confirm
  the first raw tool response and its observation join. This is replayed API
  ingestion, not a natural Hook or real-history qualification.
- Captured inference requests use `gpt-6.1-sol`, `high`, and `priority` in both
  arms. A task-local executable forwards CM's original app-server invocation
  through an entity recorder without changing semantic prompts or store writes.
  The installed global CLI was not replaced.
- The model envelopes are not identical: HM is its native manual host with the
  full skill catalog; CM is its dedicated native observer. This is a native
  workflow pilot, not an identical-prompt ablation. The planned common consumer
  with a full catalog on both sides was not reached.

## Observed first-source results

| First-source phase | HM native manual distillation | Claude-mem native observer |
| --- | ---: | ---: |
| Real inference requests with reported usage | 13 | 2 |
| Input tokens, including cache hits | 642,181 | 14,498 |
| Cached input tokens (subset of input) | 580,608 | 0 |
| Uncached input tokens | 61,573 | 14,498 |
| Output tokens, including reasoning | 4,907 | 707 |
| Reasoning tokens (subset of output) | 2,334 | 112 |
| Total reported tokens | 647,088 | 15,205 |
| Recorded phase wall seconds | 180.237 | 211.695 |
| Durable readback | 1 current knowledge row | 1 observation and 1 summary |
| Native processing state | finalized; organization partial | session completed |

These outputs and completion criteria differ. The CM wall includes its native
three-minute idle-finalization interval and a checker error after generation;
the observation and summary were persisted earlier. HM includes native manual
instruction reading, point-level governance and one recovered fixture-adapter
tool rejection. This table is not an accepted speed or billing comparison.

### Why HM remained partial

The Agent submitted seven non-durable transcript points with `verified` and
`no_write`, alongside one independently verified user-statement memory. The
current evidence gate demotes transcript evidence to `unverified` with
`transcript_cannot_verify_durable_truth`. The assimilation path admits ordinary
decisions only for `ANSWERED` points, so the seven `no_write` decisions became
`defer`. Native finalize returned `distill_status=completed`,
`organization_status=partial`, and `readback_verified=true`; it did not declare
all organization complete.

The raw missing-label follow-up also remained a handoff. It is not evidence that
the original task was fixed. Public Review has a native route for an Agent to
decide `no_write` or `reject` without promoting unverified knowledge, but no such
semantic decisions were filled in by the benchmark driver. This pilot does not
prove that reviewing those candidates would retroactively change the finalized
session's original partial receipt.

Relevant frozen owners are `commands/evidence_admission.py`,
`commands/separated_assimilation.py`, and `commands/knowledge_assimilation.py`.
This round did not patch any product implementation to improve its score.

## Failed, interrupted and fixture-induced work is retained

1. CM's first Bun startup failed before model use because the isolation driver
   omitted Windows `SYSTEMROOT`. A controlled minimal-environment probe
   reproduced the crash and showed that adding that variable fixes it. This is
   a benchmark-environment defect, not a CM product loss.
2. HM's first request was blocked before inference because repository ancestor
   discovery added a duplicate `hm` skill. Local Git roots in both fixture
   workspaces removed the accidental ancestor scope; the 239 original contracts
   remained intact.
3. HM's next real request returned `server_is_overloaded`, with no usage. It is
   not assigned zero billing. One later same-model attempt produced the
   first-source result above.
4. A CM recorder startup failed during TLS negotiation before any generation.
   A later recorder startup succeeded. The failed receipt is retained.
5. The CM first-source runner incorrectly expected `content_session_id` in
   both public response shapes. Native summaries use `session_id`. The checker
   mapping was corrected, then independently checked against reopened SQLite
   and the already captured HTTP responses, without rerunning generation.
   This is not a fresh HTTP readback claim.
6. The pilot replay omitted `summarize.last_assistant_message`, producing a
   native warning. Its `Read` observation still contained every original user
   and assistant message. This adapter defect further limits the pilot; it is
   not classified as a CM generation failure.
7. The subsequent HM full-batch attempt was explicitly interrupted. Its prompt
   asked for chronological replay, but native frozen batches sort by
   `(client, session_id, source_id, source_revision)`. Its attempts to add a
   session selector to that active batch were correctly rejected. A comparison
   must resolve this driver/order conflict before a full matched run, without
   changing native ownership rules. This attempt made no additional current
   knowledge row; all observed provider work is retained below.

## Complete observed native-provider ledger for this attempt

| Attempt | Provider requests | Requests with usage | Input | Cached input | Output | Total with reported usage |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| HM overloaded attempt | 1 | 0 | unknown | unknown | unknown | unknown |
| HM first-source run | 13 | 13 | 642,181 | 580,608 | 4,907 | 647,088 |
| HM interrupted batch attempt | 13 | 12 | 769,199 | 694,144 | 2,133 | 771,332 |
| CM first-source run | 2 | 2 | 14,498 | 0 | 707 | 15,205 |
| Reported-usage subtotal | 29 | 27 | 1,425,878 | 1,274,752 | 7,747 | 1,433,625 |

The overloaded request and one interrupted request have no provider usage;
their token/billing amounts remain unknown. The reported subtotal is not a
complete bill. Cached input and reasoning output are subsets, not extra tokens
to add a second time. Completed HM native CLI usage agrees with the captured
provider totals. A recorder `ClientAbort` after an observed
`response.completed` does not erase that terminal usage; it remains annotated.

These are native arm-provider tokens, not currency charges. Subscription CLI
usage does not provide the actual monetary debit. Benchmark-development/main
Agent/subagent usage and local setup/download resource charges are not included
in this native-provider ledger. No fixed character divisor, estimated dollar
price, or presumed free failed request is substituted for missing data.

Correction, retrieval accuracy, retrieval latency and the complete
build-plus-correction-plus-retrieval cost remain unmeasured. There is no
amortization or break-even claim.

## Isolation and cleanup

All 575 real current knowledge rows retain the protected baseline's logical
hash. Global HM/Codex configuration, global CM settings/PID files, global CLI
binary and shared proxy configuration match the before snapshot. The task
proxy and remaining task-owned processes were stopped. Six disposable private
credential/configuration copies were removed; their originals remain in their
protected locations. Original fictional sources, generated isolated stores,
failed attempts, raw captures and review receipts remain available.

This is not a claim of zero host ACL/account/service effects. The run reused a
previously provisioned private native sandbox; no new host sandbox preparation
or global account reset was requested here.

## Receipts and next decision

Ignored task root: `.tmp/claude-mem-head-to-head-20261015/`.

- `fixture.json`, `protected-before.json`, `partial-report.json`.
- `hm-build-smoke-v3/`, `hm-build-smoke-v4/`, `hm-build-remaining/`.
- `cm-startup/`, `cm-startup-v2/`, `cm-build-smoke/`,
  `cm-build-smoke-v2/`, `cm-build-smoke-v2-replay/`.
- `cleanup-receipt.json`; task-proxy stop receipt in the earlier private CLI
  task root.

Before another paid full comparison, decide whether to repair the HM
non-durable-point closure behavior or intentionally benchmark it unchanged with
partial results. Separately correct the replay/ordering adapters and freeze a
matched order. Any subsequent clean-store run must include its own construction,
correction and retrieval ledger and retain these earlier incurred attempts.
