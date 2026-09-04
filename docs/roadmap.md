# harness-mem Roadmap

This roadmap distinguishes the released runtime from separately authorized
legacy convergence. It never authorizes mutation of real user memory by
itself; normal runtime paths do not migrate legacy data.

## Current source and release line

The current source package is `0.9.27`; published artifacts are listed on the
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
for unattended Dream work (superseded by the current `0.9.27` source:
`distill.autonomous.enabled=true` + a project-selected CLI, defaulting to the
current host; see
[`docs/background-memory.md`](background-memory.md)). A project could select a
named profile from user configuration; repository configuration could not supply
an endpoint or credential environment variable. Automatic model work still
needed the separate project authorization `[distill.autonomous].enabled = true`.

Dream now keeps a terminal ledger for every source recheck. It can refresh one
current item when its complete, reopenable source still supports it, or
reversibly retire that item when the source contradicts it. Multi-item
comparison signals, unsupported external sources, missing providers, and
bounded/truncated source excerpts leave current knowledge unchanged and close
as audit records. This is not the unplanned external web/API revalidator.

`0.9.24` adds the explicit `output_mode = "json"` profile setting for
Anthropic-compatible gateways that reject forced tool output. It is still a
no-tool transport: the runtime accepts only JSON that validates against the
same strict Pydantic schema, so malformed text fails closed.

## Released SQLite current-knowledge convergence

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
| `0.9.27` | One daily `hm` entry and honest Hook/host failure boundaries | 0--4 | Quickstart leaves MCP alone; no action-specific entries, inline Hook work, or guessed host | Current release line |

## Current `0.9.27` source

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

- Extraction keeps the existing lossless manifest, semantic/raw drilldown, and
  zero-to-twelve independent promotion points.
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
