## Why

The runtime has long treated `triggers.scheduler` as an `off|on` config gate,
and the tests only accept those values. But a remaining v2.4 roadmap table
still described that key as `off|cron`, which can mislead operators into
writing a value the current loader will reject.

## What Changes

- Update the remaining v2.4 roadmap and operator docs to use `off|on` for
  `triggers.scheduler`.
- Clarify that `on` enables a scheduler/cron host-trigger path but does not
  mean the runtime now ships a cron-expression schema or installer.
- Extend the focused config-truth guard to cover `triggers.scheduler`.

## Impact

- Current docs stop teaching a configuration value the shipped loader rejects.
- Future edits that reintroduce `off|cron` into current-truth docs will fail
  fast in CI.
