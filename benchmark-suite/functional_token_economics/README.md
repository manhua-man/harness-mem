# Functional Token Economics

This collection measures feature-level context-token economics in the style of
the claude-mem marketing claims, but with narrower claim boundaries.

It does not try to prove that the whole `harness-mem` product saves tokens.
Instead, it asks whether specific progressive-disclosure workflows produce
smaller context payloads than full-source or full-history baselines on declared
fixture/source corpora.

## Scenarios

| Scenario | Harness-mem pattern | Baseline |
|---|---|---|
| `FTE1` | progressive recall: compact search/timeline/details | full source recovery across broad docs |
| `FTE2` | file context preflight | full target file read |
| `FTE3` | compact wake | broad session/status context |
| `FTE4` | wiki compact index | direct multi-doc read |

## Measurement

The runner reads `scenarios.json`, loads baseline sources from the current
workspace, counts tokens with `harness_mem.commands.token_estimator`, counts the
declared compact payload, and writes one result JSON per scenario.

Result deltas are:

```text
token_delta = baseline_tokens - optimized_tokens
saving_ratio = token_delta / baseline_tokens
```

The compact payloads are fixture/golden payloads. They prove the economics of
the workflow shape on the declared corpus; they do not prove that a live agent
will always choose the compact path.

## Claim Boundary

Passing this benchmark may support a bounded statement like:

> In the functional token-economics fixture benchmark, the compact
> progressive-disclosure workflow reduced estimated context tokens by X%.

It does not prove:

- global product token/cost savings
- real billing savings
- live-agent behavior in every client
- answer quality improvements
- code-intelligence performance comparable to `codedb-mcp` or claude-mem Smart
  Explore

## Run

```bash
python benchmark-suite/functional_token_economics/driver.py --run-name local-01
python benchmark-suite/tools/render_report.py --run-dir benchmark-suite/artifacts/<run-dir>
python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/<run-dir>
```
