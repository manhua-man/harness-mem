## Why

The runtime has long treated `distill.mode` as a
`defer_to_agent|inline|worker` config enum, and the tests only accept those
values. But `roadmap-v24` still carried `notify_only` / `embedded_llm`, which
can mislead operators into expecting a shipped config value the current loader
will reject.

## What Changes

- Update the remaining v2.4 roadmap wording to use the shipped `distill.mode`
  values.
- Clarify in release/status docs that current runtime behavior still defaults to
  `defer_to_agent`; `inline` / `worker` do not imply a shipped always-on or
  default LLM path.
- Extend the focused config-truth guard to cover `distill.mode`.

## Impact

- Current docs stop teaching config values the shipped loader rejects.
- Future edits that reintroduce `notify_only` or `embedded_llm` into
  current-truth docs will fail fast in CI.
