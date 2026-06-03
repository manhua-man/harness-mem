## Why

`docs/roadmap-v22x.md` and `docs/roadmap-status.md` still described `v2.2` as
fully completed, but the release-gate evidence in `docs/v2-user-test-packet.md`
still said:

- `Known gap: 非 Claude client (Codex / Cursor / generic MCP) 未跑`

That left the repo claiming a closed cross-client gate while its own run log
still showed the required non-Claude client entry missing.

## What Changes

- Update `docs/roadmap-v22x.md` to distinguish runtime/contract completion from
  the still-open manual cross-client release gate.
- Update `docs/roadmap-status.md` to carry the same nuance in the status matrix
  and high-level summary.
- Add a focused regression test that fails if the packet still has the
  non-Claude gap while the roadmap slips back to "fully completed".
- Update release writeback for `v2.9.54`.

## Impact

- The `v2.2` status now matches the repo's actual evidence.
- Automated non-Claude parity coverage and missing manual run-log evidence are
  clearly separated instead of being conflated.
- CI guards this completion-truth boundary against regression.
