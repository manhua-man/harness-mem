## ADDED Requirements

### Requirement: doctor reports truth-store runtime state
The maintenance doctor surface SHALL report whether the runtime is operating in
`canonical`, `bootstrapped_from_legacy`, or `degraded_fallback` truth-store
mode, and SHALL provide an explicit recovery hint when the runtime is degraded.

#### Scenario: Doctor reports canonical runtime state
- **WHEN** `harness-mem doctor -p <project>` runs against a healthy canonical runtime
- **THEN** the output reports truth-store state `canonical`
- **AND** it does not instruct the user to migrate the project

#### Scenario: Doctor reports degraded fallback recovery path
- **GIVEN** canonical bootstrap failed and the runtime is degraded
- **WHEN** `harness-mem doctor -p <project>` runs
- **THEN** the output reports truth-store state `degraded_fallback`
- **AND** it includes a recovery command or rollback/export hint
