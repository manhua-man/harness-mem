# embedding-model-selection Specification

## Purpose
Define multi-model support for embeddings, including model_id/model_version metadata, model switching, and vector filtering by version.

## ADDED Requirements

### Requirement: configurable embedding model

The system SHALL support three embedding models selectable via `~/.harness-mem/config.toml` under `[embedding] model_id`:
- `all-MiniLM-L6-v2` (default, 384 dim, 22MB)
- `bge-small-en-v1.5` (384 dim, ~130MB)
- `nomic-embed-text-v1.5` (768 dim, ~130MB)

#### Scenario: user selects bge-small model
- **WHEN** user sets `[embedding] model_id = "bge-small-en-v1.5"` in config
- **THEN** system loads bge-small model for encoding
- **THEN** new embeddings are written with `model_id = "bge-small-en-v1.5"`

#### Scenario: default model is all-MiniLM-L6-v2
- **WHEN** user does not specify `model_id` in config
- **THEN** system uses `all-MiniLM-L6-v2` as default

### Requirement: model metadata in vec_embeddings

The system SHALL store `model_id` and `model_version` in every `vec_embeddings` row. The `model_version` MUST be derived from the loaded model's metadata or package version.

#### Scenario: embedding row contains model metadata
- **WHEN** system writes an embedding for entry "obs_123"
- **THEN** `vec_embeddings` row contains `model_id = "all-MiniLM-L6-v2"` and `model_version = "1.0.0"`

### Requirement: filter vectors by model version

The system SHALL filter `vec_embeddings` rows during search to match the currently configured `model_id`. Rows with mismatched `model_id` MUST be excluded from the candidate pool.

#### Scenario: old vectors excluded after model switch
- **WHEN** user switches from `all-MiniLM-L6-v2` to `bge-small-en-v1.5`
- **WHEN** user runs `harness-mem search "test" --mode hybrid`
- **THEN** only embeddings with `model_id = "bge-small-en-v1.5"` are used
- **THEN** embeddings with `model_id = "all-MiniLM-L6-v2"` are ignored

### Requirement: rebuild after model switch

The system SHALL detect model mismatch during `harness-mem doctor` and suggest running `harness-mem maintenance rebuild-vector-index` to re-encode all entries with the new model.

#### Scenario: doctor detects model mismatch
- **WHEN** user switches model and runs `harness-mem doctor`
- **THEN** output includes warning "Vector index uses different model (all-MiniLM-L6-v2), current config is bge-small-en-v1.5"
- **THEN** output suggests `harness-mem maintenance rebuild-vector-index`

### Requirement: invalid model_id error

The system SHALL raise error with code `HM-203` when user specifies an unsupported `model_id` in config. Error message MUST list the three supported models.

#### Scenario: unsupported model_id
- **WHEN** user sets `[embedding] model_id = "unsupported-model"`
- **WHEN** system attempts to load embedding model
- **THEN** system raises `HM-203: Unsupported embedding model 'unsupported-model'. Supported: all-MiniLM-L6-v2, bge-small-en-v1.5, nomic-embed-text-v1.5`

### Requirement: dimension mismatch detection

The system SHALL detect dimension mismatch between stored embeddings and current model. If current model produces 768-dim vectors but stored embeddings are 384-dim, the system MUST exclude mismatched rows and log a warning.

#### Scenario: dimension mismatch triggers warning
- **WHEN** user switches from 384-dim model to 768-dim model
- **WHEN** user runs search without rebuilding index
- **THEN** system logs "Dimension mismatch: stored=384, current=768. Run rebuild-vector-index."
- **THEN** search uses only matching-dimension embeddings (if any) or falls back to FTS
