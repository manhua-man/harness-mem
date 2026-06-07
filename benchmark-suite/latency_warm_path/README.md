# Latency Warm Path

Standalone warm-path latency driver for the benchmark suite.

The driver seeds an isolated temporary harness-mem data directory, warms the
read paths, samples latency, and writes a complete run bundle under
`benchmark-suite/artifacts/`.

It does not use `~/.harness-mem`, does not call MCP stdio, and does not modify
the product runtime.

## Quick Start

```bash
python benchmark-suite/latency_warm_path/driver.py ^
  --run-name local-pass-01 ^
  --workspace F:\\memory-lab\\harness-mem ^
  --samples 20 ^
  --warmup 5
```

Validate and render:

```bash
python benchmark-suite/tools/validate_run.py ^
  --run-dir benchmark-suite/artifacts/<created-run-dir>

python benchmark-suite/tools/render_report.py ^
  --run-dir benchmark-suite/artifacts/<created-run-dir>
```

## Tasks

- `wake_synthetic`: list/select wake entries, confirmed rules, and handoffs.
- `search_fts`: structured memory search with `mode=fts`.
- `search_hybrid`: structured memory search with `mode=hybrid`.

If optional embedding dependencies or persisted vectors are unavailable,
`search_hybrid` may report `effective_mode=fts` with a fallback reason. That is
a valid first-run result, not a driver failure.

## Result Schema

`result.schema.json` documents the full result payload. `suite.json` still
defines the minimal cross-suite fields consumed by the generic validator.
