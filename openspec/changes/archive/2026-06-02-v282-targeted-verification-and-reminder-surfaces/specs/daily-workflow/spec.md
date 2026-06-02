## ADDED Requirements

### Requirement: Targeted verification is an explicit maintenance entry

The system SHALL treat `/hm:verify-entry <session-id|keyword>` and its
natural-language equivalents as the formal user-facing entry for targeted
knowledge-base recheck.

#### Scenario: Verify-entry returns matching entries and recheck questions

- **WHEN** the operator runs `/hm:verify-entry <session-id|keyword>`
- **THEN** the system returns matching knowledge entries
- **AND** it includes grill-style recheck questions for each match

### Requirement: Maintenance reminders are summary-only nudges

Review and overlap reminders SHALL stay advisory and SHALL NOT silently mutate
knowledge or confirmed truth.

#### Scenario: Review-baseline reminder after knowledge growth

- **GIVEN** the knowledge base has grown beyond the configured reminder threshold
- **WHEN** a session is marked `distilled`
- **THEN** the summary may suggest `/hm:review-kb --next <n>`
- **AND** the mark flow still completes if all closure guardrails passed

#### Scenario: Overlap reminder after packet or note creation

- **GIVEN** a new packet or session note overlaps earlier knowledge entries
- **WHEN** the maintenance summary is rendered
- **THEN** the summary may suggest `/hm:verify-entry <keyword>`
- **AND** it does not auto-prune, auto-supersede, or block distill completion
