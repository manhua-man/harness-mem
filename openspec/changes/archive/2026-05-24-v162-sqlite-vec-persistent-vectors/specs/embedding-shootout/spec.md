# embedding-shootout Specification

## Purpose
Define the embedding model evaluation process, decision rules, and reporting format for selecting the default embedding model.

## ADDED Requirements

### Requirement: three-model LongMemEval benchmark

The system SHALL run LongMemEval benchmark on all three candidate models:
- `all-MiniLM-L6-v2` (baseline)
- `bge-small-en-v1.5`
- `nomic-embed-text-v1.5`

Each model MUST be evaluated on the full 500-question dataset with five-dimension breakdown (multi-session, temporal-reasoning, single-session-user, single-session-preference, single-session-assistant, knowledge-update).

#### Scenario: shootout runs three full benchmarks
- **WHEN** user runs `python -m harness_mem.tools.embedding_shootout`
- **THEN** system runs LongMemEval three times (once per model)
- **THEN** each run produces five-dimension R@5 scores

### Requirement: decision rule matching

The system SHALL apply the following decision rules in order (first match wins):

1. If any candidate has **all 5 dimensions ≥ baseline** (≤0pp regression) AND **≥2 dimensions with +1pp improvement**, select it. If multiple candidates match, select the one with highest total R@5.
2. If no candidate satisfies rule 1, but any candidate has **≥4 dimensions ≥ baseline** AND **≥1 dimension with +2pp improvement**, select it.
3. If neither rule 1 nor rule 2 is satisfied, **keep `all-MiniLM-L6-v2` unchanged**.

#### Scenario: rule 1 match selects bge-small
- **WHEN** bge-small has all 5 dimensions ≥ baseline and 2 dimensions +1pp
- **THEN** system selects `bge-small-en-v1.5` as default model

#### Scenario: rule 3 fallback keeps baseline
- **WHEN** no candidate satisfies rule 1 or rule 2
- **THEN** system keeps `all-MiniLM-L6-v2` as default
- **THEN** report documents "No model met improvement criteria"

### Requirement: shootout report generation

The system SHALL generate `docs/benchmark/v162-embedding-shootout.md` containing:
- Five-dimension R@5 table for all three models
- Total R@5 comparison
- Decision rule matching results (which rule triggered, which model selected)
- Model metadata (size, dimensions, license)
- Recommendation section with selected model and rationale

#### Scenario: report documents decision
- **WHEN** shootout completes
- **THEN** `docs/benchmark/v162-embedding-shootout.md` exists
- **THEN** report contains five-dimension table with baseline comparison
- **THEN** report states which decision rule matched and final selection

### Requirement: baseline reference

The system SHALL use v1.6.0 baseline from `docs/benchmark/v160-baseline.md` as the comparison anchor. The baseline model is `all-MiniLM-L6-v2` with hybrid (real) mode R@5 = 0.953.

#### Scenario: shootout loads v1.6.0 baseline
- **WHEN** shootout runs
- **THEN** system reads `docs/benchmark/v160-baseline.md` for baseline scores
- **THEN** all comparisons use v1.6.0 hybrid (real) as reference

### Requirement: tiebreaker priority

The system SHALL use the following tiebreaker priority when multiple models satisfy the same decision rule with equal total R@5:
1. `bge-small-en-v1.5`
2. `nomic-embed-text-v1.5`
3. `all-MiniLM-L6-v2`

#### Scenario: tiebreaker selects bge-small
- **WHEN** both bge-small and nomic-embed satisfy rule 1 with equal R@5
- **THEN** system selects `bge-small-en-v1.5` per tiebreaker priority

### Requirement: shootout CLI tool

The system SHALL provide `python -m harness_mem.tools.embedding_shootout` CLI tool that:
- Accepts `--output <path>` to specify report output location (default: `docs/benchmark/v162-embedding-shootout.md`)
- Accepts `--baseline <path>` to specify baseline file (default: `docs/benchmark/v160-baseline.md`)
- Runs all three benchmarks sequentially
- Applies decision rules
- Generates report

#### Scenario: shootout tool runs end-to-end
- **WHEN** user runs `python -m harness_mem.tools.embedding_shootout`
- **THEN** tool runs three LongMemEval benchmarks
- **THEN** tool applies decision rules
- **THEN** tool writes report to `docs/benchmark/v162-embedding-shootout.md`
- **THEN** tool prints selected model to stdout
