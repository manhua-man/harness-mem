# Draft release 0.9.26 (not yet published)

## What changed in the current source

- Converged authorized background memory on `distill.autonomous.enabled=true`
  and a project-selected CLI. The default is the current host; a project may
  explicitly select Codex, Claude Code, Hermes, or OpenCode. Profile
  registration is no longer part of the product path.
- Added host CLI executors for Codex, Hermes, Claude Code, and OpenCode with
  Hook re-entry guard and honest `{host}_cli` receipts
  (`execution_mode=agent`).
- Routed Dream recheck and the autonomous worker through
  `build_semantic_executor` with honest `{host}_cli` receipts only; no HTTP
  profile or transport fallback in the product path.
- Documented the contract in `docs/background-memory.md` and aligned public
  docs, canvases, SVGs, and host skill mirrors.

## Install the latest public release

`0.9.26` has not been published yet. The latest public release is `0.9.25`:

```bash
pip install \
  --find-links https://github.com/manhua-man/harness-mem/releases/expanded_assets/v0.9.25 \
  harness-mem==0.9.25
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
