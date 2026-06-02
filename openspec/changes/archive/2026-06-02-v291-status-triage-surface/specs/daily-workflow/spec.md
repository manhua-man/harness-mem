## ADDED Requirements

### Requirement: Status is an explicit read-only triage entry

The system SHALL treat `/hm:status` and its natural-language equivalents as a
formal user-facing read-only entry for project memory triage.

#### Scenario: Empty project suggests distill

- **GIVEN** a project has no observations yet
- **WHEN** the operator runs `/hm:status`
- **THEN** the system reports an empty/needs-distill phase
- **AND** it suggests `/hm:distill` as the primary next step

#### Scenario: Ready project suggests wake and only hints review

- **GIVEN** a project already has usable memory context
- **WHEN** the operator runs `/hm:status`
- **THEN** the system reports a ready phase
- **AND** it suggests `/hm:wake` as the primary next step
- **AND** if pending candidates exist, it may include `/hm:review` as an
  explicit repair hint rather than the main happy-path next step
