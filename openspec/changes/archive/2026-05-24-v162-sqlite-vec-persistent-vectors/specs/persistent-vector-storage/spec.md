# persistent-vector-storage Specification

## Purpose
Define sqlite-vec integration for persistent vector storage, including schema, write/read paths, and upgrade/fallback semantics.

## ADDED Requirements

### Requirement: sqlite-vec as mandatory dependency

The system SHALL include `sqlite-vec>=0.1.0` in `pyproject.toml` under `[project.optional-dependencies] hybrid` as a mandatory dependency. Installation via `pip install "harness-mem[hybrid]"` MUST succeed with sqlite-vec available.

#### Scenario: hybrid extra installs sqlite-vec
- **WHEN** user runs `pip install "harness-mem[hybrid]"`
- **THEN** sqlite-vec package is installed and importable

### Requirement: vec_embeddings table schema

The system SHALL create a `vec_embeddings` table in both `verbatim_index.sqlite` and `structured_index.sqlite` with the following schema:
- `entry_id TEXT PRIMARY KEY`: foreign key to parent entry
- `model_id TEXT NOT NULL`: embedding model identifier (e.g., "all-MiniLM-L6-v2")
- `model_version TEXT NOT NULL`: model version string
- `embedding BLOB NOT NULL`: serialized vector (384 or 768 dimensions)
- `created_at INTEGER NOT NULL`: Unix timestamp

#### Scenario: table created on first hybrid ingest
- **WHEN** user runs `harness-mem ingest` with hybrid mode enabled
- **THEN** `vec_embeddings` table exists in both index databases

### Requirement: write path persists embeddings

The system SHALL persist embeddings during `ingest` and `save` operations. For each entry written to verbatim or structured store, the system MUST encode the text content and insert a row into `vec_embeddings` with `model_id`, `model_version`, and serialized `embedding`.

#### Scenario: ingest writes vectors to database
- **WHEN** user ingests a session with hybrid mode enabled
- **THEN** each observation/memory entry has a corresponding row in `vec_embeddings`

#### Scenario: model metadata is recorded
- **WHEN** system writes an embedding
- **THEN** the row contains the current `model_id` and `model_version`

### Requirement: read path queries persisted vectors

The system SHALL modify `HybridSearchLayer._search_hybrid` to query persisted vectors via SQL JOIN instead of calling `model.encode` on the candidate pool. Only the query text MUST be encoded at search time (1 call to `model.encode`).

#### Scenario: search uses persisted vectors
- **WHEN** user runs `harness-mem search "dark mode" --mode hybrid`
- **THEN** system performs SQL JOIN on `vec_embeddings` table
- **THEN** `model.encode` is called exactly once (for query text)

### Requirement: fallback to FTS when vectors missing

The system SHALL fallback to FTS mode when `vec_embeddings` table does not exist or is empty. The system MUST NOT raise an error; instead, it SHALL log a warning and proceed with FTS-only search.

#### Scenario: missing vec_embeddings table triggers FTS fallback
- **WHEN** user searches in hybrid mode but `vec_embeddings` table does not exist
- **THEN** system logs "vec_embeddings table not found, falling back to FTS"
- **THEN** search completes successfully using FTS mode

### Requirement: doctor detects missing vector index

The system SHALL extend `harness-mem doctor` to detect when `vec_embeddings` table is missing or empty. Doctor output MUST include error code `HM-201` with message "Vector index not built" and suggest running `harness-mem maintenance rebuild-vector-index`.

#### Scenario: doctor detects missing vectors
- **WHEN** user runs `harness-mem doctor` and `vec_embeddings` table is missing
- **THEN** output includes `HM-201: Vector index not built`
- **THEN** output suggests `harness-mem maintenance rebuild-vector-index`

### Requirement: rebuild-vector-index command

The system SHALL provide `harness-mem maintenance rebuild-vector-index --project <name>` command to rebuild the vector index from existing entries. The command MUST:
- Drop existing `vec_embeddings` table if present
- Re-encode all entries in verbatim and structured stores
- Insert new rows with current `model_id` and `model_version`

#### Scenario: rebuild command recreates vector index
- **WHEN** user runs `harness-mem maintenance rebuild-vector-index --project test`
- **THEN** `vec_embeddings` table is dropped and recreated
- **THEN** all entries are re-encoded and inserted

### Requirement: Windows sqlite extension loading

The system SHALL call `connection.enable_load_extension(True)` before loading sqlite-vec extension on Windows. The system MUST handle `OperationalError` if extension loading is disabled and provide clear error message with code `HM-202`.

#### Scenario: extension loading succeeds on Windows
- **WHEN** system initializes sqlite connection on Windows
- **THEN** `enable_load_extension(True)` is called
- **THEN** sqlite-vec extension loads successfully

#### Scenario: extension loading disabled
- **WHEN** sqlite is compiled without extension support
- **THEN** system raises error with code `HM-202: SQLite extension loading disabled`
- **THEN** error message suggests recompiling sqlite or using FTS mode
