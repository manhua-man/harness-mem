# Local Index Fabric Smoke

Benchmark id: `local_index_fabric_smoke`

This v4.0.0 collection establishes the artifact shape for manifest-last
generation sidecars. It is a smoke contract for later Local Memory Index Fabric
work, not the runtime index implementation itself.

```bash
python benchmark-suite/local_index_fabric_smoke/driver.py --run-name local-index-fabric-smoke
python benchmark-suite/tools/validate_run.py --run-dir benchmark-suite/artifacts/local-index-fabric-smoke
```
