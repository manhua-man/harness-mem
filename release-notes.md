# Release 0.9.28 (2026-09-08)

## What changed

- Explicit `hm` distillation now submits the complete assimilation decision
  before finalize. Add, refine, confirm, replace, and no-write outcomes use
  the same SQLite current-knowledge transaction as background processing.
- Confirm names one current SQLite target; refine and replace may name one or
  more current SQLite targets. Missing,
  stale, or mismatched targets leave the job unfinished instead of turning a
  compatibility status into a successful write.
- Current reads now start from `knowledge_entries`. Legacy `MemoryEntry` rows
  remain readable only for compatibility and do not
  count as current project knowledge.
- Replacing knowledge deletes the old item and writes the new item. Invalid
  knowledge is deleted. There are no knowledge versions, archived knowledge
  copies, knowledge change records, or undo chain.
- The automatic project check now returns one short ready or failure message.
  Detailed retrieval, queue, cost, version, and repair information remains in
  `harness-mem doctor`.

## Runtime corrections

- Finalize verifies that every newly committed item is returned by ordinary
  current-project search and that replaced items are no longer returned.
- Archive verification no longer falls back to legacy candidate or truth rows
  when current SQLite knowledge is absent.
- Archives containing only host events now finish as verified empty records;
  they do not call a model or create a job, Note, or knowledge item.
- A historical session cannot establish the current project version without
  matching evidence from the current repository.
- Review can directly delete exactly one named current-memory item when it is
  no longer valid.
- The legacy Observation-only distill response no longer embeds the old project
  status object, and current status counting never reads `memory_entries`.
- Dream no longer creates legacy `MemoryEntry` merge or stale output.
  It rechecks every named complete source against `knowledge_entries`; a
  multi-item replacement is applied only when all of those sources verify.
- Wake now uses one current-knowledge path for normal use and one diagnostic
  path when explicitly requested; the duplicate CLI renderer, repeated backend
  pass, and obsolete status modules have been removed.
- `temporal_query`, `undo_dream_item`, and the old rule/skill/relation read
  tools are no longer public MCP tools. The public contract now contains 20
  tools.
- New databases no longer create knowledge-version or knowledge-mutation
  tables. Existing compatibility data is left untouched and never counts as
  current memory.
- Removed artificial processing caps: a source candidate may produce multiple
  current memories; search and wake no longer hide current entries behind a
  fixed default count; archive, background, and session sync work no longer
  have an implicit batch or daily quota. An explicit count remains an optional
  caller choice.
- Current-memory titles and statements no longer have the old 160/4000
  character limits. A refine or replace decision may remove several current
  entries and write several new entries atomically.
- A successful user-requested session cleanup now removes only the selected
  session's source, generated Note, and matching host-history file. Dream keeps
  its source and Note as an archive. Failed, unfinished, unsupported, or
  ambiguous sessions remain.
- Session processing never creates an automatic source backup, and it never
  clears a host's unrelated history.

## Release evidence

- Release completion requires Git tag `v0.9.28` and a successful public build.
- Python package metadata, runtime `__version__`, and plugin manifest:
  `0.9.28`.
- Full source, Rust, built-wheel, seven-host, Hook, and current result checks are
  required before the release is declared complete.
- The release does not migrate, delete, or rewrite existing user memory unless
  the user explicitly requests that particular memory change.

## Install or upgrade

```bash
python -m pip install --upgrade \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.28 \
  harness-mem==0.9.28
```

The package is distributed through GitHub Releases, not PyPI.

# Release 0.9.27 (2026-09-04)

## What changed

- Daily use now has one entry: `$hm` in Codex and `/hm` in the other supported
  Agents. Say what you want in ordinary language: remember this session, find
  earlier work, or correct a memory.
- Quickstart runs once for each Agent app you use. It installs that entry only;
  it does not inspect projects or manage MCP connections.
- The first `hm` use passes the current project and Agent explicitly before it
  prepares local memory and project Hooks.
- Existing Router or plugin connections remain the connection authority. The
  setup guide now warns against adding a duplicate direct server.

## Runtime corrections

- A Hook that cannot start its detached worker now reports the failure and
  stops. It never runs Dream, maintenance, or a model command inline.
- If the current Agent cannot be identified, harness-mem reports that instead
  of guessing Claude Code or Codex. A project may still explicitly choose a
  supported background CLI.
- Wheel smoke tests now prove that a clean Quickstart installs only `hm`, MCP
  initialization leaves the project untouched, and the first `hm` status call
  prepares the project Hooks.
- Hook, worker, and MCP processes now share the configured data directory.
  Release verification uses isolated SQLite and Note paths and confirms the
  same Hook-created knowledge is returned by normal search.
- Hermes background runs on Windows no longer fail only because a late-exiting
  child process briefly keeps its working directory open.
- Background calls use the selected CLI's normal Agent configuration. The old
  fixed mode, duplicate `restricted` state, copied-down Codex configuration,
  and self-reported capability flags are gone; harness-mem validates JSON and
  blocks Hook re-entry locally.

## Release evidence

- Release completion requires Git tag `v0.9.27` and a successful public build.
- Python package metadata, runtime `__version__`, and plugin manifest:
  `0.9.27`.
- Full source, Rust, built-wheel, seven-host, Hook, and 12-result checks are
  required before the release is declared complete.
- The release does not migrate or rewrite existing user memory.

## Install or upgrade

```bash
python -m pip install --upgrade \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.27 \
  harness-mem==0.9.27
```

The package is distributed through GitHub Releases, not PyPI.

# Release 0.9.26 (2026-09-02)

## What shipped

- Converged authorized background memory on `distill.autonomous.enabled=true`
  and a project-selected CLI. The default is the current host; a project may
  explicitly select Codex, Claude Code, Hermes, or OpenCode. Profile
  registration and HTTP transport fallback are no longer part of the product
  path.
- Added host CLI executors for Codex, Hermes, Claude Code, and OpenCode with
  Hook re-entry guard and honest `{host}_cli` receipts
  (`execution_mode=agent`).
- Routed Dream recheck and the autonomous worker through
  `build_semantic_executor` with honest `{host}_cli` receipts only.
- Documented the contract in `docs/background-memory.md` and added a release
  Hook acceptance checklist at `docs/hook-release-checklist.md`.

## Current architecture boundary

- SQLite `knowledge_entries` is the sole authority for current long-term
  knowledge.
- Transcript revisions remain source evidence.
- Candidate, evidence, and proposed assimilation decisions remain temporary
  job-scoped material and are cleaned by policy only after a proven terminal
  outcome.
- Normal `wake` and `search` do not expose raw transcripts, provisional
  candidates, internal IDs, or audit envelopes.
- Session processing and project governance use distinct queues even when
  served by the same restricted Dream executor.

## Release evidence

- Git tag: `v0.9.26`.
- Python package metadata, runtime `__version__`, and plugin manifest:
  `0.9.26`.
- Repository qualification record: frozen six-session oracle, generation-bound
  Desktop Hook, and the 14-claim outcome contract passed.
- Hermes and Claude Code host CLI chains validated in isolated acceptance
  runs; real Hook acceptance documented in `docs/hook-release-checklist.md`.
- The release does not authorize automatic migration or mutation of other
  projects' real legacy memory.

## Install or upgrade

```bash
python -m pip install --upgrade \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.26 \
  harness-mem==0.9.26
```

The package is distributed through GitHub Releases, not PyPI.

# Release 0.9.25 (2026-08-21)

## What shipped

- Made Dream the only unattended executor for Hook-started sessions. A Hook
  now persists the immutable source and session job, then emits a source-bound
  Dream activity signal; an explicit `distill` remains in the active host.
- Added operator-owned restricted semantic provider profiles. Projects may
  select a named user profile only after autonomous distillation is explicitly
  enabled; credentials are read only through environment-variable references.
- Added strict, no-tools JSON output compatibility for Anthropic-compatible
  gateways that reject forced tool output. Malformed or schema-invalid output
  fails closed.
- Prevented truncated, missing, or unsupported sources from retiring current
  knowledge. Unsafe multi-item comparisons close without guessing a winner.
- Made provider construction and verification failures persist as terminal,
  retryable Dream failures, and made archived truth mutations carry a real
  undo path.
- Bound unattended receipts to the originating Hook source, dispatch
  generation, and a fingerprint of the selected non-secret provider settings.

## Current architecture boundary

- SQLite `knowledge_entries` is the sole authority for current long-term
  knowledge.
- Transcript revisions remain source evidence.
- Candidate, evidence, and proposed assimilation decisions remain temporary
  job-scoped material and are cleaned by policy only after a proven terminal
  outcome.
- Normal `wake` and `search` do not expose raw transcripts, provisional
  candidates, internal IDs, or audit envelopes.
- Session processing and project governance use distinct queues even when
  served by the same restricted Dream executor.

## Release evidence

- Git tag: `v0.9.25`.
- Python package metadata, runtime `__version__`, and plugin manifest:
  `0.9.25`.
- Repository qualification record: frozen six-session oracle,
  generation-bound Desktop Hook, and the 14-claim outcome contract passed.
- The release does not authorize automatic migration or mutation of other
  projects' real legacy memory.

## Install or upgrade

```bash
python -m pip install --upgrade \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.25 \
  harness-mem==0.9.25
```

The package is distributed through GitHub Releases, not PyPI.
