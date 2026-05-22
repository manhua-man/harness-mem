## 1. Dependencies and Schema

- [x] 1.1 Add `sqlite-vec>=0.1.0` to `pyproject.toml` under `[project.optional-dependencies] hybrid`
- [x] 1.2 Create `vec_embeddings` table schema in `harness_mem/storage/sqlite_index.py` with columns: entry_id (PK), model_id, model_version, embedding (BLOB), created_at
- [x] 1.3 Add table creation logic to `SQLiteIndex._init_tables()` for both verbatim and structured indexes
- [x] 1.4 Implement Windows-compatible extension loading: call `connection.enable_load_extension(True)` before loading sqlite-vec
- [x] 1.5 Add try/except for `OperationalError` during extension loading with HM-202 error code

## 2. Embedding Model Configuration

- [x] 2.1 Add `[embedding]` section to config schema with `model_id` field (default: "all-MiniLM-L6-v2")
- [x] 2.2 Create `harness_mem/embedding/model_registry.py` with three model definitions: all-MiniLM-L6-v2, bge-small-en-v1.5, nomic-embed-text-v1.5
- [x] 2.3 Implement model loader that validates `model_id` against registry and raises HM-203 for unsupported models
- [x] 2.4 Extract `model_version` from loaded model metadata or package version
- [x] 2.5 Add lazy loading logic: load model on first encode call, not at import time

## 3. Write Path: Persist Embeddings

- [x] 3.1 Create `_persist_embedding(entry_id, text, model_id, model_version)` helper in `sqlite_index.py`
- [x] 3.2 Integrate `_persist_embedding` into `LocalVerbatimStore.save_observation()` after writing observation
- [x] 3.3 Integrate `_persist_embedding` into `LocalStructuredStore.save_memory_entry()` after writing memory entry
- [x] 3.4 Serialize numpy array to BLOB using `np.array.tobytes()`
- [ ] 3.5 Add progress logging for batch ingest: "Encoding embeddings: X/Y" (deferred to v1.6.3 batch encode; v1.6.2 rebuild command prints project-level progress)

## 4. Read Path: Query Persisted Vectors

- [x] 4.1 Modify `HybridSearchLayer._search_hybrid()` to query `vec_embeddings` via SQL JOIN instead of calling `model.encode` on candidate pool
- [x] 4.2 Add SQL query: `SELECT entry_id, embedding FROM vec_embeddings WHERE entry_id IN (?) AND model_id = ?`
- [x] 4.3 Deserialize BLOB to numpy array using `np.frombuffer(blob, dtype=np.float32).reshape(-1, dim)`
- [x] 4.4 Keep query-side encoding: call `model.encode(query_text)` exactly once
- [x] 4.5 Compute cosine similarity between query vector and persisted vectors
- [x] 4.6 Apply RRF fusion with FTS scores (keep existing RRF logic)

## 5. Fallback and Error Handling

- [x] 5.1 Implement fallback to FTS when `vec_embeddings` table does not exist
- [x] 5.2 Implement fallback to FTS when `vec_embeddings` table is empty
- [x] 5.3 Add dimension mismatch detection: log warning and skip mismatched vectors
- [x] 5.4 If all vectors are filtered out (model_id mismatch or dimension mismatch), fallback to FTS
- [x] 5.5 Log clear warnings for each fallback scenario

## 6. Doctor and Maintenance Commands

- [x] 6.1 Extend `harness-mem doctor` to detect missing `vec_embeddings` table (HM-201 error code)
- [x] 6.2 Extend `harness-mem doctor` to detect model_id mismatch between config and stored vectors
- [x] 6.3 Extend `harness-mem doctor` to detect dimension mismatch
- [x] 6.4 Implement `harness-mem maintenance rebuild-vector-index --project <name>` command
- [x] 6.5 Rebuild command: drop existing `vec_embeddings` table, re-encode all entries, insert with current model_id/model_version
- [x] 6.6 Add progress output for rebuild: "Rebuilding vector index: X/Y entries"

## 7. Error Codes Documentation

- [x] 7.1 Add HM-201 to `docs/error-codes.md`: "Vector index not built. Run: harness-mem maintenance rebuild-vector-index"
- [x] 7.2 Add HM-202 to `docs/error-codes.md`: "SQLite extension loading disabled. Recompile sqlite or use FTS mode."
- [x] 7.3 Add HM-203 to `docs/error-codes.md`: "Unsupported embedding model. Supported: all-MiniLM-L6-v2, bge-small-en-v1.5, nomic-embed-text-v1.5"

## 8. Embedding Shootout Tool

- [x] 8.1 Create `harness_mem/tools/embedding_shootout.py` CLI tool
- [x] 8.2 Implement `--output <path>` flag (default: docs/benchmark/v162-embedding-shootout.md)
- [x] 8.3 Implement `--baseline <path>` flag (default: docs/benchmark/v160-baseline.md)
- [x] 8.4 Load v1.6.0 baseline scores from baseline file
- [x] 8.5 Run LongMemEval for all-MiniLM-L6-v2, capture six-dimension R@5
- [x] 8.6 Run LongMemEval for bge-small-en-v1.5, capture six-dimension R@5
- [x] 8.7 Run LongMemEval for nomic-embed-text-v1.5, capture six-dimension R@5
- [x] 8.8 Implement decision rule 1: all 6 dims ≥ baseline + ≥2 dims +1pp
- [x] 8.9 Implement decision rule 2: ≥4 dims ≥ baseline + ≥1 dim +2pp
- [x] 8.10 Implement decision rule 3: fallback to all-MiniLM-L6-v2
- [x] 8.11 Implement tiebreaker priority: bge-small > nomic-embed > all-MiniLM
- [x] 8.12 Generate report with six-dimension table, decision rule match, and recommendation
- [x] 8.13 Add progress output: "Running <model>: X/500 questions"

## 9. Testing

- [x] 9.1 Unit test: write embedding, verify row exists in `vec_embeddings` with correct model_id/model_version
- [x] 9.2 Unit test: restart process, verify vectors are read from DB without re-encoding
- [x] 9.3 Unit test: query with model_id filter, verify only matching vectors are used
- [x] 9.4 Unit test: switch model_id, verify old vectors are excluded from search
- [x] 9.5 Unit test: missing `vec_embeddings` table triggers FTS fallback
- [x] 9.6 Unit test: dimension mismatch triggers warning and fallback
- [x] 9.7 Unit test: rebuild-vector-index drops and recreates table
- [x] 9.8 Unit test: doctor detects HM-201, HM-202, HM-203 scenarios
- [x] 9.9 Integration test: run LongMemEval with persistent vectors, verify R@5 ≥ baseline on ≥3 dimensions (test exists and skips unless `LONGMEMEVAL_INTEGRATION=1`)

## 10. Benchmarking and Validation

- [x] 10.1 Run embedding shootout: `python -m harness_mem.tools.embedding_shootout`
- [x] 10.2 Verify shootout report is generated at `docs/benchmark/v162-embedding-shootout.md`
- [x] 10.3 Apply decision rule result: keep default model at `all-MiniLM-L6-v2` per rule 3 fallback
- [ ] 10.4 Run LongMemEval with final model, verify ≥3 dimensions do not regress (manual release gate; integration test is present but full run is not automatic)
- [ ] 10.5 Measure P95 latency with persistent vectors, verify ≤437ms (manual release gate; not claimed by CHANGELOG)

## 11. Documentation and Release

- [x] 11.1 Update `CHANGELOG.md` with v1.6.2 section documenting all changes
- [x] 11.2 Update `docs/roadmap-v16x.md` to mark v1.6.2 runtime complete with manual benchmark gates called out
- [x] 11.3 Document embedding model configuration in README or docs/
- [x] 11.4 Document rebuild-vector-index workflow for model switching
- [x] 11.5 Run full test suite: `python -m pytest -q`
- [x] 11.6 Run type checking: `python -m mypy harness_mem`
- [x] 11.7 Run linting: `python -m ruff check .`
