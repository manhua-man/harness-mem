# Native-host network stability, 2026-10-15

Status: **partial; full user outcome and matched performance comparison have
not passed**. Source version remains `0.9.28`. This work changes a scoped local
network route and an ignored experiment recorder, not the installed Codex
binary, harness-mem semantics, skill budget or real memory.

## Findings and applied repair

Mihomo service logs show actual `codex.exe` / `ChatGPT.exe` connections for
`chatgpt.com` selecting the existing AI group's Japanese AWS node and failing
to connect to its remote endpoint. A fast local socket connection does not
exclude this failure: TUN was enabled, so a nominal no-proxy test is not proof
of physical direct routing.

After testing actual models/MCP targets through existing alternatives, one
first-priority `DOMAIN-SUFFIX,chatgpt.com` rule now selects the existing US07
node. The persistent profile prepend and generated runtime configuration both
contain it. The controller accepted the reload with HTTP204 and new target
connections were observed on the intended chain. Existing long-lived connections
were not forcibly closed; future node availability is not guaranteed.

Byte-verified backups precede the change. YAML semantic comparison proves that
only the new prefix rule differs in the two affected files. All six manual
selector choices and seven protected files remain unchanged, including
Proxifier, Codex/harness-mem configuration and unrelated Clash profile assets.
Existing Grok/X and Antigravity rules were retained. No shared MCP service was
restarted. Backups and receipts are in the ignored directory
`.tmp/host-network-stability-20261015/`.

A second, separate fault was in the experiment's Node HTTP/2 recorder. After
a healthy route and early TLS/SETTINGS negotiation, a real 568,595-byte model
directory could still stall at 524,280 bytes (`65535 * 8`) and exceed native
discovery's five-second deadline. The new recorder negotiates bounded 1 MiB
stream / 4 MiB connection receive windows. A local control withholding
WINDOW_UPDATE distinguishes the old stall from the full transfer. It does not
change upstream bodies, TLS validation, authentication, native timeout, model
settings, context-window configuration or retry policy. The previous recorder
and its evidence remain unchanged. This is **not** an installed-Codex patch or
a forced/cached local model catalog.

## Verified scope

Three fresh native, zero-generation probes through the repaired recorder
receive HTTP200 and the same complete 568,595-byte directory, SHA256
`c6c9dcf61e3ac9d881988fed9312c0a72fd5036e2c0591bfc6cb8b15c01704da`.
Native discovery takes 0.840 / 0.633 / 0.815 seconds; total including readiness
is 1.372 / 1.182 / 1.596 seconds. The real Sol entry declares context window
500,000 and maximum 872,000. In the subsequent generated task, native events
consistently report effective window 475,000. This short series is not long-run
stability acceptance.

On the original official base, native discovery returns the same 14 installed,
enabled, callable apps. Real `codex_apps` MCP initializes with 618 tools and no
selected transport-close errors. The baseline also discovered those apps; this
does not prove all connector operations or prior retries repaired. `app/list`
still returns HTTP403. That directory failure is retained separately, not
relabeled as success or established as the missing-skill cause. A loopback
Apps-base experiment was rejected and is not used by the generated task.

The recorder's 23 tests pass, including exact entity hashes, retained partial
failures, no auth-header persistence or automatic replay, flow control and
shutdown. A separate gate test checks missing metadata/paths and exact valid
forwarding. These are recorder tests, not a full repository regression.
The isolated `bounded_current_memory_reading` outcome also passes: complete
facts, continuation and explicit full reading remain accessible.

## Same-task attempts and rejected comparison

Tasks use the same frozen 245-file runtime, 180 fictional sessions / 195,795
`o200k_base` source tokens, seven seeded facts, current-file override and
18-field final-answer oracle. Native settings and the twenty-tool memory
surface are not reduced. Actual order is A1, A2, then B1 after repair, not
randomized ABBA or cache-controlled.

| Attempt | Full wall seconds | Input / cached input / output | Effective window | Implicit skills | Answer |
| --- | ---: | --- | ---: | ---: | --- |
| Before A1 | 43.045 | 167332 / 129536 / 715 | 258400 | 212 | 18/18 |
| Before A2 | 30.489 | 109431 / 78464 / 498 | 475000 | 212 | 18/18 |
| After B1 | 24.672 | 100244 / 72704 / 424 | 475000 | 100 | 18/18 |

A1 has two model-refresh timeout diagnostics; A2/B1 have none. None has the
selected Apps transport-close diagnostic. A1 uses raw history rather than a
memory call; that unfavorable behavior remains recorded. B1's correct answer
and lower time do **not** make it an accepted sample: actual model requests
omit all 112 original curated-remote skill entries. No skill was manually
deleted, disabled, hidden by a budget override or replaced to obtain savings.

Native metadata-only investigation reports the plugins installed/enabled and
their cached files present. Within one app-server, `plugin/list(forceRefetch=true)`
then `skills/list` exposes 239 enabled skills. A later source-policy check
corrects the initial interpretation: 212 are implicit, matching the original
names exactly; 27 are explicit-only (20 templates, five Product Design helpers,
`grill-me` and `review-agent`). Enabled API rows are not proof of implicit
invocation. All 27 retain `allow_implicit_invocation: false`. This
normal native refresh updates its own cache/install metadata; it is not a
manual global skill/configuration edit. Another `debug prompt-input` process
still shows 100 and is not an exec acceptance gate.

The version-matched source has process-local remote-installed-plugin state and
returns empty remote configuration before that snapshot is available. This
supports an initialization-path explanation, not a proven account of the
specific earlier timing that allowed A1/A2 to include 212. There is no evidence
that the unchanged `capture_openai` alias itself disables plugins, or that the
remaining directory 403 caused this omission. Native details projecting null
skill paths are not by themselves mount failures. Sources:
[0.162.1 snapshot implementation](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/core-plugins/src/manager.rs),
[in-process startup](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server/src/in_process.rs#L517),
[native refresh test](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/app-server/tests/suite/v2/skills_list.rs).

A new frozen arm originally, incorrectly requires 237 implicit names and
existing expanded paths before forwarding generation. Its fresh CLI again has
only 100. The gate blocks forwarding; the exact native session independently
confirms the original 112 implicit omissions. Its reported 137 also includes
25 explicit-only names that should not appear by default. That gate assumption
is superseded, not the retained original failure evidence. The relay records
only two complete real model-catalog reads and **zero generation requests**.
This is not an answer-quality pass. An initial derived-report null-usage error
is retained; `blocked-gate-receipt.json` separately reconstructs metadata from
that exact native session, not an unpersisted rejected HTTP entity.

No further paid task or second candidate was run in that round. The correct
default acceptance roster remains the original 212 names, with the complete
239 enabled bodies and their invocation policies retained. No accepted speed,
token or billed-cost benefit is established by that round.

## Safety, accounting and remaining decision

Fresh checks preserve the logical hash of all 575 real current-memory rows,
global Codex/harness-mem configuration byte hashes, frozen runtime bytes and
seeded fixture knowledge. No weakened validation, Release, global installation,
version bump, commit or push is claimed.

The three generated task attempts total 14 completed provider requests:
377,007 input tokens (280,704 cached) and 1,637 output tokens, **378,644 total**.
This is experiment consumption, not savings. Catalog/discovery probes and the
blocked attempt generate no model responses. Parent/reviewer/research usage
is separate, not assumed zero. Provider SSE usage agrees with native totals.

Primary receipts: `.tmp/host-network-stability-20261015/report.json`,
`route-before.json`, `route-applied.json`, `final-models-{1,2,3}/`,
`native-after-route-tools.json`, `skills-native-refreshed-discovery.json`,
`verification/1-on/blocked-gate-receipt.json`, immutable baseline/candidate
captures and the isolated `outcome-report.json`.
`check-receipts.json` retains fresh TAP/unittest output and narrow structured
service-log observations with source paths, line numbers and file hashes.

Remaining: stable full remote-skill initialization in fresh native CLI,
the separate directory HTTP403, and then a new equal-catalog task comparison.
The network/recorder repair alone does not complete the request. A same-process
API initialization/execution path would change the measured workflow; patching
or replacing the installed CLI is a separate host-wide scope decision. Do not
silently change the global binary, copy skills to another store or continue
generating favorable samples with missing skills.

The operator subsequently authorized an isolated CLI source/build repair, not
replacement of the installed executable. That follow-up corrects the implicit
skill interpretation, passes five fresh-home bootstrap checks, but still fails
the same task at private elevated sandbox setup. Its separate failed paid
attempt, cleanup and remaining authorization boundary are recorded in
[Isolated Codex CLI startup repair](codex-cli-startup-20261015.md). Do not fold
that round's token consumption or partial verdict into the earlier three runs.
