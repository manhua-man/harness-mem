from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped or stripped.lower() == "unavailable":
            return None
        try:
            parsed = float(stripped)
        except ValueError:
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _pick_number(payload: dict[str, Any], *keys: str) -> int | float | None:
    for key in keys:
        value = _number(payload.get(key))
        if value is not None:
            return value
    return None


def normalize_token_usage(payload: dict[str, Any], source: str) -> dict[str, Any]:
    total = _pick_number(payload, "total", "total_tokens", "token_total", "tokens")
    input_tokens = _pick_number(payload, "input", "input_tokens", "prompt_tokens")
    cached_input = _pick_number(
        payload,
        "cached_input",
        "cached_input_tokens",
        "cached_tokens",
        "prompt_cached_tokens",
    )
    output_tokens = _pick_number(
        payload,
        "output",
        "output_tokens",
        "completion_tokens",
    )
    reasoning_tokens = _pick_number(
        payload,
        "reasoning",
        "reasoning_tokens",
        "reasoning_output_tokens",
        "completion_reasoning_tokens",
    )
    cost_usd = _pick_number(payload, "cost_usd", "usd", "cost")
    if total is None and input_tokens is not None and output_tokens is not None:
        total = input_tokens + output_tokens

    available = any(
        value is not None
        for value in [total, input_tokens, cached_input, output_tokens, reasoning_tokens, cost_usd]
    )
    notes = payload.get("notes", [])
    if isinstance(notes, str):
        notes = [notes]
    if not isinstance(notes, list):
        notes = []

    if not available:
        return {
            "available": False,
            "source": "unavailable",
            "total": None,
            "input": None,
            "cached_input": None,
            "output": None,
            "reasoning": None,
            "cost_usd": None,
            "notes": [f"No token numbers were present in {source} sidecar."],
        }

    return {
        "available": True,
        "source": str(payload.get("source") or source),
        "total": total,
        "input": input_tokens,
        "cached_input": cached_input,
        "output": output_tokens,
        "reasoning": reasoning_tokens,
        "cost_usd": cost_usd,
        "notes": [str(item) for item in notes],
    }


def token_total_for_result(token_usage: dict[str, Any]) -> int | float | str:
    total = token_usage.get("total")
    return total if token_usage.get("available") and total is not None else "unavailable"


def sidecar_candidates(sidecar_dir: Path, task_id: str, condition: str) -> list[Path]:
    return [
        sidecar_dir / f"{task_id}-{condition}-token-usage.json",
        sidecar_dir / f"{task_id}-{condition}.json",
        sidecar_dir / f"{task_id}.{condition}.json",
    ]


def load_sidecar(sidecar_dir: Path, task_id: str, condition: str) -> tuple[Path, dict[str, Any]] | None:
    for path in sidecar_candidates(sidecar_dir, task_id, condition):
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise SystemExit(f"{path}: token sidecar must be a JSON object")
            return path, normalize_token_usage(payload, "sidecar")
    return None


def apply_token_usage(result: dict[str, Any], token_usage: dict[str, Any]) -> dict[str, Any]:
    updated = dict(result)
    updated["token_total"] = token_total_for_result(token_usage)
    updated["token_input"] = token_usage.get("input")
    updated["token_cached_input"] = token_usage.get("cached_input")
    updated["token_output"] = token_usage.get("output")
    updated["token_reasoning"] = token_usage.get("reasoning")
    updated["token_cost_usd"] = token_usage.get("cost_usd")
    updated["token_source"] = token_usage.get("source")
    updated["token_counter_available"] = bool(token_usage.get("available"))
    updated["token_usage"] = token_usage
    return updated


def apply_sidecars(run_dir: Path, sidecar_dir: Path, allow_missing: bool = False, dry_run: bool = False) -> dict[str, Any]:
    results_dir = run_dir / "results"
    result_paths = sorted(results_dir.glob("*.json"))
    if not result_paths:
        raise SystemExit(f"{results_dir}: no result JSON files found")

    applied: list[str] = []
    missing: list[str] = []
    for result_path in result_paths:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        task_id = result.get("task_id")
        condition = result.get("condition")
        if not isinstance(task_id, str) or not isinstance(condition, str):
            raise SystemExit(f"{result_path.name}: missing task_id or condition")

        sidecar = load_sidecar(sidecar_dir, task_id, condition)
        if sidecar is None:
            missing.append(f"{task_id}/{condition}")
            continue
        sidecar_path, token_usage = sidecar
        updated = apply_token_usage(result, token_usage)
        if not dry_run:
            result_path.write_text(
                json.dumps(updated, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        applied.append(f"{result_path.name} <= {sidecar_path.name}")

    if missing and not allow_missing:
        raise SystemExit("Missing token sidecars for: " + ", ".join(missing))

    manifest_path = run_dir / "run_manifest.json"
    manifest_updated = False
    if not missing and manifest_path.exists() and not dry_run:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        current_version = int(manifest.get("result_schema_version", 1))
        if current_version < 2:
            manifest["result_schema_version"] = 2
            manifest_path.write_text(
                json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            manifest_updated = True

    return {
        "applied": applied,
        "missing": missing,
        "manifest_schema_updated": manifest_updated,
        "dry_run": dry_run,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply BENCH-001 token usage sidecars to result JSON files."
    )
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--sidecar-dir", type=Path)
    parser.add_argument("--allow-missing", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sidecar_dir = args.sidecar_dir or (args.run_dir / "notes")
    summary = apply_sidecars(
        args.run_dir,
        sidecar_dir,
        allow_missing=args.allow_missing,
        dry_run=args.dry_run,
    )
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
