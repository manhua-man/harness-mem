from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from harness_mem.commands import token_estimator  # noqa: E402

SUITE_DIR = ROOT / "benchmark-suite"
BENCHMARK_ID = "functional_token_economics"
SCENARIOS_PATH = SUITE_DIR / BENCHMARK_ID / "scenarios.json"
ARTIFACTS = SUITE_DIR / "artifacts"


def load_scenarios() -> dict[str, Any]:
    return json.loads(SCENARIOS_PATH.read_text(encoding="utf-8"))


def make_run_dir(run_name: str) -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d")
    run_dir = ARTIFACTS / f"{stamp}-{BENCHMARK_ID}-{run_name}"
    run_dir.mkdir(parents=True, exist_ok=False)
    (run_dir / "results").mkdir()
    (run_dir / "notes").mkdir()
    return run_dir


def build_manifest(args: argparse.Namespace, run_dir: Path, scenario_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "benchmark_id": BENCHMARK_ID,
        "run_name": args.run_name,
        "artifact_state": "accepted" if args.release_snapshot else "diagnostic",
        "accepted": True if args.release_snapshot else None,
        "release_snapshot": bool(args.release_snapshot),
        "result_schema_version": 1,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "workspace_path": str(args.workspace),
        "scenario_version": scenario_pack.get("version"),
        "claim_boundary": scenario_pack.get("claim_boundary"),
        "operator_notes": [
            "Functional token-economics fixture run.",
            "Measures payload token counts only; does not prove global product savings or real billing.",
            f"Run directory: {run_dir}",
        ],
    }


def _load_payload(workspace: Path, source: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    kind = source.get("kind")
    if kind == "text":
        text = str(source.get("text") or "")
        return text, {
            "kind": "text",
            "label": source.get("label") or "inline",
            "chars": len(text),
        }
    if kind == "file":
        rel_path = Path(str(source.get("path") or ""))
        path = (workspace / rel_path).resolve()
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(f"Missing benchmark source file: {rel_path}")
        text = path.read_text(encoding="utf-8", errors="replace")
        return text, {
            "kind": "file",
            "path": rel_path.as_posix(),
            "chars": len(text),
        }
    raise ValueError(f"Unsupported source kind: {kind!r}")


def _payload_bundle(workspace: Path, sources: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
    texts: list[str] = []
    summaries: list[dict[str, Any]] = []
    for source in sources:
        text, summary = _load_payload(workspace, source)
        texts.append(text)
        summaries.append(summary)
    return "\n\n".join(texts), summaries


def build_result(workspace: Path, scenario: dict[str, Any]) -> dict[str, Any]:
    baseline_text, baseline_sources = _payload_bundle(workspace, scenario["baseline_sources"])
    optimized_text, optimized_sources = _payload_bundle(workspace, scenario["optimized_sources"])
    baseline_tokens = token_estimator.count_tokens(baseline_text)
    optimized_tokens = token_estimator.count_tokens(optimized_text)
    token_delta = baseline_tokens - optimized_tokens
    saving_ratio = token_delta / baseline_tokens if baseline_tokens > 0 else 0.0
    minimum_ratio = float(scenario.get("minimum_saving_ratio") or 0.0)
    accepted = baseline_tokens > 0 and optimized_tokens > 0 and saving_ratio >= minimum_ratio
    return {
        "scenario_id": scenario["scenario_id"],
        "workflow": scenario["workflow"],
        "title": scenario["title"],
        "baseline_label": scenario["baseline_label"],
        "optimized_label": scenario["optimized_label"],
        "baseline_tokens": baseline_tokens,
        "optimized_tokens": optimized_tokens,
        "token_delta": token_delta,
        "saving_ratio": round(saving_ratio, 4),
        "minimum_saving_ratio": minimum_ratio,
        "baseline_source_count": len(baseline_sources),
        "optimized_source_count": len(optimized_sources),
        "baseline_sources": baseline_sources,
        "optimized_sources": optimized_sources,
        "tokenizer": token_estimator.tokenizer_kind,
        "token_source": "harness_mem.commands.token_estimator",
        "fixture_only": True,
        "claim_scope": scenario["claim_scope"],
        "accepted": "yes" if accepted else "no",
        "acceptance_notes": (
            f"saving_ratio={saving_ratio:.3f} >= minimum={minimum_ratio:.3f}; "
            "fixture payload only, not global savings"
            if accepted
            else f"saving_ratio={saving_ratio:.3f} below minimum={minimum_ratio:.3f}"
        ),
    }


def write_summary_csv(run_dir: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    path = run_dir / "summary.csv"
    fieldnames = [
        "scenario_id",
        "workflow",
        "baseline_tokens",
        "optimized_tokens",
        "token_delta",
        "saving_ratio",
        "minimum_saving_ratio",
        "tokenizer",
        "fixture_only",
        "claim_scope",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def build_report(rows: list[dict[str, Any]]) -> str:
    lines = ["# Functional Token Economics Report", "", "## Result Table", ""]
    lines.append(
        "| Scenario | Workflow | Baseline Tokens | Optimized Tokens | Delta | Saving Ratio | Accepted |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        lines.append(
            "| {scenario_id} | {workflow} | {baseline_tokens} | {optimized_tokens} | {token_delta} | {saving_ratio:.3f} | {accepted} |".format(
                scenario_id=row["scenario_id"],
                workflow=row["workflow"],
                baseline_tokens=row["baseline_tokens"],
                optimized_tokens=row["optimized_tokens"],
                token_delta=row["token_delta"],
                saving_ratio=float(row["saving_ratio"]),
                accepted=row["accepted"],
            )
        )

    blockers = [
        f"{row['scenario_id']}/saving_ratio={float(row['saving_ratio']):.3f}<minimum={float(row['minimum_saving_ratio']):.3f}"
        for row in rows
        if row.get("accepted") != "yes"
    ]
    ready = "yes" if rows and not blockers else "no"
    ratios = [float(row["saving_ratio"]) for row in rows]
    min_ratio = min(ratios) if ratios else 0.0
    median_ratio = sorted(ratios)[len(ratios) // 2] if ratios else 0.0
    if len(ratios) and len(ratios) % 2 == 0:
        ordered = sorted(ratios)
        median_ratio = (ordered[(len(ordered) // 2) - 1] + ordered[len(ordered) // 2]) / 2

    lines.extend(
        [
            "",
            "## Feature-Level Claim Readiness",
            "",
            f"- Functional fixture token-economics ready: {ready}",
            f"- Scenario count: {len(rows)}",
            f"- Minimum saving ratio: {min_ratio:.3f}",
            f"- Median saving ratio: {median_ratio:.3f}",
            f"- Blocking rows: {', '.join(blockers) if blockers else 'none'}",
            "",
            "## Global Claim Boundary",
            "",
            "- Global token/cost saving ready: no",
            "- Rule: this collection measures fixture payload economics only. It does not prove real billing, live-agent behavior, or whole-product savings.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run functional token-economics benchmark.")
    parser.add_argument("--run-name", default="local-01")
    parser.add_argument("--workspace", type=Path, default=ROOT)
    parser.add_argument(
        "--release-snapshot",
        action="store_true",
        help="Opt this fixture run into release-snapshot consideration after review.",
    )
    args = parser.parse_args()
    args.workspace = args.workspace.resolve()

    scenario_pack = load_scenarios()
    run_dir = make_run_dir(args.run_name)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(build_manifest(args, run_dir, scenario_pack), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    shutil.copyfile(SCENARIOS_PATH, run_dir / "notes" / "scenarios.json")

    rows = []
    for scenario in scenario_pack["scenarios"]:
        result = build_result(args.workspace, scenario)
        rows.append(result)
        (run_dir / "results" / f"{scenario['scenario_id']}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

    write_summary_csv(run_dir, rows)
    (run_dir / "report.md").write_text(build_report(rows), encoding="utf-8")
    print(run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
