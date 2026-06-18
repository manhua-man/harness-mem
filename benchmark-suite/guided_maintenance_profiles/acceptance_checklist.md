# Acceptance Checklist: `guided_maintenance_profiles`

- [ ] `benchmark_id` is `guided_maintenance_profiles`.
- [ ] `ProjectProfile.maintenance_profile` is set through the MCP profile update path.
- [ ] `get_project_status` returns `maintenance_profiles.active`, `suggested`, `available`, and `dry_runs`.
- [ ] Each dry-run summary includes `candidate_counts`, `risk_level`, `auto_applied`, `needs_human_review`, and `undo_available`.
- [ ] Dry-runs do not run `dream_run`, `metabolism_run`, a scheduler, or a host hook.
- [ ] Dry-runs do not write confirmed truth.
- [ ] Dry-runs do not write pending maintenance candidates.
- [ ] Dry-runs do not write retrieval signals.
- [ ] The report keeps the claim boundary: no production maintenance precision, answer-quality, token/cost, or daemon-readiness claim.
