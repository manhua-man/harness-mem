## 1. Runtime fix

- [x] 1.1 Add a local-cache probe for embedding models.
- [x] 1.2 Skip write-path vec generation when the model is not cached locally.
- [x] 1.3 Keep the existing timeout/circuit-breaker behavior for cached-model hangs.

## 2. Evidence and docs

- [x] 2.1 Append a fresh-home, embeddings-enabled generic MCP smoke entry to `docs/v2-user-test-packet.md`.
- [x] 2.2 Update `docs/roadmap-status.md`, `docs/roadmap-v29.md`, changelog, and version files for `v2.9.56`.
- [x] 2.3 Add a focused regression guard for the packet writeback.

## 3. Validation

- [x] 3.1 `python -m pytest -q tests/test_disable_embeddings.py tests/test_v2_user_test_packet_fresh_home_embedding_truth.py`
- [x] 3.2 `python -m pytest -q --ignore=tests/benchmarks`
- [x] 3.3 `python -m ruff check harness_mem tests`
- [x] 3.4 `python -m mypy harness_mem`
- [x] 3.5 `openspec validate --all --strict`
- [x] 3.6 `python -m harness_mem.cli --version`
