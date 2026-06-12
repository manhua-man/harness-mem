from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SNAPSHOT = ROOT / "release-snapshot.json"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise SystemExit(message)


def _require_non_negative_int(payload: dict[str, Any], field: str) -> int:
    value = payload.get(field)
    _require(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0,
        f"{field} must be a non-negative integer",
    )
    return value


def _validate_claim_gate(payload: dict[str, Any], key: str) -> None:
    gate = payload.get(key)
    _require(isinstance(gate, dict), f"claim_readiness.{key} must be an object")
    _require(isinstance(gate.get("ready"), bool), f"claim_readiness.{key}.ready must be boolean")
    _require(
        isinstance(gate.get("dimension"), str) and bool(gate["dimension"]),
        f"claim_readiness.{key}.dimension must be a non-empty string",
    )
    _require(
        isinstance(gate.get("source"), str) and bool(gate["source"]),
        f"claim_readiness.{key}.source must be a non-empty string",
    )
    blocking = gate.get("blocking")
    _require(
        isinstance(blocking, list) and all(isinstance(item, str) for item in blocking),
        f"claim_readiness.{key}.blocking must be a string array",
    )
    if gate["ready"]:
        _require(blocking == [], f"claim_readiness.{key}.blocking must be empty when ready=true")
    else:
        _require(blocking != [], f"claim_readiness.{key}.blocking must explain ready=false")


def validate_release_snapshot(path: Path) -> dict[str, Any]:
    _require(path.exists(), f"Missing release snapshot: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    _require(isinstance(payload, dict), "release snapshot must be a JSON object")

    version = payload.get("snapshot_version")
    _require(version == 2, "snapshot_version must be 2")
    _require(
        isinstance(payload.get("generated_at"), str) and bool(payload["generated_at"]),
        "generated_at must be a non-empty string",
    )
    _require(
        isinstance(payload.get("source"), str) and bool(payload["source"]),
        "source must be a non-empty string",
    )

    artifact_run_count = _require_non_negative_int(payload, "artifact_run_count")
    accepted_runs = _require_non_negative_int(payload, "accepted_runs")
    failed_runs = _require_non_negative_int(payload, "failed_runs")
    unknown_runs = _require_non_negative_int(payload, "unknown_runs")
    _require(isinstance(payload.get("gate_passed"), bool), "gate_passed must be boolean")

    runs = payload.get("runs")
    _require(isinstance(runs, list), "runs must be an array")
    _require(len(runs) == artifact_run_count, "artifact_run_count must match runs length")

    accepted = failed = unknown = 0
    for index, item in enumerate(runs):
        _require(isinstance(item, dict), f"runs[{index}] must be an object")
        for field in ["run_id", "collection_id", "claim_boundary"]:
            _require(
                isinstance(item.get(field), str) and bool(item[field]),
                f"runs[{index}].{field} must be a non-empty string",
            )
        accepted_value = item.get("accepted")
        if accepted_value is True:
            accepted += 1
        elif accepted_value is False:
            failed += 1
        elif accepted_value is None:
            unknown += 1
        else:
            raise SystemExit(f"runs[{index}].accepted must be boolean or null")

    _require(accepted == accepted_runs, "accepted_runs must match runs")
    _require(failed == failed_runs, "failed_runs must match runs")
    _require(unknown == unknown_runs, "unknown_runs must match runs")
    _require(
        payload["gate_passed"] == (failed == 0 and unknown == 0 and bool(runs)),
        "gate_passed must match accepted/failed/unknown counts",
    )

    readiness = payload.get("claim_readiness")
    _require(isinstance(readiness, dict), "claim_readiness must be an object")
    _validate_claim_gate(readiness, "token_cost_saving")
    _validate_claim_gate(readiness, "true_vector_hybrid_latency")
    _validate_claim_gate(readiness, "retrieval_recall")
    shootout = payload.get("retrieval_shootout")
    _require(isinstance(shootout, dict), "retrieval_shootout must be an object")
    _require(
        isinstance(shootout.get("default_embedding_baseline"), str)
        and bool(shootout["default_embedding_baseline"]),
        "retrieval_shootout.default_embedding_baseline must be a non-empty string",
    )
    _require(
        isinstance(shootout.get("embedding_candidates"), list)
        and all(isinstance(item, str) for item in shootout["embedding_candidates"]),
        "retrieval_shootout.embedding_candidates must be a string array",
    )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate benchmark release-snapshot.json.")
    parser.add_argument("--path", default=str(DEFAULT_SNAPSHOT))
    args = parser.parse_args()

    payload = validate_release_snapshot(Path(args.path))
    print(
        "OK: validated release snapshot "
        f"v{payload['snapshot_version']} with {payload['artifact_run_count']} runs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
