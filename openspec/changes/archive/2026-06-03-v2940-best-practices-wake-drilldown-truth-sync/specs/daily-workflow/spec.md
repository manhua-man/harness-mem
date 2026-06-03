## MODIFIED Requirements

### Requirement: Wake-up guidance uses the MCP wake surface

#### Scenario: Best-practices docs treat wake as a first-class read tool

- **WHEN** maintainers update `docs/best-practices.md`
- **THEN** the runtime tool list includes `wake`
- **AND** the wake-up section names MCP `wake(project_name=<project>)` as the default read surface
- **AND** compact/generated wake options remain explicit opt-ins rather than implicit defaults
- **AND** low-level reads such as `get_task_handoffs` and `get_confirmed_rules` are only described as explicit drilldown surfaces rather than the default wake-up starting point
