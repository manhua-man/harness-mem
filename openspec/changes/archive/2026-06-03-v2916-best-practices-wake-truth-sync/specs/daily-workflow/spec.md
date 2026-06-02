## ADDED Requirements

### Requirement: Best-practices docs treat wake as a first-class read tool

The best-practices guide SHALL list `wake` as a first-class read tool and
SHALL describe `wake(project_name=<project>)` as the default wake-up surface.

#### Scenario: best-practices wake guidance matches the shipped surface

- **WHEN** maintainers update `docs/best-practices.md`
- **THEN** the runtime tool list includes `wake`
- **AND** the wake-up section names MCP `wake(project_name=<project>)` as the default read surface
- **AND** compact/generated wake and skill hints remain explicit opt-ins
