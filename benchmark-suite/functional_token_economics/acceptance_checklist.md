# Acceptance Checklist: `functional_token_economics`

Use this checklist before citing any feature-level token-economics number.

## Bundle Checks

- [ ] `benchmark_id` is `functional_token_economics`.
- [ ] `run_manifest.json`, `report.md`, `summary.csv`, `results/`, and
      `notes/scenarios.json` are present.
- [ ] Every result records `baseline_tokens`, `optimized_tokens`,
      `token_delta`, `saving_ratio`, `tokenizer`, source lists, and
      `claim_scope`.
- [ ] Every baseline source path exists in the measured workspace.
- [ ] `fixture_only=true` is preserved unless the run uses live tool outputs.
- [ ] The report includes both the feature-level readiness and the global
      token/cost non-claim.

## Scenario Checks

- [ ] `FTE1` measures progressive recall against a wider source-recovery
      baseline.
- [ ] `FTE2` measures file-context preflight against a full target-file read.
- [ ] `FTE3` measures compact wake against broad session/status context.
- [ ] `FTE4` measures wiki compact index against direct multi-doc reading.
- [ ] Optimized payloads cite source IDs or source paths; compact prose is not
      treated as authority.
- [ ] Each scenario meets its declared `minimum_saving_ratio`.

## Claim Gate

Feature-level fixture token-economics can be cited only when all scenarios are
accepted and every scenario has `saving_ratio > 0`.

Do not cite this benchmark as:

- global `harness-mem` token/cost saving
- real billing saving
- proof that every live agent will choose the compact path
- a code-intelligence benchmark
