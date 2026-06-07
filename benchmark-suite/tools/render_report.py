from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


def load_results(results_dir: Path) -> list[dict]:
    payloads = []
    for path in sorted(results_dir.glob("*.json")):
        payloads.append(json.loads(path.read_text(encoding="utf-8")))
    return payloads


def load_manifest(run_dir: Path) -> dict:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.exists():
        return {}
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def write_summary_csv(run_dir: Path, rows: list[dict], benchmark_id: str) -> None:
    if benchmark_id == "latency_warm_path":
        write_latency_summary_csv(run_dir, rows)
        return
    write_client_summary_csv(run_dir, rows)


def write_client_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "task_id",
        "condition",
        "client",
        "model",
        "workspace_path",
        "runtime_seconds",
        "prompt_turns",
        "followup_count",
        "token_total",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def write_latency_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "task_id",
        "condition",
        "operation",
        "runtime_seconds",
        "sample_count",
        "warmup_count",
        "p50_ms",
        "p95_ms",
        "p99_ms",
        "max_ms",
        "min_ms",
        "mean_ms",
        "error_count",
        "accepted",
        "acceptance_notes",
        "requested_mode",
        "effective_mode",
        "fallback_reason",
        "result_count_last_sample",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_report(rows: list[dict], benchmark_id: str) -> str:
    if benchmark_id == "latency_warm_path":
        return build_latency_report(rows)
    return build_client_report(rows)


def build_client_report(rows: list[dict]) -> str:
    lines = ["# Benchmark Report", "", "## Result Table", ""]
    lines.append("| Task | Condition | Accepted | Runtime (s) | Turns | Tokens | Notes |")
    lines.append("|---|---|---|---:|---:|---|---|")
    for row in rows:
        lines.append(
            "| {task_id} | {condition} | {accepted} | {runtime_seconds} | {prompt_turns} | {token_total} | {acceptance_notes} |".format(
                task_id=row.get("task_id", ""),
                condition=row.get("condition", ""),
                accepted=row.get("accepted", ""),
                runtime_seconds=row.get("runtime_seconds", ""),
                prompt_turns=row.get("prompt_turns", ""),
                token_total=row.get("token_total", ""),
                acceptance_notes=row.get("acceptance_notes", ""),
            )
        )

    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        grouped[row.get("task_id", "")][row.get("condition", "")] = row

    lines.extend(["", "## Paired Delta Table", "", "| Task | Token Delta | Runtime Delta | Turn Delta | Outcome |", "|---|---:|---:|---:|---|"])
    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled and disabled:
            runtime_delta = _safe_num(disabled.get("runtime_seconds")) - _safe_num(enabled.get("runtime_seconds"))
            turn_delta = _safe_num(disabled.get("prompt_turns")) - _safe_num(enabled.get("prompt_turns"))
            token_delta = _token_delta(disabled.get("token_total"), enabled.get("token_total"))
            outcome = f"enabled={enabled.get('accepted')} / disabled={disabled.get('accepted')}"
            lines.append(
                f"| {task_id} | {token_delta} | {runtime_delta:.2f} | {int(turn_delta)} | {outcome} |"
            )
        else:
            lines.append(f"| {task_id} | unavailable | unavailable | unavailable | missing pair |")

    return "\n".join(lines) + "\n"


def build_latency_report(rows: list[dict]) -> str:
    lines = ["# Warm Path Latency Report", "", "## Result Table", ""]
    lines.append(
        "| Task | Accepted | Samples | p50 ms | p95 ms | p99 ms | max ms | Effective Mode | Fallback |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---|---|")
    for row in rows:
        lines.append(
            "| {task_id} | {accepted} | {sample_count} | {p50_ms} | {p95_ms} | {p99_ms} | {max_ms} | {effective_mode} | {fallback_reason} |".format(
                task_id=row.get("task_id", ""),
                accepted=row.get("accepted", ""),
                sample_count=row.get("sample_count", ""),
                p50_ms=row.get("p50_ms", ""),
                p95_ms=row.get("p95_ms", ""),
                p99_ms=row.get("p99_ms", ""),
                max_ms=row.get("max_ms", ""),
                effective_mode=row.get("effective_mode", ""),
                fallback_reason=row.get("fallback_reason") or "",
            )
        )
    lines.extend(
        [
            "",
            "## Notes",
            "",
            "- Latency results are synthetic warm-path measurements from an isolated benchmark data directory.",
            "- `search_hybrid` must be read with `effective_mode` and `fallback_reason`; FTS fallback is a valid environmental result.",
        ]
    )
    return "\n".join(lines) + "\n"


def _safe_num(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _token_delta(disabled, enabled) -> str:
    try:
        return str(float(disabled) - float(enabled))
    except Exception:
        return "unavailable"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render benchmark summary files.")
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()

    run_dir = Path(args.run_dir)
    manifest = load_manifest(run_dir)
    benchmark_id = manifest.get("benchmark_id", "")
    rows = load_results(run_dir / "results")
    write_summary_csv(run_dir, rows, benchmark_id)
    (run_dir / "report.md").write_text(build_report(rows, benchmark_id), encoding="utf-8")
    print(f"Rendered {run_dir / 'summary.csv'} and {run_dir / 'report.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
