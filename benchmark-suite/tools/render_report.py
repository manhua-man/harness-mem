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
    if benchmark_id == "true_hybrid_retrieval_shootout":
        write_retrieval_shootout_summary_csv(run_dir, rows)
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
        "token_input",
        "token_cached_input",
        "token_output",
        "token_reasoning",
        "token_cost_usd",
        "token_source",
        "token_counter_available",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(_client_summary_row(row, fieldnames))


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


def write_retrieval_shootout_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "query_id",
        "query_type",
        "mode",
        "model_id",
        "expected_source_ids",
        "retrieved_source_ids",
        "recall_at_1",
        "recall_at_5",
        "recall_at_10",
        "p50_ms",
        "p95_ms",
        "index_load_ms",
        "fallback_reason",
        "token_cost_estimate",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key, "")) for key in fieldnames})


def build_report(rows: list[dict], benchmark_id: str) -> str:
    if benchmark_id == "latency_warm_path":
        return build_latency_report(rows)
    if benchmark_id == "true_hybrid_retrieval_shootout":
        return build_retrieval_shootout_report(rows)
    return build_client_report(rows)


def build_client_report(rows: list[dict]) -> str:
    lines = ["# Benchmark Report", "", "## Result Table", ""]
    lines.append(
        "| Task | Condition | Accepted | Runtime (s) | Turns | Tokens | Token Source | Notes |"
    )
    lines.append("|---|---|---|---:|---:|---|---|---|")
    for row in rows:
        token_usage = _token_usage(row)
        lines.append(
            "| {task_id} | {condition} | {accepted} | {runtime_seconds} | {prompt_turns} | {token_total} | {token_source} | {acceptance_notes} |".format(
                task_id=row.get("task_id", ""),
                condition=row.get("condition", ""),
                accepted=row.get("accepted", ""),
                runtime_seconds=row.get("runtime_seconds", ""),
                prompt_turns=row.get("prompt_turns", ""),
                token_total=_token_total_display(row),
                token_source=token_usage.get("source", ""),
                acceptance_notes=row.get("acceptance_notes", ""),
            )
        )

    conditions = {row.get("condition", "") for row in rows}
    if not {"enabled", "disabled"}.issubset(conditions):
        return "\n".join(lines) + "\n"

    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        grouped[row.get("task_id", "")][row.get("condition", "")] = row

    lines.extend(
        [
            "",
            "## Paired Delta Table",
            "",
            "| Task | Token Delta | Runtime Delta | Turn Delta | Outcome |",
            "|---|---:|---:|---:|---|",
        ]
    )
    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled and disabled:
            runtime_delta = _safe_num(disabled.get("runtime_seconds")) - _safe_num(enabled.get("runtime_seconds"))
            turn_delta = _safe_num(disabled.get("prompt_turns")) - _safe_num(enabled.get("prompt_turns"))
            token_delta = _token_delta(disabled, enabled)
            outcome = _pair_outcome(enabled.get("accepted"), disabled.get("accepted"))
            lines.append(
                f"| {task_id} | {token_delta} | {runtime_delta:.2f} | {int(turn_delta)} | {outcome} |"
            )
        else:
            lines.append(
                f"| {task_id} | unavailable | unavailable | unavailable | missing_pair |"
            )

    readiness = _token_claim_readiness(grouped)
    lines.extend(
        [
            "",
            "## Token Claim Readiness",
            "",
            f"- Token-saving claim ready: {readiness['ready']}",
            "- Rule: claim token/cost savings only when every claimed enabled/disabled pair has token totals from a named source and disabled - enabled is positive.",
            f"- Missing token totals: {readiness['missing']}",
            f"- Blocking token-saving rows: {readiness['blocking']}",
        ]
    )

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

    readiness = _vector_hybrid_claim_readiness(rows)
    lines.extend(
        [
            "",
            "## Vector Hybrid Claim Readiness",
            "",
            f"- True vector-hybrid claim ready: {readiness['ready']}",
            "- Rule: claim true vector-hybrid latency only when requested hybrid runs with `effective_mode=hybrid`, `accepted=yes`, and no `fallback_reason`.",
            f"- Blocking rows: {readiness['blocking']}",
            "",
            "## Notes",
            "",
            "- Latency results are synthetic warm-path measurements from an isolated benchmark data directory.",
            "- `search_hybrid` must be read with `effective_mode` and `fallback_reason`; FTS fallback is a valid environmental result.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_retrieval_shootout_report(rows: list[dict]) -> str:
    lines = ["# True Hybrid Retrieval Shootout Report", "", "## Result Table", ""]
    lines.append(
        "| Query | Type | Mode | Model | R@1 | R@5 | R@10 | p50 ms | p95 ms | Fallback | Accepted |"
    )
    lines.append("|---|---|---|---|---:|---:|---:|---:|---:|---|---|")
    for row in rows:
        lines.append(
            "| {query_id} | {query_type} | {mode} | {model_id} | {r1} | {r5} | {r10} | {p50} | {p95} | {fallback} | {accepted} |".format(
                query_id=row.get("query_id") or row.get("task_id", ""),
                query_type=row.get("query_type", ""),
                mode=row.get("mode") or row.get("retrieval_mode", ""),
                model_id=row.get("model_id", ""),
                r1=row.get("recall_at_1", ""),
                r5=row.get("recall_at_5", ""),
                r10=row.get("recall_at_10", ""),
                p50=row.get("p50_ms", ""),
                p95=row.get("p95_ms", ""),
                fallback=row.get("fallback_reason") or "",
                accepted=row.get("accepted", ""),
            )
        )

    readiness = _retrieval_recall_claim_readiness(rows)
    lines.extend(
        [
            "",
            "## Retrieval Recall Claim Readiness",
            "",
            f"- Retrieval recall claim ready: {readiness['ready']}",
            "- Rule: claim retrieval recall only when fts/vector/hybrid rows all carry expected source ids, R@5, accepted evidence, and fixture_only=false.",
            f"- Blocking rows: {readiness['blocking']}",
            "",
            "## Notes",
            "",
            "- Retrieval recall is source-hit recall, not end-to-end answer correctness.",
            "- The default embedding baseline remains all-MiniLM-L6-v2 until recall, latency, cache/disk, and install-friction gates all pass.",
        ]
    )
    return "\n".join(lines) + "\n"


def _safe_num(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _csv_cell(value):
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _client_summary_row(row: dict, fieldnames: list[str]) -> dict:
    usage = _token_usage(row)
    normalized = {key: row.get(key, "") for key in fieldnames}
    normalized["token_total"] = _token_total_display(row)
    normalized["token_input"] = usage.get("input")
    normalized["token_cached_input"] = usage.get("cached_input")
    normalized["token_output"] = usage.get("output")
    normalized["token_reasoning"] = usage.get("reasoning")
    normalized["token_cost_usd"] = usage.get("cost_usd")
    normalized["token_source"] = usage.get("source", "")
    normalized["token_counter_available"] = bool(usage.get("available"))
    return normalized


def _token_usage(row: dict) -> dict:
    usage = row.get("token_usage")
    if isinstance(usage, dict):
        return usage
    token_total = row.get("token_total")
    if _safe_token_num(token_total) is not None:
        return {
            "available": True,
            "source": "legacy-token_total",
            "total": token_total,
        }
    return {
        "available": False,
        "source": "unavailable",
        "total": None,
    }


def _safe_token_num(value) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _token_total_display(row: dict) -> str:
    usage = _token_usage(row)
    total = usage.get("total")
    if usage.get("available") and total is not None:
        return str(total)
    return "unavailable"


def _token_delta(disabled: dict, enabled: dict) -> str:
    disabled_total = _safe_token_num(_token_usage(disabled).get("total"))
    enabled_total = _safe_token_num(_token_usage(enabled).get("total"))
    if disabled_total is None or enabled_total is None:
        return "unavailable"
    delta = disabled_total - enabled_total
    return str(int(delta)) if delta.is_integer() else f"{delta:.2f}"


def _has_token_total(row: dict | None) -> bool:
    if row is None:
        return False
    return _safe_token_num(_token_usage(row).get("total")) is not None


def _token_claim_readiness(grouped: dict[str, dict[str, dict]]) -> dict[str, str]:
    missing: list[str] = []
    blocking: list[str] = []
    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled is None or disabled is None:
            missing.append(f"{task_id}/missing_pair")
            continue
        if not _has_token_total(enabled):
            missing.append(f"{task_id}/enabled")
        if not _has_token_total(disabled):
            missing.append(f"{task_id}/disabled")
        enabled_total = _safe_token_num(_token_usage(enabled).get("total"))
        disabled_total = _safe_token_num(_token_usage(disabled).get("total"))
        if enabled_total is not None and disabled_total is not None:
            delta = disabled_total - enabled_total
            if delta <= 0:
                blocking.append(f"{task_id}/token_delta_not_saving={int(delta)}")
    return {
        "ready": "yes" if not missing and not blocking and grouped else "no",
        "missing": ", ".join(missing) if missing else "none",
        "blocking": ", ".join(blocking) if blocking else "none",
    }


def _is_hybrid_claim_row(row: dict) -> bool:
    return row.get("requested_mode") == "hybrid" or row.get("task_id") == "search_hybrid"


def _vector_hybrid_claim_readiness(rows: list[dict]) -> dict[str, str]:
    hybrid_rows = [row for row in rows if _is_hybrid_claim_row(row)]
    if not hybrid_rows:
        return {
            "ready": "no",
            "blocking": "search_hybrid/missing",
        }

    blockers: list[str] = []
    for row in hybrid_rows:
        task_id = row.get("task_id") or "unknown"
        accepted = row.get("accepted")
        effective_mode = row.get("effective_mode") or "missing"
        fallback_reason = row.get("fallback_reason") or "none"

        if accepted != "yes":
            blockers.append(f"{task_id}/accepted={accepted or 'missing'}")
        if effective_mode != "hybrid" or fallback_reason != "none":
            blockers.append(
                f"{task_id}/effective_mode={effective_mode}/fallback_reason={fallback_reason}"
            )

    return {
        "ready": "no" if blockers else "yes",
        "blocking": ", ".join(blockers) if blockers else "none",
    }


def _retrieval_recall_claim_readiness(rows: list[dict]) -> dict[str, str]:
    required_modes = {"fts", "vector", "hybrid"}
    modes_seen: set[str] = set()
    blockers: list[str] = []
    for row in rows:
        query_id = row.get("query_id") or row.get("task_id") or "unknown"
        mode = row.get("mode") or row.get("retrieval_mode")
        if mode:
            modes_seen.add(str(mode))
        if row.get("accepted") != "yes":
            blockers.append(f"{query_id}/accepted={row.get('accepted') or 'missing'}")
        if row.get("fixture_only") is True:
            blockers.append(f"{query_id}/fixture_only")
        if row.get("recall_at_5") in {None, ""}:
            blockers.append(f"{query_id}/recall_at_5/missing")
        if not row.get("expected_source_ids"):
            blockers.append(f"{query_id}/expected_source_ids/missing")
    blockers.extend(
        f"mode/{mode}/missing"
        for mode in sorted(required_modes - modes_seen)
    )
    return {
        "ready": "no" if blockers else "yes",
        "blocking": ", ".join(blockers) if blockers else "none",
    }


def _pair_outcome(enabled, disabled) -> str:
    enabled_passed = enabled == "yes"
    disabled_passed = disabled == "yes"
    if enabled_passed and disabled_passed:
        return "both_passed"
    if enabled_passed:
        return "enabled_only_passed"
    if disabled_passed:
        return "disabled_only_passed"
    return "both_failed"


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
