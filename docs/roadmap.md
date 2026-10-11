# harness-mem Roadmap

This roadmap distinguishes released capabilities, unreleased working-tree
changes, and the next delivery train. Separately authorized legacy convergence
remains independent. This document never authorizes mutation of real user memory by
itself; normal runtime paths do not migrate legacy data.

## Current source and release line

The current source package is `0.9.28`; published artifacts are listed on the
GitHub Releases page. This release line provides session lifecycle, lossless
extraction, per-point verification, transactional SQLite current knowledge,
job-scoped processing material, clean retrieval, and one governed Review/Dream
feedback path. Legacy `MemoryEntry` rows remain readable for compatibility, but
new clean knowledge no longer stores candidate, evidence, decision, and truth
as one object.

Authorized background work now runs through `distill.autonomous.enabled=true`
and a project-selected host CLI with honest `{host}_cli` receipts. HTTP profile
transport is no longer part of the product path.

The normal user surface is one `hm` entry. Quickstart installs that entry once
for each Agent app and leaves MCP ownership to the Agent, Router, or plugin
already in use. Hooks only dispatch detached work; a failed dispatch or unknown
host is reported without running model work inside the Hook or selecting a
different host.

## Next train: complete session organization with less friction

The agreed goal is to let users ask `hm` to organize their work and receive
readable, verified project knowledge with fewer user steps, fewer unnecessary
Agent calls, and less repeated output. End-to-end capability and surface
simplification are one goal, not competing directions. No release version or
target tool count is assigned to this train yet.

As of 2026-10-07, inventory and resumable manual batches already have
implementation and isolated fixtures. The next iteration should prove that
users can see the saved knowledge immediately, find it during later work, and
resume an interrupted organization request without managing internal steps.
Upstream parity is not required for the user's current functional acceptance.

The upstream is [session-distill-skills](https://github.com/manhua-man/session-distill-skills).
Use its actual multi-host intake, verification, organization, progress and
recovery paths, not just its report formatting. Its example reports are UX
references, not evidence that harness-mem has implemented or verified those
outcomes. Retain this project's SQLite authority, current-knowledge-only model,
source integrity and authorization boundaries; do not copy fixed batch limits,
Markdown authority, or automatic commit/push behavior.

### Current acceptance: one working host is enough

On 2026-10-07 the user clarified that Codex running normally is sufficient:
one supported host/adapter completing the core memory path counts as passed.
The selected Codex path has a real CLI preflight and isolated Hook/worker run,
persisted SQLite knowledge and a job-bound Note, ordinary-search readback, and
a real readable completion reply. At that review the source fingerprints,
ordinary MCP title/body readback and Note digest matched. That revision met the
one-host functional criterion. The 2026-10-08 evidence/display fixes below change
the runtime fingerprint; the earlier model/Hook report remains historical and
does not verify those new bytes.

All-host acceptance, paired upstream comparison, a natural Desktop Stop event
and repeated performance measurements are not prerequisites for this criterion.
Keep them as separate follow-ups only when requested or when making the
corresponding compatibility, native-trigger or performance claim. Do not label
Codex unusable because a separate comparison collector failed to start. This
decision does not assert that every host works or that time/token use improved,
and does not replace package safety/regression or publication requirements.

### Status: released, implemented, and planned are different

| Scope | Status | Evidence boundary |
|---|---|---|
| `0.9.28` capabilities described below | Released baseline | Historical release evidence does not validate later working-tree changes |
| Automatic retrieval returns one memory projection and usable feedback references; finalize returns one top-level Answer Packet | Implemented in the working tree, unreleased | Focused tests passed; the Codex Hook run below proves one background write/readback, not all automatic-retrieval and manual UX paths |
| Public MCP contains 20 tools: the previous 19 plus `inspect_sessions`; automatic Dream tick remains internal | Implemented in the working tree, unreleased | Published 0.9.28 also has 20 tools but includes `dream_auto_tick` instead of `inspect_sessions`; equal counts do not mean equal contracts |
| Diagnostic stages no longer inferred from `completed`; actual provider/readback boundaries and task-local correlation | Implemented in the working tree, unreleased | Focused tests passed; missing boundary evidence remains a gap, not an inferred success |
| Read-only inventory, complete source paging, theme coverage, frozen manual batches, progress and knowledge-change reports | Implemented in the working tree, unreleased | Focused synthetic fixtures; integrated outcome and release acceptance are separate gates, not inferred from implementation |
| Codex CLI preflight and isolated Hook-to-knowledge-to-search flow | Passed on the recorded `6940734...` fingerprint on 2026-10-11, unreleased | Real CLI, isolated Hook, SQLite/Note and ordinary search matched; later retrieval/onboarding fixes need their own checks and do not inherit that model/Hook verdict |
| Readable completion and on-demand current knowledge | Implemented and narrowly verified on 2026-10-07, unreleased | Isolated manual runtime outcomes and one real Codex completion reply; not all native Agent interactions |
| Frozen matched quality corpus and offline result comparison | Implemented in the working tree, unreleased | Seven fictional sources and 17 independent oracle points; no actual paired product run or comparative quality verdict |
| One working host/CLI core memory path | Codex met the agreed one-host criterion on 2026-10-11 | Recorded CLI/Hook core-chain evidence supersedes the earlier local occupancy blocker; not live-history quality, all-host or release acceptance |
| Manual/background ownership and current-project archive totals | Repaired and isolated-runtime verified on 2026-10-09, unreleased | Frozen manual selections stay out of background dispatch/claims; stored absolute roots scope terminal totals; the separate Codex core-chain pass does not prove every manual/archive path |
| Matched upstream quality/ease comparison and lower end-to-end overhead | Optional follow-ups, not current pass criteria | Comparative or performance claims still require their own real measurements |

### Current usability work (2026-10-12, unreleased)

The operator authorized four bounded repairs and an ordinary commit/push, not a
release, version bump, new capability or real-memory maintenance:

- Installation examples are single-line commands for PowerShell, Command Prompt
  and Bash. Quickstart explains the handoff to the existing MCP manager without
  inspecting or changing connections.
- First-use status names known setup failures and one safe recovery action. It
  distinguishes memory storage and prepared Hook files from actual execution;
  Codex's trust reminder is conditional and remains available after first use.
- Current-knowledge search handles unsegmented Chinese questions with bounded
  lexical matching. The Agent reformulates empty queries; synonym understanding
  and comparative retrieval quality are not claimed.
- This current status table replaces stale top-level blocked summaries. The
  dated failures below remain historical evidence, not the present verdict.

Verification is scoped to these changed paths and isolated current-knowledge
boundaries. The 2026-10-11 model/Hook reports remain tied to their recorded
fingerprint; they do not validate subsequently changed runtime bytes. Package,
upgrade, native-trigger and release acceptance remain separate.

### Product review: remaining priorities, not additional implementation

The product purpose remains helping Agent users remember reusable project
decisions, find them during later work, and correct them without managing a
second application. Keep the single daily `hm` entry. Source inspection and
recovery remain on-demand; Doctor, configuration and deletion stay operator
actions; jobs, leases and receipts stay internal. Low frequency alone does not
justify removing a source-verification or recovery operation.

The four usability repairs do not close these wider quality directions:

1. **Reliable everyday results.** Use the existing isolated sources and three
   daily intents to observe actual Agent replies for saving, later recall and
   correction, including ambiguous targets, no-write and partial completion.
   Runtime fixtures prove persistence and boundaries, not that ordinary users
   consistently receive enough information without asking again. Keep exact
   keyword and negative-query controls when comparing retrieval changes.
2. **Less repeated work.** Inspect existing per-call traces before reducing
   source, knowledge or instruction repetition. The recorded one-host Hook
   baseline is about 71 seconds and 86,644 CLI-reported tokens, not billed cost
   or a general performance verdict. Do not merge independent judgments or
   truncate complete source access to obtain a smaller number.
3. **Predictable installation and upgrades.** Before any later release, prove
   the newly built package's clean installation and upgrade paths, and keep
   published-versus-development tool changes explicit. Current MCP discovery,
   client commands and installed executables must refer to the intended package;
   existing local-environment first-use evidence is not a new wheel acceptance.

These are follow-up observations and adjustments in existing owners, not a new
dashboard, another entry, a fixed tool-count target or an authorized release.

The first implementation package now projects `knowledge_changes`, ordinary
`not_written` reasons and `unfinished_work` directly from verified current rows
for both finalize and batches. A blank project query through existing
`search_memory` lists current knowledge with natural modules; normal search
remains title/statement only. Canonical `hm` instructions and generated mirrors
require concrete saved knowledge in the completion reply. After these source
changes, a fresh F2 preflight and isolated Codex Hook run passed against the same
runtime fingerprint. The job persisted one current item, a job-bound Note and
normal-search readback; all three Hook reentry challenges were blocked with zero
new jobs. A separate real Codex reply consumed the verified completion, directly
showed the exact saved title/body and exposed no internal material. The current
knowledge view matched the SQLite result. This reply preserved English knowledge
as explicitly requested; it does not prove all user-language or native UI paths.
Current artifacts are
`.tmp/codex-visible-20261007/{fingerprint-fixed-hook,fingerprint-fixed-reply}.json`.
Independent review found that the earlier runtime fingerprint omitted new
display dependencies. The fingerprint now includes result generation, search,
projection, current-knowledge reading/storage and canonical `hm` instructions;
six in-memory drift cases invalidate it. The reply check rejected the earlier
report before backend/provider work. Preflight, Hook and reply were then rerun
on the new fingerprint; earlier reports are retained, not reused as proof.

The existing `manual_session_batch` and `clean_retrieval_boundary` outcome claims
also passed against isolated stores. `fingerprint-fixed-contract.json` applies the existing
background Hook assertions to the fresh report, without another model call; it
is not a full outcome or release run. This Hook took 76.36 seconds, with 104,489
input plus 795 output tokens reported across its three semantic phases. The
23.138-second preflight and 14.148-second reply check are separate. These single
runs are not a measured optimization or a billed-cost comparison.

The matched quality corpus is frozen at seven fictional sources and 17 points
(seven current knowledge, three handoffs, six no-write and one conflict). The
offline scorer validates full-source coverage and exact or explicitly
human-attested result associations; unknown cost/operation measures remain
unknown. It never runs either product or verifies attestation semantics,
readability or recovery itself. Usage and acceptance boundaries are in
`docs/distill-test-plan.md`, section 9. Neither a scorer test nor this one-point
Hook/reply establishes that either product has won the quality comparison.

The working tree adds a thirteenth `manual_session_batch` probe to the original
12 outcome contracts. Its configuration and execution result must be recorded
separately from the historical 0.9.28 outcomes and background Hook acceptance.
Manual work belongs to the current Agent and does not require the background
CLI. `prepare_session_distill(batch_sessions=...)` freezes selection;
`batch_id` resumes it and `retry_failures=true` retries only active-batch
failures. Runtime identity and source revisions remain pinned. Batch completion
does not delete sources or attribute previously completed knowledge to this run.

On 2026-09-24 the scoped `manual_session_batch` outcome probe passed against
synthetic sources and an isolated durable store. It exercised resume, real
verification/assimilation, store close/reopen, ordinary MCP retrieval, readable
changes, and unchanged sources; Agent semantic decisions were deterministic.
The probe records tool-call and response-character samples. Its same-result
projection comparison measures removal of the duplicate nested Answer Packet,
not an end-to-end speedup or a reduction in all workflow calls. Regression
fixtures separately cover interrupted reads, interruption after the knowledge
commit but before its completion receipt, later replacements, preserved task
handoffs, source failures and explicit retry. These are not live-history or
background-CLI acceptance claims.

Cursor SQLite intake now has isolated schema, workspace membership, snapshot,
unsupported-layout and read-only diagnostic fixtures. The developer-only
prefix benchmark checks exact result equality and the query plan before timing
synthetic data; its method and recorded samples are in
`code/tools/harness-mem-debug/README.md`. Real Cursor history and native database
cleanup are not covered by this acceptance.

The Hermes attempts on 2026-09-24 and 2026-09-28 stopped at the model preflight:
the endpoint returned HTTP 400 for missing `x-opencode-session`; neither started
the full Hook. Hermes remains unresolved and is deferred at the user's request.

On 2026-10-07 the user explicitly selected Codex for testing. A separate
synthetic project used `cli="codex"` and isolated data/Notes; the normal project
configuration retained Hermes. The corrected run passed F2 preflight, then
invoked `post-turn-maintenance` through the existing Hook entry and detached
worker. The same job produced one SQLite knowledge item, a meaningful job-bound
Note, and an exact title/statement hit through ordinary MCP search. All three
Hook reentry challenges were blocked and created zero downstream jobs. Runtime
fingerprints before/after matched, and receipt runtime/config checks passed.
The synthetic job/session and its Note were absent from the usual ledger/Note
locations; this check is not a before/after audit of the entire live database.

The first attempt used inconsistent project names and a different subprocess
runtime, and failed before semantic processing. Its evidence is retained; the
corrected run explicitly aligned the staged project name with the directory
name and loaded repository code in subprocesses. It does not combine successful
pieces from the first attempt. Local, Git-ignored artifacts are
`.tmp/codex-acceptance-20261007/corrected-report.json` and `contract-report.json`.
The latter applies the existing `background_memory_hook_flow` assertions to
that fresh report without another model invocation; it is not a full run of
all outcome contracts. Reproduction uses
`code/scripts/run_release_hook_acceptance.py`, a separate project config,
matching project name/root, and the same repository runtime in child processes.

This single Hook run took 76.62 seconds. Its three semantic phases reported
104,549 input and 752 output tokens (105,301 total), with 73.253 seconds of
provider duration. The 24.158-second F2 preflight is separate. These are
CLI-reported usage and one-run timings, not billed cost or a general performance
claim. The dominant repeated input must be measured before blaming prompts,
tool schemas, host configuration, or the number of semantic judgments.

### Delivery sequence

The same-source manual comparison collector is now available as development-only
`code/scripts/run_matched_memory_comparison.py` and `matched_memory_host.py`.
It pins the upstream commit, supplies all seven complete fictional sources and
the same three initial knowledge items, separates evaluator answers from both
execution roots, and preserves native tool calls and pre-close artifacts. Both
products retain their own verification and storage rules; only source/output
paths are adapted. It is not a second public runtime or a quality result.
Answer files are excluded from supplied inputs, but the Agent's terminal is not
proven to have OS-enforced read isolation; record actual access and possible
contamination before making a semantic comparison claim. Preflight success
requires native evidence, not a marker substring, and frozen inputs/configuration
and upstream source bytes are checked before every model invocation and
immediately after a workflow.

The first attempted collection on 2026-10-07 stopped before model startup:
Codex rejected temporary MCP overrides with `invalid transport`. The invocation
had quoted dotted key segments, which its override parser treated as different
server names. No workflow or upstream model sample ran. The failure is retained
under `.tmp/quality-compare-20261007/actual-pair-01`. The collector now uses bare
validated key segments and the same installed npm launcher without the Windows
batch quoting layer. A read-only `codex mcp list --json` configuration check
passed with only the isolated memory server enabled; it starts neither a model
nor an MCP server. After the user explicitly requested the actual comparison,
a fresh attempt under `.tmp/quality-compare-20261007/actual-pair-02` started the
configured Codex model. Its first read-only `inspect_sessions` call was denied:
the MCP tool required approval while the noninteractive CLI policy was `never`.
The preflight took 29.098 seconds and reported 60,085 input / 247 output tokens;
no distillation workflow or upstream model sample ran. CLI exit zero and a
completed model turn did not pass the native-evidence gate. Only the isolated
server's per-invocation tool approval setting was then corrected. Neither
attempt is a quality result.

After explicit user authorization, `.tmp/quality-compare-20261007/actual-pair-03`
passed a fresh native preflight (44.815 seconds; all seven sources readable).
The real manual workflow ran for 246.382 seconds and reported 607,866 input
tokens, of which 553,984 were cached, and 5,341 output tokens. It closed only
F10 and F9: no new or replaced knowledge, the three seeded entries unchanged,
and one deferred audit preference in the task area. The F9 user-statement
reference omitted `role="user"`; the runtime evidence gate derived `PARTIAL`,
not permission to write. Five other sessions did not reach processing, so the
collector's persisted-artifact gate stopped the upstream sample. A fresh normal
MCP search found the three existing facts and no new audit preference; the two
job-bound Notes were readable and their hashes matched. All original sources
remain intact. This is a **partial real attempt**, not a paired quality result;
the CLI's successful model turn does not establish workflow completion. No
automatic retry or second-product model call followed.

Independent read-only review also found a result-expression defect: F9's
finalize response returned a real deferred handoff but reported `no_candidate`
and empty unfinished work, while its Note claimed verification and no open
work. This is not the cause of the reference rejection; it is a separate
misleading display issue. Runtime proof and findings are retained in the
ignored run's `evaluator/attempt-review.md`; the input and result must not be
rewritten to turn this failed sample into a pass.

On 2026-10-08 the user authorized fixes to these two boundaries. Missing author
metadata in a user-statement reference may be derived from the frozen source;
this currently covers supported structured Codex/Cursor sources. Legacy text
and other hosts keep explicit-role compatibility, not automatic author proof.
Role-delimiter injection conservatively rejects the ambiguous source as a whole;
explicit conflicting roles, unavailable sources and changed digests must still
block writing. Completion now distinguishes deferred/conflicting work and task
handoffs from an absence of durable candidates. Notes, single-session replies
and batch reports use runtime validation and persisted job-bound unfinished
work, not an Agent's unsupported success claim. Isolated runtime regressions
cover a saved preference, verified `no_write`, retained work in a new batch,
a rejected digest, mixed independent points, Note
hashes, reopen/replay and ordinary search. These are deterministic Agent
fixtures, not a rerun of the seven-session model comparison or background Hook.

Later on 2026-10-08, the user authorized Codex validation in a new isolated
directory, `.tmp/codex-reverify-20261008/`. The F2 real model preflight made one
attempt and failed with `codex provider exceeded 300s`. A decision file was
observed during execution, but the process communication did not complete;
this does not establish a successful or schema-validated model result. The
full Hook and subsequent manual model workflow were not started, and no
automatic retry followed. The existing `background_memory_hook_flow` outcome
assertions report blocked because the failed preflight prevents the dependent
Hook check. Three unchanged fictional F8/F9/F10 sources were prepared for
manual validation only; preparation is not processing. This attempt changes
neither the production project's Hermes choice nor real memories or previous
experimental outputs. The exact cause of the CLI exit/wait timeout remains
unproven; current-code end-to-end acceptance is still outstanding.

The user then authorized continued diagnosis and repair. In a separate ignored
directory, `.tmp/codex-pipe-fix-20261008/`, a new F2 check passed in 26.226 seconds
with reported usage of 28,562 input and 253 output tokens. Its Hook failed before
background model execution: the test command's project name did not match the
profile resolved from its project directory (`attempted=0`). The subsequent
binding-corrected attempt failed during F2 scratch-directory removal with
Windows error 32 and did not materialize a model-check or Hook report. Model
calls stopped; the manual workflow remains prepared but unexecuted. The first
report and negative attempts are retained, not combined into a successful chain.

The local repair disables configured MCP servers for each Codex JSON-only call
without modifying CLI settings; it captures stdout/stderr in temporary files
instead of waiting for inherited pipe EOF. On Windows it starts the CLI
suspended, assigns it to an anonymous Job Object with kill-on-close, and only
then resumes execution. Cleanup terminates that invocation's assigned children,
not other Codex sessions. Lease registration now follows stream allocation.
Codex TOML reading is lazy and accepts `tomli`; the package and lock declare it
for Python below 3.11. This is not full Python 3.9/3.10 runtime qualification.
Thirty-nine focused tests include actual early-spawning local processes, cwd
release, a crashing worker, and unchanged nonzero/schema/timeout rejection.
Scoped Mypy/Ruff, compilation, four version checks and offline lock validation
also passed. These tests prove the controlled mechanism, not which process
held the original invocation's handles. The repair changes the fingerprint
again: no model or complete Hook has run against these latest bytes. Existing
Hook assertions applied only to current evidence availability report `blocked`;
no broad test lane or release gate ran. Details are in the ignored
`attempt-review.md` and `current-contract-report.json` under that directory.

On 2026-10-09 the user authorized fixing readable corrections and independent
point handling. `govern_memory` now accepts `target_knowledge` containing the
old title, statement and optional module from ordinary search; internal IDs
remain compatible but are not required from users. Exact, unique project-scoped
matching is required. A missing, ambiguous or changed target leaves old knowledge
intact and that point unfinished, while independent verified additions can be
committed. A common source/project/write/readback safety failure still stops
processing. Deferred or conflicting points retain their sources. Manual batch
reports also include saved handoffs from jobs that are not yet finalized.

Current evidence is isolated in `.tmp/codex-simple-memory-fix-20261009/`.
The real F2 preflight passed, followed by one full Codex Hook on fingerprint
`sha256:ae1c7994f850f71e43d50e4e472e3be0c515d8024a670eeb0f2535f66b58e5b8`.
SQLite knowledge, its job-bound Note and ordinary search agreed, and all three
Hook reentry attempts were blocked with zero downstream jobs. Execution and
configuration hashes remained unchanged during this run. The unchanged
`background_memory_hook_flow` assertions consume that fresh report; isolated
`manual_session_batch`, `partial_distill_handoff` and `clean_retrieval_boundary`
checks passed separately. Focused runtime regressions prove readable replacement,
independent saving with unresolved targets, store reopen/replay, source retention
and unfinished-job handoff reporting using deterministic Agent decisions.
The final quick PR lane passed 1,413 tests with one skip and four release-gate
cases deselected; Ruff, whole-runtime Mypy and compilation passed. Those checks
do not replace the blocked manual model workflow below or publication gates.

The new real three-source F8/F9/F10 manual preflight passed, but its workflow
could not read the required instructions: both terminal launches returned
`helper_unknown_error: setup refresh had errors`. The isolated MCP adapter has
no `resources/list` implementation, so it did not provide a fallback for those
instruction files. No distill job, Note, new knowledge or handoff was created;
the initial three entries and all source bytes were preserved. The CLI exited
zero and its receipt says `passed`, but persisted-result checks correctly report
`partial`. That exit is not manual product acceptance. No further model samples
or retries ran after this failed result. The formal project's Hermes setting,
global installation and real memories were not changed. This is not evidence
of all hosts, a natural Desktop Stop, comparative quality, optimization or release.
Independent read-only review confirmed both stores and Note hashes, and found
that this preflight did not verify instruction-file readability. The actual
failed manual reply also exposed `batch_id` and prepare/govern/finalize names;
the plain-language failure-reply contract has not passed on a real Agent sample,
despite the updated canonical instructions. Keep that failure visible.

The later authorized repair adds an observable instruction-read preflight:
the canonical `hm.md`, full distillation skill, required references and initial
knowledge must actually appear in successful native terminal reads. A stale MCP
inventory log, a normal CLI exit, or the Agent saying it read the files cannot
pass. Default failure guidance is taken from canonical `hm`, including when
instruction reading itself fails. In `.tmp/manual-entry-fix-20261009/`, one real
CLI preflight stopped after one failed terminal launch with a plain-language
reply and no knowledge changes. Windows sandbox logs identify error 32 on the
in-use `node_repl.exe`; no host processes were killed, global settings changed,
or sandbox bypass enabled. This is a failure-path sample, not restored CLI
availability, and later runtime repairs make its fingerprint historical.

Current-Agent manual simulation subsequently exposed two runtime defects.
An invalid semantic review could settle candidates before schema rejection;
finalize now validates it before any candidate or knowledge mutation. Codex
captures permitted conversation rather than its full host event log, so new
captures now bind native user-text digests to the immutable rendering. Evidence
admission compares the full ordered user texts with that capture proof; injected
role boundaries remain rejected. Private spans and host-only records are not
persisted. Legacy captures are not silently rewritten. These capture owners
are included in the runtime fingerprint.

Independent review of that simulation found an outer/inner native-role conflict
could still be certified after parsing, and confirmed existing facts appeared
in the newly-written Note list. Parsing now excludes conflicting/malformed
authorship before capture, and the written list includes only add/refine/replace.
Both defects have real-adapter or finalize/Note negative regressions; the earlier
simulation is retained as historical evidence, not promoted to current success.

On the final fingerprint, `.tmp/manual-verified-20261009/` contains a new isolated
three-source manual simulation. The current main Agent authored point decisions
and used the existing product MCP over stdio, with background processing off.
Two facts were added, one rule replaced, one existing fact confirmed without
duplication, transient/unsupported material left out, and two unfinished task
themes retained in the batch result. Ordinary search returned five current
items and no old sync rule; all selected native sources were retained. This is
not an independent standalone Codex CLI run or a complete Hook rerun. The three
isolated outcome claims passed separately; 301 focused tests, four version
checks, whole-runtime Mypy, Ruff, compilation and descriptor alignment passed.
A broad quick lane was inadvertently started and stopped without a final
verdict because a fresh complete Hook prerequisite is still missing. No release
gate or all-host acceptance is claimed; the formal Hermes project and real
memory remain untouched.

The subsequent 2026-10-09 repair persists explicit manual job ownership and
excludes manual jobs from background dispatch, preferred-job preparation,
review claims and background lease reconciliation. Frozen batch selections
are protected before import/binding and after stopping; manual preparation
cannot take an active background lease. Current-scope archive reports filter
terminal records by stored absolute project root, retaining deleted verified
sources while excluding foreign, same-name/different-root and unowned records.
Unresolved/global inventory diagnostics are not this project's totals.

The latest focused run passed 274 tests, four isolated outcome claims,
whole-runtime Mypy (230 files), scoped Ruff, compilation and descriptor
alignment. The manual outcome probe enables background execution and attempts
each manual preferred job with a provider that fails on any call; jobs, current
knowledge and sources remain unchanged. Evidence lives in
`.tmp/manual-background-fix-20261009/`. These deterministic decisions verify
runtime isolation, not independent model quality or a fresh complete Hook.
One no-model sandbox precondition failed before reading instructions: ACL
refresh of the in-use `node_repl.exe` returned Windows error 32. No model run,
retry, host-process termination, global configuration change or fresh Hook
followed. Standalone CLI recovery and release gates therefore remain open;
real memory and the formal Hermes project remain untouched.

Independent review then reproduced lower-level unbound-source claims and a
manifest-publication race. Frozen selection publication now serializes with
cross-connection claims under the existing SQLite write lock; both chunk and
review claims check frozen ownership. An already-active background lease
prevents publication rather than being taken over. Archive completed replay
now verifies current knowledge, native/immutable source and receipt before
calling the existing cleanup owner; manual retention is honored. Reintroduced
native bytes cannot be certified by an old deletion receipt. Exception handling
uses the frozen revision rather than rereading a deleted file, preserves the
Note identity, and changed source revisions have only one current lifecycle
state. Negative regressions reproduced these failures before correction.

The final frozen fingerprint is
`sha256:6940734ce7c44fe2d9bb2a81bda78d04064137e5ffa239f32523ff6427f56302`.
The consolidated 18-file focused run passed 415 tests; four current isolated
outcome claims passed in
`.tmp/manual-background-fix-20261009/outcomes-final.json`. Whole-runtime Mypy,
scoped Ruff, compilation and diff checks also passed. This closes the code
defects found in this repair, not standalone CLI recovery, a fresh complete
Hook, full-suite release gates or publication. No model or real-memory
maintenance was performed.

The operator restarted the desktop host and authorized continuation on
2026-10-09. One fresh no-model sandbox instruction-read check still failed with
Windows error 32 on the in-use `node_repl.exe`. Read-only process inspection
found multiple same-path runtime processes launched by the current desktop
host's Codex child. Evidence is in `.tmp/codex-restarted-20261009/`; the source
fingerprint is unchanged. No model or complete Hook followed, and shared
runtime processes, sandbox security and global configuration were not changed.
Restarting alone did not resolve this condition; release acceptance remains
blocked pending safe resolution of that runtime occupancy.

On 2026-10-11, the operator authorized a fix that works with the desktop open.
The installed Codex CLI remains `0.162.1`; only its sandbox setup helper was
replaced with the valid OpenAI-signed helper from the official
`0.163.0-alpha.5-win32-x64` package, retaining the signed original for recovery.
The old helper still failed in the same live desktop environment. Both fresh
ordinary installed-entry probes then passed full instruction reads, inside
workspace writes and outside workspace write denial, with actual helper path
and hash sampling and unchanged desktop/Node/Swift process identities.
CLI, runner, configuration and harness-mem fingerprint remained unchanged;
no model, memory maintenance, tool termination or restart was used in this fix.
Private receipts are in `.tmp/desktop-runtime-fix-20261011/`. This resolves the
observed local sandbox occupancy blocker, not fresh model preflight, complete
Hook or release acceptance. It is a local signed-helper replacement, not a
complete upstream version upgrade; reinstalling Codex may overwrite it.

Later on 2026-10-11, one authorized Codex F2 preflight passed (27.563 seconds,
29,046 tokens), followed by one full isolated Hook (70.61 seconds; 86,644 tokens
across its three semantic phases). The current `6940734...` fingerprint produced
one job-bound current knowledge entry, matching immutable/latest Notes and
receipt hashes, and an actual ordinary MCP search response with the same title
and statement. All three Hook reentry actions were blocked with zero downstream
jobs. Raw search responses and the canonical core-claim report are retained in
the private `.tmp/codex-core-chain-20261011/` directory. Code, selected helper
and configurations remained unchanged; the real current knowledge database
hash remained unchanged and the synthetic run was absent from real ledger/Notes.
The initial extra guard requiring the entire live transcript ledger's bytes to
remain frozen failed and is preserved: a real desktop job updated during this
window. Read-only follow-up checks explain the scope mismatch but do not claim
to attribute every changed byte. The unchanged `background_memory_hook_flow`
assertions passed after retaining raw search and checking real knowledge and
test isolation; the original strict wrapper/report stays failed/blocked.
No second model preflight, Hook or real-memory maintenance was run. This meets
the operator's Codex core-chain acceptance scope, not natural Desktop Stop,
all-host coverage, wider semantic quality, performance improvement or release.

Same-source semantic quality, natural Stop and repeatable performance remain
unverified. Each failed model preflight stops the remaining samples without
automatic retries.

1. **Show the actual saved result.** An explicit organization request finishes
   with readable additions, replacements and removals, grouped by natural module
   when useful, plus ordinary no-write reasons and unresolved work. The user
   should not need a second question to see what was remembered. Reuse current
   knowledge rendering and the canonical `hm` instruction; do not create a
   dashboard, a new daily command or a Markdown truth store. On demand, show the
   full current project knowledge from SQLite. Quiet background processing
   remains quiet; requested status uses the same readable result. Distinguish
   the original conversation's outcome from the organizer's persisted result.
   Acceptance covers success, replacement, no-write, failure and partial work
   in the user's language, through the actual Agent response as well as MCP.
2. **Optional upstream comparison.** This is not required for the current
   one-host acceptance; run it only if comparative quality/ease is requested.
   Freeze a fictional corpus
   and expected independent knowledge points before running either product.
   Include short, long/multi-point, repeated, outdated, conflicting, task-local
   and unfinished content; pin both revisions and report configuration and
   model differences. Compare missed points, incorrect writes, duplicates,
   readable results, necessary user decisions and recovery. Reuse existing
   source inventory, coverage and fixed batches: selected project/revisions
   remain stable, ownership errors remain visible, and interrupted work resumes
   without duplicate knowledge. Manual acceptance runs with background disabled.
   Neither an upstream sample report nor deterministic runtime fixtures prove
   equal semantic quality or ease. Upstream-only operations are recorded, not
   counted as missing daily memory features without a user need.
3. **Optional measured optimization.** Repeated measurement is required for a
   claimed time/token reduction, not for the current functional pass. Establish
   repeatable per-phase and whole-workflow baselines from the same corpus;
   include CLI startup, all actual Agent input/output, source reads, retries,
   validation, SQLite/Note persistence and normal search. Separate preflight
   from work, and CLI usage from cached/billed usage when available. Trace
   repeated source/knowledge/schema/instruction context before changing code.
   First remove demonstrated duplication in existing owners. Preserve complete
   source access, independent extraction/verification/assimilation decisions,
   host configuration and Hook guards. A stage merger, different model or
   truncation is not an assumed shortcut. Accept savings only when repeated
   matched runs reduce time/context while the frozen quality and recovery
   checks do not regress; record spread, not just the fastest result.
4. **Follow-up native use and release preparation.** A natural Stop test is a
   separate native-trigger claim, not a prerequisite for this functional pass.
   If requested, exercise a newly
   created native host session, its actual Stop event, and later recall and
   correction through `hm`. Retest the current manual batch path with a real
   Agent against isolated synthetic sources, including interruption and retry.
   Record host-specific evidence separately; the Codex result does not clear
   Hermes or native Cursor compatibility. Align canonical instructions,
   generated mirrors/descriptors and bilingual public docs, then run the
   required outcome, repository and release gates in the order below.
   This stage prepares reviewable release evidence; publishing is a separate
   action. Assign the next version only when its scope and gates are settled.

The immediate acceptance package is readable saved results and one working
host/CLI path; Codex meets that criterion. Steps 2 and 3 are not blockers, and
step 4 remains separate from this functional verdict. Keep inventory,
source inspection, recovery and evidence tools where their operations require
them. Removing an entry requires the necessary user operation, its deletion
consequence and verified alternative coverage; there is no target tool count.
Hermes gateway repair, additional daily entries, a knowledge dashboard and
broader storage/architecture work remain outside this package.

### Adopted upstream improvements

- **Inventory first:** adapter defaults must not discard short sessions by file
  size. CLI/MCP listing already requests a zero size threshold; the remaining
  default mismatch was in adapters. The working tree now aligns those defaults
  and retains per-file read/stat failures in shared JSONL listing, with Cursor
  forwarding issues. `empty_source` means blank decoded text, not proof of an
  empty IDE draft; `readable` does not mean valid JSON or completed processing.
- **Cursor history coverage:** exported JSONL plus read-only native SQLite and
  `workspace.json` ownership resolution have isolated fixture coverage in the
  working tree. This is not a claim that every live DB format is supported.
  Schema/key inspection belongs in developer diagnostics. Benchmark future
  prefix-query optimization against the actual schema and query plan rather
  than inheriting upstream performance claims.
- **Theme overview:** implemented in the working tree through read-only
  `inspect_sessions(action="overview")`, validating submitted coverage ranges
  against the complete permitted source revision. Allow multiple Agent-proposed
  themes and unclassified sessions; counts must trace
  to the same selected sessions. Classification helps navigation, never skips
  per-point extraction or substitutes sampling for full coverage.
- **Reuse existing safety:** improve evidence-location assistance and cleanup
  previews without replacing source revalidation, project/session isolation,
  governed writes, search readback or resumable jobs. A matching entity/file
  does not establish semantic support. Packet/Note existence is not completion
  or permission to delete a source. Do not add eight public tools or combine a
  read-only overview with implicit cleanup.

Inventory, source paging, conservative draft classification, theme coverage
and manual batch persistence now have focused synthetic fixtures. Unknown or
malformed sources are not empty drafts. These checks do not establish live
database compatibility, semantic theme quality or current background acceptance.

### Acceptance criteria

- An explicit single-session request proceeds without a platform-selection
  wizard. An explicit project-wide request covers the selected hosts without
  asking the user to invoke each processing tool.
- Inventory and progress use the same project scope and current counts;
  imported is never reported as processed. Unreadable or ambiguous sources
  remain visible and cannot silently count as complete.
- Complete source coverage, independent point decisions, deduplication,
  current SQLite state and ordinary-search readback agree with the reported
  knowledge changes. No-write results remain valid outcomes, not fake writes.
- An interrupted run resumes from preserved state without duplicating knowledge
  or losing unresolved work. New source revisions are not mistaken for old ones.
- Manual acceptance succeeds with background processing disabled; background
  acceptance separately proves the selected CLI, Hook isolation, persistence,
  Note and retrieval. Passing one does not prove the other.
- For success, empty/no-write, failure and recovery fixtures, capture the
  actual tool sequence and returned content. Compare user decisions, Agent
  calls, repeated source reads and context size; justify each remaining repeat.
  Do not trade away evidence or recovery to meet an arbitrary tool/token count.

This train does not authorize real-history migration, source deletion, Git
commit/push, credential changes, a new daily entry, a parallel runtime or a new
storage authority. Detailed interaction rules belong in `DESIGN.md`; executable
current facts belong in `AGENTS.md`. This roadmap owns goals, order and gates.

## Release `0.9.28`

`0.9.28` closes the gap between a successful distill job and usable current
knowledge. Explicit distill suggestions now carry a complete assimilation
decision, and finalize checks the ordinary search path after each write.
`knowledge_entries` is the only current memory: replacement may remove one or
more old items and write one or more new items in one transaction,
and invalid memory is deleted. No knowledge versions, archived knowledge
copies, knowledge change records, or undo chain are retained. Legacy
`MemoryEntry` rows stay readable only for compatibility. The automatic project
check now returns one short ready/failure message, while detailed diagnosis
remains in Doctor. Historical version claims require matching current
repository evidence, and host-event-only Codex archives finish as verified
empty records without model work.

## Release `0.9.27`

`0.9.27` converges installation and daily use on one `hm` entry, removes the
old action-specific entries from new and upgraded installations, and makes
Quickstart independent of projects and MCP configuration. It also removes two
silent runtime substitutions: Hook dispatch failure no longer runs maintenance
inline, and an unknown host no longer becomes Claude Code or Codex.

## Release `0.9.26`

`0.9.26` converges authorized background work on the selected host CLI,
documents the contract in `docs/background-memory.md`, and adds release Hook
acceptance gates. Hermes and Claude Code host CLI chains were validated in
isolated acceptance runs.

## Release `0.9.25`

`0.9.25` makes Dream the only unattended executor for Hook-started sessions:
the Hook persists its immutable source/job and wakes Dream, while a manually
requested `distill` stays in its active host. It also closes the fail-closed
boundaries found during the first provider/Dream review: a truncated source
cannot retire truth, an archived truth mutation has a real undo, provider
construction/verification failures persist terminal Dream failures, and Hook
receipts bind the selected non-secret provider configuration.

## Releases `0.9.23` and `0.9.24`

`0.9.23` introduces an operator-owned, restricted semantic provider profile
for unattended Dream work (superseded by the current `0.9.28` source:
`distill.autonomous.enabled=true` + a project-selected CLI, defaulting to the
current host; see
[`docs/background-memory.md`](background-memory.md)). A project could select a
named profile from user configuration; repository configuration could not supply
an endpoint or credential environment variable. Automatic model work still
needed the separate project authorization `[distill.autonomous].enabled = true`.

In `0.9.23`, Dream kept a terminal ledger for every source recheck and offered
reversible retirement. That knowledge-history design was removed in `0.9.28`.
The current design changes or deletes only the current item after rechecking a
complete source; unsupported or incomplete sources leave current memory
unchanged. This is not an external web/API revalidator.

`0.9.24` adds the explicit `output_mode = "json"` profile setting for
Anthropic-compatible gateways that reject forced tool output. It is still a
no-tool transport: the runtime accepts only JSON that validates against the
same strict Pydantic schema, so malformed text fails closed.

## Released SQLite current-knowledge convergence

Rows below `0.9.28` describe what those releases shipped. Their references to
knowledge versions, archived knowledge, mutation history, or undo are historical
only and were removed from the current `0.9.28` design.

```text
canonical.sqlite / knowledge_entries
  = single authority for current long-term knowledge

job workspace
  = temporary candidates, verification, and proposed decisions
  = retained only for retry, unresolved work, and bounded diagnosis

current search
  = deterministic SQLite knowledge read and ranking

FTS/vector
  = optional rebuildable optimization; never a truth authority

Markdown/JSON/text
  = on-demand user presentation, never an authority
```

| Version | Primary change | Main modules | Removal/convergence | Status |
|---|---|---|---|---|
| `0.9.16` | Make SQLite current knowledge authoritative and transactional | 0, 3 | Remove Markdown authority, fingerprint synchronization, whole-document mutation, and permanent audit-ledger construction | Folded into released `0.9.20` |
| `0.9.17` | Make candidate/evidence/decision material job-scoped and clean terminal detail | 2, 3 | Remove completed processing records as a permanent corpus; move handoff to its owner | Folded into released `0.9.20` |
| `0.9.18` | Read only clean SQLite knowledge and render Markdown on demand | 4 | Remove Markdown parser from normal reads and exclude audit/storage fields from normal output | Folded into released `0.9.20` |
| `0.9.19` | Route Dream/Review revalidation and undo through the same SQLite mutation path | 2, 3, 4 | Remove parallel mutation paths and unbounded decision history | Folded into released `0.9.20` |
| `0.9.20` | Run six retained sessions in an isolated `harness-mem` scope and show the actual clean library | 0--4 | Delete remaining duplicate/broad/internal-heading behavior found by acceptance | Released; frozen oracle, lineage readback, Hook and 14-claim outcome passed |
| `0.9.21` | Physical repository migration to `code/` and delivery of clean SQLite-first 0.9.x behavior | 0--4 | Keep legacy real memory untouched unless separately authorized; keep candidate/evidence/decision as transient job material; preserve audit receipts and recovery points | Released; one separately authorized, project-isolated legacy convergence completed |
| `0.9.22` | Close the archive-repair, task-envelope, clean-search, and current-truth outcome gaps | 0--4 | Keep normal search clean while preserving internal Autopilot context; prevent semantic models from invoking truth archival | Released |
| `0.9.23` | Operator-owned restricted semantic profiles and terminal source-backed Dream rechecks | 2--4 | Keep credentials out of project config; do not retire truth from partial/unsupported sources; retain mutation undo | Released |
| `0.9.24` | Strict JSON-text compatibility for Anthropic-compatible gateways that reject forced tool output | 2--4 | Keep JSON schema validation and no-tool boundary; do not silently downgrade malformed output | Released |
| `0.9.25` | Hook-started Dream execution and fail-closed source/provider/undo receipts | 0, 2--4 | Keep Hook non-semantic; reject truncated retirement; preserve real undo and retryable provider failure | Released |
| `0.9.26` | Host CLI background authorization and honest `{host}_cli` receipts | 0, 2--4 | No HTTP impersonating Agent; profile not required for CLI path; Hook re-entry guard | Released |
| `0.9.27` | One daily `hm` entry and honest Hook/host failure boundaries | 0--4 | Quickstart leaves MCP alone; no action-specific entries, inline Hook work, or guessed host | Released |
| `0.9.28` | One current-memory store and short automatic project check | 2--4 | Normal-search readback; direct replacement/deletion; no knowledge history or undo; legacy `MemoryEntry` is compatibility data only | Released |

## Current `0.9.28` source

Since `0.9.26`, authorized background work uses **`distill.autonomous.enabled=true`**
+ a **project-selected CLI**. The default is the current host; a project may
explicitly select Codex, Claude Code, Hermes, or OpenCode. Transport and
credentials live in the selected CLI's configuration. Runtime checks require
`provider.name=<host>_cli` and a successful Hook re-entry challenge; there is no
HTTP fallback in the product path.
Turn off background work with **`distill.autonomous.enabled=false` only**.

`0.9.27` keeps that execution model and narrows the public path to install,
Quickstart, and `hm`. When the current host cannot be identified, or detached
Hook dispatch fails, the pending work stays local and no model command is run
from the Hook process.

`0.9.28` keeps that public path and requires completed distill work to become
current SQLite knowledge that ordinary search can read. Replacing a current
item deletes it and writes the new item; invalid memory is deleted. The current
design does not keep knowledge versions, archived knowledge copies, knowledge
change records, or undo. Compatibility `MemoryEntry` rows remain readable but
do not count or appear as current knowledge. The automatic project check
reports only readiness or one recovery action; operational detail belongs to
Doctor.

These versions are implementation slices, not additional product modules. The
product architecture remains the five independently measurable modules:

```text
0. session intake/lifecycle
-> 1. extraction
-> 2. per-point verification
-> 3. assimilation
-> 4. retrieval/use
```

Review and Dream remain the governance feedback loop across modules 3--4. A
person explicitly running `distill` uses the active host; a Hook only persists
the session/job and wakes Dream. Dream is the unattended executor: it may
process the triggering session before its project-wide comparison, then returns
all accepted work to per-point verification and the same assimilation mutation
path.

## Locked decisions

- Extraction keeps the existing lossless manifest and semantic/raw drilldown.
  A session may yield zero or more independent promotion points, without a
  hidden fixed count limit.
- One session may yield multiple independent durable items.
- Source authenticity and semantic support are verification concerns;
  `ANSWERED` does not mean “write this”.
- Assimilation owns durability, atomic splitting, wording, natural module
  grouping, deduplication, and the nine dispositions.
- There is no project allowlist and no fixed module taxonomy. An archive run is
  scoped by its explicit project argument and verified session ownership.
- Current knowledge keeps a stable internal ID, project identity, natural
  module path, specific title, one-statement body, and verification date.
- The stable ID is for mutation/feedback/source linkage and is never shown or
  embedded by default. The title is retained because it improves human scanning
  and targeted retrieval; it cannot be an internal type such as “candidate” or
  “stable operation rule”.
- Minimal source locators remain separate from current knowledge so Review and
  Dream can re-open the real repository, transcript, local file, web page, or
  API. Earlier database verdicts do not revalidate themselves.
- Candidate, verification, and proposed-decision detail is temporary. Terminal
  cleanup occurs only after SQLite commit, Note/Packet, and receipt are durable.
- Real memory is never migrated, deleted, or redistilled as a side effect of
  development, docs, startup, or tests.

## Delivery order and stop conditions

1. Released: lock schema, transaction, cleanup, and clean-projection tests.
2. Released: remove rejected Markdown authority and permanent audit-ledger code.
3. Released: implement SQLite row mutations and minimal source/version relations on the existing database inode.
4. Released: move processing detail into job lifecycle storage with retry-safe cleanup.
5. Released: converge normal retrieval and on-demand rendering.
6. Released: route Dream/Review through revalidation and the same mutation service.
7. Completed: six retained `harness-mem` sessions ran in an isolated data root;
   all six jobs, Notes, and Answer Packets reached terminal persistence, and all
   12 clean knowledge entries were read back without changing real runtime data.
8. Completed: a fresh Desktop Hook receipt bound dispatch generation, session,
   job, Provider, and Note; the full outcome contract passed 14/14.
9. Completed one separately authorized `harness-mem`-scoped legacy convergence;
   future projects or historical cohorts still require their own explicit approval.

Checks that call a real host CLI follow one bounded order: focused deterministic
tests, one fixed model check with no automatic retry, one isolated full Hook run,
then broad repository and release gates. A failed or timed-out model check stops
the run before a job or full Hook is created. A failed full Hook stops the release
checks. Code or relevant configuration changes invalidate earlier runtime
evidence; results from separate attempts are not combined.

Any partial SQLite mutation, early workspace cleanup, stale/superseded retrieval
hit, cross-project write, unsupported source claim, duplicate current item,
audit field in normal output, or Markdown-to-truth write path stops the train.
Unit tests, provider JSON, queued jobs, and generic `completed` status are only
supporting evidence.

The detailed conceptual contract is
[memory-adoption.md](memory-adoption.md), the engineering plan is
[knowledge-truth-separation.md](roadmap/knowledge-truth-separation.md), and the
acceptance matrix is [distill-test-plan.md](distill-test-plan.md).

## Directions under consideration

The released train is complete. One deliberately unplanned direction is
recorded in [next-iteration-directions.md](roadmap/next-iteration-directions.md):

1. Revalidate the real external web/API source of an existing claim without
   turning the product into a search engine.

That document is a decision backlog, not a delivery commitment or an authority
to access networks or mutate real historical memory.

## Historical releases

Older 0.8--0.9 release notes remain historical evidence. The deleted
`0.9.13--0.9.15` proposal and the unshipped Markdown-authority experiment do not
define current implementation status or the next target architecture.
