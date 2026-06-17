# storage-runtime Specification

## Purpose

定义 canonical SQLite truth runtime、首启 bootstrap/migration、degraded
fallback 可见性，以及 export/rollback 兼容边界。

## Requirements

### Requirement: Canonical SQLite is the default truth runtime

The system SHALL use canonical SQLite as the default truth store for structured
entities and verbatim observations. Legacy JSON blobs SHALL NOT be the default
runtime read source once canonical bootstrap succeeds.

#### Scenario: Fresh install bootstraps canonical runtime

- **WHEN** a backend initializes against an empty data directory
- **THEN** the system creates and initializes the canonical store
- **AND** the runtime state is `canonical`
- **AND** no legacy JSON payloads are required for reads or writes

#### Scenario: Structured and verbatim writes persist canonical truth

- **WHEN** the runtime saves a memory entry or observation after bootstrap
- **THEN** the payload is written to canonical SQLite as truth
- **AND** any FTS, vector, trigram, or other generated index writes are treated as derived index maintenance

### Requirement: Canonical bootstrap migrates legacy truth once

The system SHALL automatically bootstrap canonical truth from legacy JSON
payloads when legacy data exists and canonical runtime state is missing or
incomplete.

#### Scenario: Existing legacy install auto-migrates on first bootstrap

- **GIVEN** a data directory contains legacy structured and verbatim JSON payloads
- **AND** canonical runtime state is missing
- **WHEN** the backend initializes
- **THEN** the system migrates legacy payloads into canonical SQLite
- **AND** the resulting logical checksum matches the legacy payload checksum
- **AND** the runtime state is `bootstrapped_from_legacy`

#### Scenario: Repeated bootstrap is idempotent

- **GIVEN** canonical bootstrap already completed successfully
- **WHEN** the backend initializes again
- **THEN** the system does not duplicate canonical truth rows
- **AND** the logical checksum remains unchanged

### Requirement: Degraded fallback is explicit and recoverable

The system SHALL expose a degraded fallback state when canonical bootstrap or
migration fails. The fallback SHALL be visible to maintenance surfaces and SHALL
include a recovery path.

#### Scenario: Failed canonical migration enters degraded fallback

- **GIVEN** legacy data exists and automatic canonical bootstrap encounters a migration error
- **WHEN** the backend initializes
- **THEN** the runtime state is `degraded_fallback`
- **AND** the system exposes a maintenance recovery hint
- **AND** the failure is not reported as a healthy canonical runtime

### Requirement: Canonical runtime preserves rollback compatibility

The system SHALL continue to support explicit JSON snapshot export and
rollback-compatible payload generation from canonical truth.

#### Scenario: Canonical export rebuilds a legacy-compatible snapshot

- **GIVEN** canonical truth exists for a project
- **WHEN** the operator runs the export or rollback maintenance path
- **THEN** the system writes legacy-compatible JSON payloads
- **AND** the exported logical checksum matches the canonical truth checksum
