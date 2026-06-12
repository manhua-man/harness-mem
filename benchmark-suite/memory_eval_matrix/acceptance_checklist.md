# Acceptance Checklist

- [ ] Every result row has `benchmark_id=memory_eval_matrix`.
- [ ] All eight `dimension` values are present exactly once or more.
- [ ] Accepted rows include `expected_source_ids`, `retrieved_source_ids`, `safe_to_answer`, `false_positive_count`, `artifact_state`, and `claim_boundary`.
- [ ] `accepted=yes` rows use `artifact_state=accepted`.
- [ ] The report states that this is a release gate, not an end-to-end answer-quality claim.
