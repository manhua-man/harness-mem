from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suite.json"


def load_suite() -> dict:
    return json.loads(SUITE_PATH.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a benchmark run bundle.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Missing run_manifest.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_id = manifest["benchmark_id"]

    suite = load_suite()
    collection = None
    for item in suite["collections"]:
        if item["id"] == benchmark_id:
            collection = item
            break
    if collection is None:
        raise SystemExit(f"Unknown benchmark id in manifest: {benchmark_id}")

    missing = []
    for rel in collection["artifact_requirements"]:
        if not (run_dir / rel).exists():
            missing.append(rel)
    if missing:
        raise SystemExit(f"Missing required artifacts: {', '.join(missing)}")

    result_files = sorted((run_dir / "results").glob("*.json"))
    if not result_files:
        raise SystemExit("No result JSON files found under results/")

    required_fields = collection["required_result_fields"]
    checked = 0
    for path in result_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for field in required_fields:
            if field not in payload:
                raise SystemExit(f"{path.name}: missing field '{field}'")
        checked += 1

    print(f"OK: validated {checked} result files for {benchmark_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
