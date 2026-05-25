# persistent-vector-storage Specification

## Purpose

Defines persistent local vector storage for hybrid retrieval. Vectors are stored
inside harness-mem's local SQLite indexes and used by MCP/read API retrieval.
CLI involvement is limited to maintenance commands such as
`harness-mem maintenance rebuild-vector-index`.

## Requirements

### Requirement: sqlite-vec as hybrid dependency

The system SHALL include `sqlite-vec>=0.1.0` under `[project.optional-dependencies] hybrid`.

#### Scenario: hybrid extra installs sqlite-vec

- **WHEN** user runs `pip install "harness-mem[hybrid]"`
- **THEN** sqlite-vec package is installed and importable

### Requirement: vec_embeddings table schema

The system SHALL create a `vec_embeddings` table in both `verbatim_index.sqlite`
and `structured_index.sqlite` with `entry_id`, `model_id`, `model_version`,
`embedding`, and `created_at`.

#### Scenario: table created on first hybrid write

- **WHEN** an observation or memory entry is saved with hybrid support enabled
- **THEN** `vec_embeddings` table exists in the relevant index database

### Requirement: write path persists embeddings

For each entry written to verbatim or structured store, the system MUST encode
the text content and insert a row into `vec_embeddings` with model metadata and
serialized embedding.

#### Scenario: save writes vectors to database

- **WHEN** system saves an observation or memory entry
- **THEN** the entry has a corresponding row in `vec_embeddings`

### Requirement: read path queries persisted vectors

`HybridSearchLayer._search_hybrid` SHALL query persisted vectors instead of
encoding candidate pool text. Only the query text MUST be encoded at search time.

#### Scenario: MCP search uses persisted vectors

- **WHEN** `search_memory` is called with `mode="hybrid"`
- **THEN** system reads candidate vectors from `vec_embeddings`
- **THEN** `model.encode` is called exactly once for query text

### Requirement: fallback to FTS when vectors missing

The system SHALL fallback to FTS mode when `vec_embeddings` table does not exist
or is empty.

#### Scenario: missing vec_embeddings table triggers FTS fallback

- **WHEN** hybrid search runs but `vec_embeddings` table does not exist
- **THEN** search completes successfully using FTS mode

### Requirement: doctor detects missing vector index

`harness-mem doctor` SHALL detect missing or empty vector index and suggest
`harness-mem maintenance rebuild-vector-index`.

#### Scenario: doctor detects missing vectors

```text
$ harness-mem doctor
HM-201: Vector index not built
Fix: harness-mem maintenance rebuild-vector-index --project <project>
```

### Requirement: rebuild-vector-index command

The system SHALL provide `harness-mem maintenance rebuild-vector-index --project <name>`
to rebuild vector rows from existing local entries.

#### Scenario: rebuild command recreates vector index

```bash
$ harness-mem maintenance rebuild-vector-index --project test
Rebuilding vector index: test
```

### Requirement: Windows sqlite extension loading

The system SHALL call `connection.enable_load_extension(True)` before loading
sqlite-vec extension on Windows, and SHALL surface `HM-202` when extension
loading is disabled.

#### Scenario: extension loading disabled

- **WHEN** sqlite is compiled without extension support
- **THEN** system raises or reports `HM-202: SQLite extension loading disabled`

