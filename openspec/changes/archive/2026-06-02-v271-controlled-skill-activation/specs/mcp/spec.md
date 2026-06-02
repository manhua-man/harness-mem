## ADDED Requirements

### Requirement: MCP wake exposes opt-in skill hints

MCP `wake` SHALL support an explicit parameter for appending compact skill
hints to the default wake output.

#### Scenario: MCP wake returns skill hints only when requested

- **GIVEN** a project has confirmed skills
- **WHEN** `wake(project_name="demo", include_skill_hints=true)` runs
- **THEN** the payload includes the rendered compact skill hints
- **AND** the payload exposes whether skill hints were enabled

### Requirement: MCP provides explicit skill expansion

The MCP server SHALL expose a read tool for expanding a hinted skill by id.

#### Scenario: Get full skill by id

- **GIVEN** a hinted skill id
- **WHEN** `get_skill(skill_id)` runs
- **THEN** the payload returns the full skill body
- **AND** it includes scope, origin project, source ids, portability notes, and disabled assumptions
