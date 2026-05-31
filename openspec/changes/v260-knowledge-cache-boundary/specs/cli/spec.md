## ADDED Requirements

### Requirement: Knowledge cache boundary is explicit and visible

The system SHALL keep manual authority and generated outputs in separate
project-scoped runtime directories and SHALL make the mapping visible through a
sync map or doctor surface.

#### Scenario: Prepare boundary metadata

- **WHEN** the operator runs `harness-mem maintenance prepare-knowledge-cache --project <name>`
- **THEN** the system creates separate `manual/` and `generated/` directories
- **AND** it persists a sync map describing accepted-memory and curated-doc sources
- **AND** it persists a source manifest containing source hashes
- **AND** it does not create, confirm, supersede, or delete canonical truth

### Requirement: Doctor reports knowledge-cache drift without mutating truth

The doctor command SHALL report the current knowledge-cache boundary, stale or
missing sources, and orphaned generated outputs without compiling or repairing
them as a side effect.

#### Scenario: Doctor reports stale sources and orphaned generated outputs

- **GIVEN** a project has prepared knowledge-cache metadata
- **AND** one curated source changed or disappeared
- **AND** one generated file is not tracked by the generated index
- **WHEN** `harness-mem doctor -p <project>` runs
- **THEN** doctor reports the manual/generated boundary
- **AND** it reports the stale source count
- **AND** it reports the orphaned generated output count
- **AND** it points at `harness-mem maintenance cleanup-generated-cache --project <project> --apply`

### Requirement: Generated-cache cleanup is confined to generated outputs

The cleanup action SHALL remove only orphaned generated outputs and SHALL NOT
delete accepted memory, confirmed rules, relation facts, or curated docs.

#### Scenario: Cleanup removes orphaned generated file only

- **GIVEN** the generated cache contains one tracked file and one orphaned file
- **WHEN** `harness-mem maintenance cleanup-generated-cache --project <name> --apply` runs
- **THEN** the orphaned generated file is removed
- **AND** the tracked generated file remains
- **AND** canonical storage under structured/verbatim stores remains unchanged
