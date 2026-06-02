## ADDED Requirements

### Requirement: worker.mode docs follow the shipped config gate

Current-truth operator and roadmap docs SHALL describe `worker.mode` using the
same allowed values the shipped config loader recognizes.

#### Scenario: current docs keep off and on only

- **GIVEN** the config loader recognizes `worker.mode`
- **WHEN** maintainers update current operator or roadmap docs
- **THEN** those docs keep the allowed values aligned with the shipped loader
- **AND** focused regression tests fail if current-truth docs reintroduce
  `worker.mode=daemon`
