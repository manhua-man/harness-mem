## ADDED Requirements

### Requirement: Candidate review surface includes metabolism suggestion candidates

The system SHALL expose pending `MergeSuggestionCandidate` and
`StaleTruthSuggestionCandidate` rows through the same candidate review surface
used for ordinary pending review items.

#### Scenario: list_candidates returns merge and stale suggestion candidates

- **GIVEN** a project has one pending merge suggestion and one pending stale-truth suggestion
- **WHEN** `list_candidates(project_name, status="pending")` runs
- **THEN** both suggestion candidates appear in the returned `candidates` list
- **AND** the payload includes per-type counts for merge and stale suggestions
- **AND** ordinary rule/memory/fact/supersede/procedural candidates remain present unchanged

### Requirement: Suggestion visibility does not widen truth consumption

Review-surface visibility for merge/stale/contradiction suggestions SHALL NOT
cause those suggestion records, or generated wiki evidence that helped produce
them, to appear as confirmed truth in default runtime reads.

#### Scenario: reviewable suggestions stay outside default truth surfaces

- **GIVEN** a project has pending merge/stale suggestion candidates
- **WHEN** default wake or current-truth search runs
- **THEN** the suggestion candidates do not appear as confirmed truth
- **AND** any generated/wiki evidence associated with them remains inspectable only through explicit review or generated surfaces
