## Why

The runtime has long treated `worker.mode` as an `off|on` config gate, and the
tests explicitly reject `worker.mode = "daemon"`. But a few high-visibility v2.4
docs still described that setting as `off|daemon`, which can mislead operators
into writing a value the current loader will reject.

## What Changes

- Update the remaining v2.4 roadmap and status docs to use `worker.mode=on` as
  the current non-default gate.
- Clarify that `on` does not mean the product now ships a default always-on
  daemon installer or background path.
- Add a focused regression test that ties the docs back to the runtime
  recognized-key truth.

## Impact

- Operator docs stop teaching a configuration value the current runtime
  considers invalid.
- Future edits that reintroduce `worker.mode=daemon` into current-truth docs
  will fail fast in CI.
