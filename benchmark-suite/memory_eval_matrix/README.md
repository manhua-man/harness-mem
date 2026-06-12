# Memory Eval Matrix

v4.2 release-gate contract for memory-runtime behavior. One run must cover all
eight dimensions:

- cross_session_resume
- stale_truth_rejection
- raw_evidence_recovery
- candidate_noise_rejection
- task_aware_wake_precision
- multi_client_consistency
- wire_format_backward_compat
- context_sufficiency_accuracy

This pack proves surface availability and release-gate coverage. It does not
prove global answer quality, broad corpus quality, or token/cost savings.
