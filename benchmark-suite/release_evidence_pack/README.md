# Release Evidence Pack

v4.5 release-gate collection for clean-checkout evidence packaging.

This pack verifies that the tracked release snapshot, packaged benchmark
resources, and claim-promotion policy stay synchronized for runtime/package
consumers. It does not upgrade blocked claims into public claims.

## Boundaries

- Raw artifacts remain the richest evidence source.
- Clean checkouts may use packaged `suite.json` and `release-snapshot.json`.
- Package sync proves evidence availability, not performance, billing savings,
  or answer correctness.

