## ADDED Requirements

### Requirement: Wiki bridge compiles generated claims from explicit sources only

The system SHALL compile generated wiki/claim artifacts only from accepted
memory and curated docs already declared in the knowledge-cache boundary.

#### Scenario: Compile accepted memory and curated docs into generated claims

- **GIVEN** a project has prepared knowledge-cache metadata
- **AND** it has accepted memory and at least one curated doc
- **WHEN** the wiki bridge compiler runs
- **THEN** it writes generated claim/index artifacts under `knowledge-cache/generated/`
- **AND** every generated claim records its source memory/doc identifiers
- **AND** no confirmed rule, memory entry, relation fact, or observation is mutated

### Requirement: Compact claim index supports drilldown

The system SHALL provide a compact index that lets an Agent inspect short claims
and then drill down to the underlying source evidence.

#### Scenario: Claim drilldown points back to source

- **WHEN** an Agent inspects a generated claim
- **THEN** the claim includes compact text plus topic/entity metadata
- **AND** it includes drilldown pointers to memory entry ids, observation ids, or curated doc paths
- **AND** the underlying source can be fetched without trusting the generated claim as truth

### Requirement: Generated claims do not become hidden truth

Generated wiki artifacts SHALL remain generated authority and SHALL NOT silently
enter wake/current truth surfaces.

#### Scenario: Generated claims stay out of default truth surfaces

- **GIVEN** a generated claim exists for a project
- **WHEN** default wake or current-truth search runs
- **THEN** the generated claim is not returned as confirmed truth
- **AND** the operator can still inspect it through explicit generated/wiki surfaces
