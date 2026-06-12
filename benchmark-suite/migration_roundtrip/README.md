# Migration Roundtrip

Benchmark id: `migration_roundtrip`

This v4.0.0 collection validates the reversible migration contract: dry-run
checksum, explicit side-by-side canonical SQLite apply, and rollback export to
v3-compatible JSON blobs.

```bash
python benchmark-suite/migration_roundtrip/driver.py --run-name migration-roundtrip-smoke
python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/migration-roundtrip-smoke
```
