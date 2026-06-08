from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SUITE_PATH = ROOT / "suite.json"


def load_suite(path: Path = SUITE_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _is_number(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and value >= 0


def validate_token_usage(path: Path, payload: dict) -> None:
    usage = payload.get("token_usage")
    if not isinstance(usage, dict):
        raise SystemExit(f"{path.name}: token_usage must be an object")

    required = [
        "available",
        "source",
        "total",
        "input",
        "cached_input",
        "output",
        "reasoning",
        "cost_usd",
        "notes",
    ]
    for field in required:
        if field not in usage:
            raise SystemExit(f"{path.name}: token_usage missing field '{field}'")

    if not isinstance(usage["available"], bool):
        raise SystemExit(f"{path.name}: token_usage.available must be boolean")
    if not isinstance(usage["source"], str) or not usage["source"]:
        raise SystemExit(f"{path.name}: token_usage.source must be a non-empty string")
    if not isinstance(usage["notes"], list) or not all(
        isinstance(item, str) for item in usage["notes"]
    ):
        raise SystemExit(f"{path.name}: token_usage.notes must be a string array")

    numeric_fields = ["total", "input", "cached_input", "output", "reasoning", "cost_usd"]
    for field in numeric_fields:
        value = usage[field]
        if value is not None and not _is_number(value):
            raise SystemExit(f"{path.name}: token_usage.{field} must be a non-negative number or null")

    has_number = any(usage[field] is not None for field in numeric_fields)
    if usage["available"]:
        if usage["source"] == "unavailable":
            raise SystemExit(f"{path.name}: available token_usage cannot use source='unavailable'")
        if not has_number:
            raise SystemExit(f"{path.name}: available token_usage requires at least one numeric field")
    else:
        if usage["total"] is not None:
            raise SystemExit(f"{path.name}: unavailable token_usage must keep total=null")
        if payload.get("token_total") != "unavailable":
            raise SystemExit(f"{path.name}: unavailable token_usage requires token_total='unavailable'")


def validate_run(run_dir: Path, suite_path: Path = SUITE_PATH) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        raise SystemExit("Missing run_manifest.json")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    benchmark_id = manifest["benchmark_id"]

    suite = load_suite(suite_path)
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
    requires_token_usage = False
    if (
        benchmark_id == "client_enabled_vs_disabled"
        and int(manifest.get("result_schema_version", 1)) >= 2
    ):
        required_fields = [*required_fields, "token_usage"]
        requires_token_usage = True
    checked = 0
    for path in result_files:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for field in required_fields:
            if field not in payload:
                raise SystemExit(f"{path.name}: missing field '{field}'")
        if requires_token_usage:
            validate_token_usage(path, payload)
        checked += 1

    return {
        "benchmark_id": benchmark_id,
        "result_count": checked,
        "run_dir": str(run_dir),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a benchmark run bundle.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    result = validate_run(Path(args.run_dir))
    print(f"OK: validated {result['result_count']} result files for {result['benchmark_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
