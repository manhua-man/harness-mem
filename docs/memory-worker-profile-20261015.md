# Scoped background memory execution, 2026-10-15

## Outcome

The authorized background Codex executor now uses a call-local JSON decision
profile instead of inheriting the interactive coding Agent. The same first
original fictional conversation completes extraction, per-point verification,
assimilation and persisted readback with its project scope intact. This repairs
the background execution cost and source-completeness boundaries; it does not
change manual organization into unattended execution.

In the final same-worker comparison, only `host_cli.py` and
`host_structured_cli.py` differ between arms. Both arms include the same complete
source projection and scope-preservation repairs, model `gpt-6.1-sol`, reasoning
`high`, tier `priority`, selected original source, empty initial store, runtime
validation and current-knowledge write contract. Three semantic stages remain;
none was skipped to match Claude-mem's two-call observer.

| Complete background phase | Before profile repair | After profile repair |
| --- | ---: | ---: |
| Provider requests with complete reported usage | 3 | 3 |
| Input tokens | 72,565 | 15,036 |
| Cached input tokens, subset of input | 0 | 0 |
| Output tokens, including reasoning | 1,446 | 1,388 |
| Reasoning tokens, subset of output | 727 | 712 |
| Input plus output | 74,011 | 16,424 |
| Complete runner wall seconds | 111.201 | 61.744 |
| Original messages read completely and in order | 28/28 | 28/28 |
| Current knowledge rows after independent reopen | 1 | 1 |

Observed total tokens fall 77.81% and phase wall time 44.48% in this single pair.
There is no cache-input difference in this pair, but it is not a distributional
latency, tail-reliability or currency-cost result. Provider request/response
entities and native CLI totals agree. The code fingerprints are
`bb01186b6bfcaea124a74233d4dc42d210906cb8e229c8be740b9888b074bf6c`
(before) and
`737d63078716c8ae0fcd664ebc633d00a1dd45ec18fdc3209be0e3514b935ea6`
(after). Current workspace Python files match the final after seal.

The earlier Claude-mem observation-plus-summary sample was 15,205 tokens. This
new background sample is about 1.08 times that token count, rather than the
manual host's earlier 19.5 times. This is a historical, different-completion-
contract comparison, not a fresh matched Claude-mem win. The manual 296,051-token
sample is also a different execution path and is not the before arm above.
The full 180-session construction, held-back correction and shared retrieval
task remain unrun.

## Implementation boundaries

- Reuse `HostStructuredCliProvider`, the existing authorization switch and
  three-stage worker. There is no new public tool, model provider, knowledge
  store or parallel distillation workflow.
- For one Codex JSON call only, turn off project documents, interactive skill
  instructions, plugin/MCP/Hook loading, shell, browser and delegation features.
  A temporary task-specific instruction file replaces the generic coding-agent
  instructions. The operator's configured model, endpoint, credentials and
  global configuration are not rewritten. All 239 original body/policy
  contracts remain installed and byte-checked; daily manual Agent discovery is
  unchanged. Minimal native built-in tool definitions still exist on the wire;
  do not describe this as an empty tool schema. Attempted tool activity makes a
  returned decision unacceptable for the checked command/MCP/file/browser/
  collaboration event types even if its JSON is valid. This post-result guard
  and the tested no-tool trace do not prove a universal pre-execution tool deny.
- Complete native evidence is projected once using the existing complete MCP
  reading projection. Both the provider manifest and verification excerpts
  preserve intermediate assistant messages before the final assistant outcome.
  Complete exchange windows do not also resend a duplicate source outline.
  Reference hashes and author/source bindings remain unchanged.
- Extraction explicitly retains the source's subject, project, version and
  conditions, citing the contextual exchange with the actual decision.
  Verification treats missing subject/scope as incomplete support; assimilation
  preserves the verified subject in the knowledge statement, not just its
  module. This is a source-supported wording requirement, not a hardcoded
  project-name rule or evidence bypass.

The final stored fact expressly applies to Aster Harbor's replacement approvals.
Neither arm infers archive retention, SLA or other unprovided settings, or marks
the historical missing-label follow-up resolved. Each store is checked through
a new public MCP process, readonly SQLite reopen and both Note hashes. Only
runtime-verified current knowledge is returned by normal search.

## Rejected and failed work remains visible

The first calibration completed three CLI calls but the recorder captured none.
Its CLI reported 19,158 total tokens; the actual model/provider usage was not
independently established, so it is excluded, not counted as free. Later task
transport arguments and executable identity were checked, and complete request
entities were required before accepting a measured result.

The next frozen pair exposed a deeper completeness gap: the background prepare
path bypassed complete Agent projection and supplied only three signal-selected
windows, six original messages out of 28. A helper-only fixture had passed while
the actual worker still omitted evidence. That pair's 15,040 after / 72,422
before tokens is rejected. Its after knowledge also omitted Aster Harbor's
subject and became too broad; it is not a quality success. The current repair
adds an actual native-file-to-worker regression and new model runs, not just
stronger wording around the rejected output.

Two before-arm recorder startups reset during TLS negotiation, before any model
generation; their original summaries remain. Another before attempt had the
complete model directory but lacked two bundled skill entries because the test
forwarder omitted the original marketplace source override. The gate blocked
generation until all original contracts were restored. No global routing or
skill deletion was used. Explicit task-proxy CONNECT avoids the earlier direct
model-directory path, but these TLS failures mean general network stability is
still not established.

All captured attempts, including rejected samples, report 177,897 input-plus-
output tokens; the uncaptured first run's CLI-only 19,158 is listed separately.
Those are execution receipts, not currency charges or the whole engineering
cost. Operator/subagent development work is outside the native-arm ledger.
Successful-phase timings in the table are not retry-inclusive project duration.

The selected partial-handoff outcome initially failed because its old checker
depended on compact output fields that are no longer public. The checker now
requires exact persisted knowledge, normal search and a source/job-bound
persisted readback plus handoff; it does not restore verbose public output or
weaken the evidence check. The original failure receipt is retained.

## Checks and delivery scope

171 affected-scope tests across eleven files pass, including the native worker
coverage and scope contracts, JSON task isolation, authorization, process/Hook
boundaries and compact outcome negative cases. Scoped Ruff and five-file Mypy
pass. `partial_distill_handoff` and `multi_point_memory_assimilation` direct
isolated outcome claims pass; neither proves seven live clients or natural Hook
acceptance. The version remains `0.9.28`, unreleased.

No global installation, shared MCP reload, user-home instruction synchronization,
real-memory maintenance, commit or release is part of this change. All 575 real
knowledge rows and protected global configuration/CLI/proxy hashes are compared
with this turn's fresh baseline. Task credential/config copies are removed and
the private proxy is stopped after verification; all source files, isolated
stores, wire captures and negative evidence are retained. Prior separately
authorized sandbox account/ACL/service changes are not claimed reverted.

Receipts: `.tmp/memory-worker-profile-20261015/verification.json`,
`after-three-verification.json`, `before-five-verification.json`,
`all-attempts.json`, `outcomes-current.json`, final source seals and
`restoration-receipt.json`. The earlier manual repair is documented in
[the construction report](memory-construction-repair-20261015.md).

The scoped Codex configuration was checked against the local same-release CLI
source and [official configuration documentation](https://learn.chatgpt.com/docs/config-file/config-reference).
