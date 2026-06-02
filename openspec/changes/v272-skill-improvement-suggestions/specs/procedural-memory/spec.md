## ADDED Requirements

### Requirement: Low-success skills produce reviewed improvement suggestions

The system SHALL turn low-success skills into reviewed improvement suggestions
instead of rewriting confirmed skills directly.

#### Scenario: Detector creates pending suggestion for low-success skill

- **GIVEN** a confirmed skill has `success_rate < 0.5` or repeated zero-success use
- **WHEN** the detector runs
- **THEN** a pending `skill_revision_suggestion` candidate is created
- **AND** the confirmed skill remains unchanged

### Requirement: Revision suggestions preserve provenance

Revision suggestions SHALL carry current skill metrics and supporting recent
success/failure signal ids.

#### Scenario: Suggestion includes failure evidence

- **GIVEN** a low-success skill has recent `skill_result_failure` signals
- **WHEN** a revision suggestion is created
- **THEN** the candidate includes the current success/failure counters
- **AND** the recent supporting signal ids

### Requirement: Accepting a suggestion does not rewrite the skill

Accepting or rejecting a revision suggestion SHALL only change the candidate's
review status.

#### Scenario: Confirm suggestion without rewriting

- **GIVEN** a pending revision suggestion
- **WHEN** it is confirmed
- **THEN** the candidate status becomes accepted
- **AND** the source skill body remains unchanged
