## ADDED Requirements

### Requirement: Wake supports opt-in compact skill hints

Default wake SHALL remain unchanged unless an explicit skill-hint option is
enabled.

#### Scenario: Default wake excludes skill hints

- **WHEN** `wake(project_name="demo")` runs without a hint option
- **THEN** no compact skill-hint section is rendered
- **AND** the existing default wake text remains unchanged

#### Scenario: Opt-in wake shows compact skill hints only

- **GIVEN** a project has confirmed skills
- **WHEN** `wake(project_name="demo", include_skill_hints=true)` runs
- **THEN** wake renders a compact skill-hint section
- **AND** each hint contains only id, title, and reason
- **AND** no full procedural steps are rendered

### Requirement: Skill hints use a separate small budget

Skill hints SHALL use a separate small budget and SHALL NOT displace L0/L1/L2
truth entries from the existing wake plan.

#### Scenario: Enabling skill hints does not shrink truth sections

- **GIVEN** a wake plan that already fills its L0/L1/L2 budgets
- **WHEN** skill hints are enabled
- **THEN** the rendered L0/L1/L2 sections stay unchanged
- **AND** any skill-hint count or token accounting is tracked separately
