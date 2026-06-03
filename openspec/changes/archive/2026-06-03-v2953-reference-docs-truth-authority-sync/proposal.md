## Why

High-visibility reference docs still described how to operate or evaluate the
system without explicitly saying where current shipped-state truth lives:

- `docs/cli/v2.4.md`
- `docs/error-codes.md`
- `docs/cli-design-expert.md`

That made these reference docs weaker than the repo root, docs index, and usage
docs, all of which already pointed to `roadmap-status.md` and `CHANGELOG.md`.

## What Changes

- Update the three reference docs to point readers at `roadmap-status.md` and
  `CHANGELOG.md`.
- Add a focused regression test for those authority notes.
- Update release writeback for `v2.9.53`.

## Impact

- High-visibility reference docs now share the same current-truth authority
  chain as the rest of the repo.
- Operator guidance, error-code lookup, and design guidance stay clearly
  separated from shipped-state truth.
- CI guards this reference-doc authority wording against regression.
