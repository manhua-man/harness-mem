# Rust Core Hot Path

Benchmark id: `rust_core_hot_path`

Purpose: validate the v4.0.2 Rust-core facade, tolerant JSONL scanner, ranking
primitives, error mapping, and pure-Python fallback when a native wheel is not
available.

Claim boundary: contract/fallback smoke only. This does not prove native Rust
performance or cross-platform wheel availability.
