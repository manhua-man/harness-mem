## Why

`docs/v2-user-test-packet.md` still listed
`openspec/changes/<change>/specs/...` as a generic allowed landing path. That
blurs the distinction between:

- current main spec truth in `openspec/specs/...`
- conditional active-change proposal details in `openspec/changes/<change>/specs/...`

In the current repo state there are no active changes, so the packet should
make the default source hierarchy explicit instead of implying both are normal
peer entry points.

## What Changes

- Update `docs/v2-user-test-packet.md` to say main specs are the default truth
  source.
- Keep change-local spec paths as a conditional drilldown only when an active
  proposal actually exists.
- Extend the focused regression test for the packet wording.
- Update release writeback for `v2.9.48`.

## Impact

- Maintainers following the packet now reach the right OpenSpec source first.
- The packet no longer implies an active-change context by default.
- CI guards this source-hierarchy wording against regression.
