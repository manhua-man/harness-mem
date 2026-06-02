## ADDED Requirements

### Requirement: Wake-up guidance uses the MCP wake surface

User-facing `/hm:wake`, skill docs, and natural-language wake guidance SHALL
use the shipped MCP `wake` tool as the primary read surface rather than
teaching a manual assembly of low-level reads.

#### Scenario: Wake guidance calls MCP wake directly

- **WHEN** maintainers update `/hm:wake` command docs or repo-local skill guidance
- **THEN** they instruct the agent to call `wake(project_name=<project>)`
- **AND** optional generated summaries use `renderer="compact"`
- **AND** optional procedural hints use `include_skill_hints=true`
- **AND** they do not teach `get_project_profile` + `get_task_handoffs` + `get_confirmed_rules` + `timeline` as the default wake-up path
