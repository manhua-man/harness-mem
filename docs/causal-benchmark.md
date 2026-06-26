# Causal Benchmark Smoke

`harness-mem` 0.8.2 includes a small deterministic benchmark for typed relation
recall. It is an internal release-gate test, not a public CLI workflow:

```bash
python -m pytest tests/test_core_memory_absorption.py -k causal_benchmark
```

Capability boundary: this is not a Daily command, not a default MCP tool, and
not a public product-quality score.

The benchmark seeds a temporary local memory store with:

- one semantic distractor
- one two-hop causal chain
- accepted relation facts using typed edges such as `caused_by`

It then verifies that bounded relation tracing recovers the gold root cause.

## What it proves

The smoke test proves the local typed-edge traversal path is wired and can beat
a semantically similar distractor in one controlled fixture.

## What it does not prove

It is not a broad retrieval-quality claim. It does not benchmark arbitrary
projects, embeddings, LLM extraction, or long-horizon memory quality. Treat it
as a release gate for the causal recall plumbing, not as a product-wide score.
