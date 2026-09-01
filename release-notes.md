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
