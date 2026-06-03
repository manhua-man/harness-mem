## Why

The `v2-user-test-packet` still pointed at an archived `openspec/changes/v220`
path as its contract source, and its Codex section framed MCP setup as
"whatever the current Codex CLI version supports". Both of those references are
outside the stable repo-owned truth we can verify locally.

That leaves one of the highest-visibility cross-client test docs anchored to an
archived path and an external-client time marker instead of the maintained main
spec.

## What Changes

- Point `docs/v2-user-test-packet.md` at `openspec/specs/daily-workflow/spec.md`
  as the contract source of truth.
- Rewrite the Codex MCP setup sentence so it describes the repo's maintained
  stdio contract rather than a drifting client-version phrase.
- Add a focused regression test that rejects both the archived change path and
  the "current Codex CLI version" wording.
- Update release writeback for `v2.9.43`.

## Impact

- The user-test packet now cites a stable, maintained spec path.
- Future doc edits that drift back to archived-change or external-client timing
  language fail fast in CI.
