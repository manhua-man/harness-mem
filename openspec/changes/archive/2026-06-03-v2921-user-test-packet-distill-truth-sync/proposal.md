## Why

The shipped runtime already uses
`auto_review_candidates(project_name=<project>, apply=true)` as the default
distill review surface. But `docs/v2-user-test-packet.md` still described the
generic MCP distill chain as `prepare_session_distill -> suggest_* ->
list_candidates -> auto_review_candidates`.

That leaves one of the high-visibility test collateral docs out of sync with
the distill path the runtime actually wants generic MCP clients to follow.

## What Changes

- Update the generic distill chain in the v2 user test packet so it points
  directly to `auto_review_candidates`.
- Add a focused regression test that fails fast if the packet drifts back to
  the older `list_candidates -> auto_review_candidates` chain.

## Impact

- The v2 user test packet now matches the shipped distill review surface more
  directly.
- Future edits that reintroduce the older generic MCP chain fail fast in CI.
