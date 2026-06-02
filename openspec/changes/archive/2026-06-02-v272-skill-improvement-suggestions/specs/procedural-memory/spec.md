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

### Requirement: Duplicate pending revision suggestions are suppressed

The detector SHALL NOT create a second pending revision suggestion for the same
skill while an earlier pending suggestion already exists.

#### Scenario: Re-running detector does not duplicate pending review

- **GIVEN** a low-success skill already has a pending revision suggestion
- **WHEN** the detector runs again
- **THEN** no second pending revision suggestion is created for that skill

### Requirement: Shared-skill deprecation is review-gated

Stale or conflicting shared skills SHALL produce reviewed deprecation
suggestions rather than being retired automatically.

#### Scenario: Detect stale shared skill

- **GIVEN** a shared skill is inactive beyond the configured stale window
- **WHEN** the deprecation detector runs
- **THEN** a pending `skill_deprecation_suggestion` candidate is created
- **AND** the shared skill remains active until reviewed

#### Scenario: Confirm deprecation retires shared skill

- **GIVEN** a pending `skill_deprecation_suggestion`
- **WHEN** it is confirmed
- **THEN** the candidate status becomes accepted
- **AND** the shared skill status becomes `retired`
