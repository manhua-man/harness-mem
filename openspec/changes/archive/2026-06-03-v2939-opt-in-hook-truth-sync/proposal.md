## Why

The current runtime already ships opt-in host hook / scheduler trigger support
from v2.4, but `README.md` and `AGENTS.md` still described the product as if it
had no IDE hook at all.

That leaves two of the highest-visibility docs with a stale absolute statement
about hook capabilities.

## What Changes

- Update `README.md` and `AGENTS.md` so they say there is no default automatic
  always-on note-taking path, but opt-in host hooks / scheduler triggers do
  exist and default to `off`.
- Add a focused regression test that fails fast if either file drifts back to
  the older absolute “no IDE hook” wording.

## Impact

- Readers now get a product narrative that matches the shipped v2.4 capability
  boundary.
- Future edits that erase the opt-in hook path fail fast in CI.
