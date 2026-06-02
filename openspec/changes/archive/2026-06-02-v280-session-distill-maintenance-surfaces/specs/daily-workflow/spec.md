## ADDED Requirements

### Requirement: Session closure uses explicit maintenance guardrails

The system SHALL treat `/hm:mark <session-id> distilled [--keep-raw]` and its
natural-language equivalents as the formal user-facing entry for closing one
distilled session. A session SHALL NOT be marked `distilled` unless the
required session note, raw-review, promotion, draft, and knowledge-base
guardrails are satisfied.

#### Scenario: Distilled session passes all guardrails

- **GIVEN** a session has a completed note, reviewed raw transcript, explicit
  promotion decision, cleared memory draft state, and no unstable same-source
  knowledge-base entries
- **WHEN** the operator runs `/hm:mark <session-id> distilled`
- **THEN** the session is marked `distilled`
- **AND** the response names any follow-up reminder without requiring a
  separate review workflow

#### Scenario: Missing guardrail blocks closure

- **GIVEN** one required note or draft guardrail is still missing
- **WHEN** the operator tries to mark the session `distilled`
- **THEN** the session is not marked `distilled`
- **AND** the response identifies the missing guardrail

### Requirement: Manifest cleanup is confined to handled placeholders

The system SHALL treat `/hm:prune --statuses distilled,skipped --source-missing`
and its natural-language equivalents as cleanup for handled manifest
placeholders only.

#### Scenario: Cleanup removes source-missing handled placeholder only

- **GIVEN** a manifest row is already `distilled` or `skipped`
- **AND** its raw source is missing
- **WHEN** the operator runs `/hm:prune --statuses distilled,skipped --source-missing`
- **THEN** the handled placeholder may be cleaned up
- **AND** no confirmed rule, accepted memory entry, relation fact, shared skill,
  or unrelated raw transcript is mutated

#### Scenario: Cleanup does not remove active unresolved work

- **GIVEN** a manifest row is still unresolved or its source still exists
- **WHEN** the operator runs the prune flow
- **THEN** that row is not cleaned up merely because prune ran

### Requirement: Raw deletion stays inside explicit mark flow

Raw transcript deletion SHALL only occur as part of the explicit mark flow and
shall remain opt-out via `--keep-raw`.

#### Scenario: Keep-raw bypass preserves transcript

- **GIVEN** a session otherwise satisfies closure guardrails
- **WHEN** the operator runs `/hm:mark <session-id> distilled --keep-raw`
- **THEN** the session may still be marked `distilled`
- **AND** the raw transcript is preserved
