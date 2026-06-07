# Acceptance Checklist: `runtime_health_observability`

Use this checklist before judging any RH1-RH6 result.

## Global Checks

- [ ] `benchmark_id` in the manifest is `runtime_health_observability`.
- [ ] `condition` is `health_guarded`.
- [ ] Product unlock conditions are satisfied.
- [ ] Transcript exists.
- [ ] Diagnosis evidence is local and source-backed.
- [ ] Cost discipline is tracked separately from observability.
- [ ] False success is counted as a failure.

## RH1: Runtime Health Report

Pass requires all of:

- [ ] Health report includes actionable status.
- [ ] Warnings are tied to concrete evidence.
- [ ] Healthy state does not hide missing optional dependencies.

Primary failure signals:

- Health report says OK while required surface is broken.

## RH2: Version Drift Visibility

Pass requires all of:

- [ ] Drift is detected or explicitly absent.
- [ ] Compared versions or schema ids are named.
- [ ] Next action is clear.

Primary failure signals:

- Version drift is collapsed into generic failure.

## RH3: Cost Budget Overrun

Pass requires all of:

- [ ] Token or output budget overrun is detected.
- [ ] Cost is reported as cost discipline, not observability.
- [ ] Truncation or high-output metadata is visible.

Primary failure signals:

- Over-budget output is reported as normal.

## RH4: Regression Gate

Pass requires all of:

- [ ] Benchmark result is compared to a pinned baseline.
- [ ] Pass/fail threshold is explicit.
- [ ] Regression cannot be hidden by aggregate-only reporting.

Primary failure signals:

- Gate passes without checking relevant dimension.

## RH5: Broken Transport Diagnosis

Pass requires all of:

- [ ] Broken transport is identified.
- [ ] User-facing guidance points to the correct maintenance surface.
- [ ] Forbidden obsolete daily CLI fallback is absent.

Primary failure signals:

- User is told to use removed daily workflow CLI commands.

## RH6: False Success Accounting

Pass requires all of:

- [ ] A deliberately broken state is not reported as success.
- [ ] False-success count is recorded.
- [ ] Report includes what evidence would prove recovery.

Primary failure signals:

- Recovery reports success without before/after evidence.
