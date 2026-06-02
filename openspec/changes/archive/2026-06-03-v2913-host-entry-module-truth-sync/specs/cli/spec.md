## ADDED Requirements

### Requirement: current docs use the concrete host-entry module path

Current-truth operator and roadmap docs SHALL describe host-triggered
invocation using the shipped `python -m harness_mem.host_entry` module path and
its flag-based interface, not placeholder package names or nonexistent
positional subcommands.

#### Scenario: docs keep the shipped host-entry invocation form

- **WHEN** maintainers update current operator or roadmap docs for IDE hooks or host triggers
- **THEN** those docs use `python -m harness_mem.host_entry`
- **AND** they do not use `python -m harness_mem.host`
- **AND** they do not use `harness_mem.<host_entry>` placeholders
- **AND** they do not describe `reflection_once` as a positional host-entry subcommand
