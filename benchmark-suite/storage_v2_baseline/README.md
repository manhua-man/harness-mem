# Storage v2 Baseline

Benchmark id: `storage_v2_baseline`

This v4.0.0 collection fixes the synthetic corpus contract used before Storage
v2 changes any default runtime path. It measures deterministic legacy JSON scan
cost and emits the artifact fields future 10k / 100k / 1M runs must keep.

The smoke driver is diagnostic only. Public performance claims require larger
artifact-backed runs and must stay out of README/release notes until the claim
gate is ready.

```bash
python benchmark-suite/storage_v2_baseline/driver.py --run-name storage-v2-baseline-smoke
python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/storage-v2-baseline-smoke
```
