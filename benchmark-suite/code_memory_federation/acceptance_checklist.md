# Acceptance Checklist

- [ ] Every result row has `benchmark_id=code_memory_federation`.
- [ ] File evidence includes source id, path, fingerprint, and optional line range.
- [ ] Stale checks fail when a memory fingerprint differs from current code.
- [ ] `generated_layer_is_truth` is false for generated wiki/module-atlas rows.
- [ ] The report does not borrow codedb-mcp token/runtime results as harness-mem gains.
