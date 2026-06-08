from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parent
TOOLS_ROOT = Path(__file__).resolve().parent

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOLS_ROOT))

from build_release_snapshot import build_release_snapshot  # noqa: E402
from validate_release_snapshot import validate_release_snapshot  # noqa: E402
from validate_run import validate_run  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _check_packaged_resources(suite_root: Path) -> None:
    package_root = suite_root.parent / "harness_mem" / "resources" / "benchmark_suite"
    if not package_root.exists():
        return

    for name in ["suite.json", "release-snapshot.json"]:
        source = suite_root / name
        packaged = package_root / name
        if not packaged.exists():
            raise SystemExit(f"Missing packaged benchmark resource: {packaged}")
        if _load_json(source) != _load_json(packaged):
            raise SystemExit(
                f"{packaged}: packaged benchmark resource is stale; sync from {source}"
            )


def check_release_artifacts(suite_root: Path = ROOT) -> dict[str, Any]:
    suite_root = Path(suite_root)
    snapshot_path = suite_root / "release-snapshot.json"
    if not snapshot_path.exists():
        raise SystemExit(f"Missing release snapshot: {snapshot_path}")

    current_snapshot = _load_json(snapshot_path)
    artifact_root = suite_root / "artifacts"
    artifact_dirs = (
        sorted(
            path
            for path in artifact_root.iterdir()
            if path.is_dir() and (path / "run_manifest.json").exists()
        )
        if artifact_root.exists()
        else []
    )
    if not artifact_dirs:
        validate_release_snapshot(snapshot_path)
        _check_packaged_resources(suite_root)
        return {
            "artifact_run_count": 0,
            "result_file_count": 0,
            "snapshot_run_count": current_snapshot["artifact_run_count"],
            "snapshot_version": current_snapshot["snapshot_version"],
            "mode": "snapshot-only",
        }

    rebuilt_snapshot = build_release_snapshot(
        suite_root,
        generated_at=current_snapshot.get("generated_at"),
    )
    if rebuilt_snapshot != current_snapshot:
        raise SystemExit(
            f"{snapshot_path}: stale release snapshot; run "
            "python benchmark-suite/tools/build_release_snapshot.py "
            "--output benchmark-suite/release-snapshot.json"
        )

    validate_release_snapshot(snapshot_path)
    _check_packaged_resources(suite_root)

    run_results = [validate_run(path, suite_root / "suite.json") for path in artifact_dirs]
    return {
        "artifact_run_count": len(run_results),
        "result_file_count": sum(item["result_count"] for item in run_results),
        "snapshot_run_count": current_snapshot["artifact_run_count"],
        "snapshot_version": current_snapshot["snapshot_version"],
        "mode": "artifacts",
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check benchmark artifact bundles and tracked release snapshot."
    )
    parser.add_argument("--suite-root", default=str(ROOT))
    args = parser.parse_args()

    result = check_release_artifacts(Path(args.suite_root))
    print(
        "OK: checked "
        f"{result['artifact_run_count']} benchmark runs, "
        f"{result['result_file_count']} result files, "
        f"release snapshot v{result['snapshot_version']} "
        f"({result['mode']}, snapshot runs={result['snapshot_run_count']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
