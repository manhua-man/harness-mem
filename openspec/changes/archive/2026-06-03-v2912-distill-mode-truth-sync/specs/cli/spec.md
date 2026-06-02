## ADDED Requirements

### Requirement: distill.mode docs follow the shipped config enum

Current-truth operator and roadmap docs SHALL describe `distill.mode` using the
same allowed values the shipped config loader recognizes.

#### Scenario: current docs keep shipped distill.mode values only

- **GIVEN** the config loader recognizes `distill.mode`
- **WHEN** maintainers update current operator or roadmap docs
- **THEN** those docs keep the allowed values aligned with the shipped loader
- **AND** focused regression tests fail if current-truth docs reintroduce
  `notify_only` or `embedded_llm`
