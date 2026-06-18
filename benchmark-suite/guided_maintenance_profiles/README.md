# Guided Maintenance Profiles

Deterministic v5.8 loop gate for guided opt-in maintenance profiles.

This collection is backed by `tests/loop_harness/test_guided_maintenance_profiles.py`.
It checks the profile/status loop, not live maintenance quality.

## Loop

```text
update_project_profile(maintenance_profile)
  -> ProjectProfile stores the opt-in preset
  -> get_project_status returns active/suggested/available profiles
  -> dry_run summaries expose risk and candidate counts
  -> no truth, candidate, or signal records are implicitly written
```

## Claim Boundary

This proves profile dry-runs are explainable and non-mutating. It does not prove
production-long-run maintenance precision, automatic scheduler safety, answer
quality improvement, token/cost saving, or background daemon readiness.

## Run

```powershell
python -m pytest tests/loop_harness/test_guided_maintenance_profiles.py -q --capture=no
```
