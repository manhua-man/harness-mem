from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path


STORAGE_V2_BENCHMARKS = {
    "storage_v2_baseline",
    "migration_roundtrip",
    "local_index_fabric_smoke",
    "canonical_store_runtime_baseline",
    "rust_core_hot_path",
    "index_fabric_runtime_conformance",
    "context_sufficiency_gate",
    "task_aware_wake_precision",
}


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
    if benchmark_id == "memory_shortcut_vs_source_recovery":
        write_memory_shortcut_summary_csv(run_dir, rows)
        return
    if benchmark_id == "functional_token_economics":
        write_functional_token_economics_summary_csv(run_dir, rows)
        return
    if benchmark_id in STORAGE_V2_BENCHMARKS:
        write_storage_v2_summary_csv(run_dir, rows)
        return
    if benchmark_id in {
        "memory_eval_matrix",
        "retrieval_quality_pack",
        "code_memory_federation",
        "claim_promotion_pack",
        "release_evidence_pack",
    }:
        write_v42_v45_summary_csv(run_dir, rows, benchmark_id)
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


def write_memory_shortcut_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "task_id",
        "task_type",
        "condition",
        "client",
        "model",
        "workspace_path",
        "runtime_seconds",
        "prompt_turns",
        "followup_count",
        "token_total",
        "token_cache_adjusted_proxy",
        "token_input",
        "token_cached_input",
        "token_output",
        "token_reasoning",
        "token_source",
        "token_counter_available",
        "source_read_count",
        "repo_call_count",
        "budget_violation",
        "cited_sources",
        "memory_calls",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            usage = _token_usage(row)
            writer.writerow(
                {
                    **{key: row.get(key, "") for key in fieldnames},
                    "token_total": _token_total_display(row),
                    "token_cache_adjusted_proxy": _token_proxy_display(row),
                    "token_input": usage.get("input"),
                    "token_cached_input": usage.get("cached_input"),
                    "token_output": usage.get("output"),
                    "token_reasoning": usage.get("reasoning"),
                    "token_source": usage.get("source", ""),
                    "token_counter_available": bool(usage.get("available")),
                    "repo_call_count": _repo_call_count(row),
                    "budget_violation": _memory_shortcut_budget_violation(row),
                    "cited_sources": _csv_cell(row.get("cited_sources", [])),
                    "memory_calls": _csv_cell(row.get("memory_calls", [])),
                }
            )


def write_functional_token_economics_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "scenario_id",
        "workflow",
        "baseline_label",
        "optimized_label",
        "baseline_tokens",
        "optimized_tokens",
        "token_delta",
        "saving_ratio",
        "minimum_saving_ratio",
        "tokenizer",
        "token_source",
        "fixture_only",
        "claim_scope",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_cell(row.get(key, "")) for key in fieldnames})


def write_storage_v2_summary_csv(run_dir: Path, rows: list[dict]) -> None:
    path = run_dir / "summary.csv"
    fieldnames = [
        "benchmark_id",
        "operation",
        "dataset_id",
        "entry_count",
        "json_file_count",
        "p50_ms",
        "p95_ms",
        "rss_peak_mb",
        "disk_bytes",
        "db_size_bytes",
        "sidecar_size_bytes",
        "fallback_reason",
        "claim_ready",
        "accepted",
        "acceptance_notes",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            readiness = row.get("claim_readiness") if isinstance(row.get("claim_readiness"), dict) else {}
            writer.writerow(
                {
                    **{key: _csv_cell(row.get(key, "")) for key in fieldnames},
                    "claim_ready": readiness.get("ready", ""),
                }
            )


def write_v42_v45_summary_csv(run_dir: Path, rows: list[dict], benchmark_id: str) -> None:
    path = run_dir / "summary.csv"
    if benchmark_id == "memory_eval_matrix":
        fieldnames = [
            "dimension",
            "task_id",
            "safe_to_answer",
            "false_positive_count",
            "artifact_state",
            "accepted",
            "claim_boundary",
        ]
    elif benchmark_id == "retrieval_quality_pack":
        fieldnames = [
            "capability",
            "task_id",
            "default_enabled",
            "precision_at_k",
            "recall_delta",
            "false_positive_delta",
            "fanout_cost",
            "duplicate_rate",
            "sufficiency_delta",
            "accepted",
            "acceptance_notes",
        ]
    elif benchmark_id == "code_memory_federation":
        fieldnames = [
            "task_id",
            "file_path",
            "source_id",
            "stale_status",
            "generated_layer_is_truth",
            "accepted",
            "claim_boundary",
        ]
    elif benchmark_id == "claim_promotion_pack":
        fieldnames = [
            "claim_id",
            "status",
            "ready",
            "source_gate",
            "claim_type",
            "accepted",
            "claim_boundary",
        ]
    else:
        fieldnames = [
            "pack_id",
            "snapshot_run_count",
            "accepted_runs",
            "failed_runs",
            "unknown_runs",
            "blocked_claim_count",
            "bounded_claim_count",
            "packaged_suite_match",
            "packaged_snapshot_match",
            "claim_promotion_policy_enforced",
            "gate_passed",
            "accepted",
        ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            stale_check = row.get("stale_check") if isinstance(row.get("stale_check"), dict) else {}
            writer.writerow(
                {
                    **{key: _csv_cell(row.get(key, "")) for key in fieldnames},
                    "stale_status": stale_check.get("status", ""),
                }
            )


def build_report(rows: list[dict], benchmark_id: str) -> str:
    if benchmark_id == "latency_warm_path":
        return build_latency_report(rows)
    if benchmark_id == "true_hybrid_retrieval_shootout":
        return build_retrieval_shootout_report(rows)
    if benchmark_id == "memory_shortcut_vs_source_recovery":
        return build_memory_shortcut_report(rows)
    if benchmark_id == "functional_token_economics":
        return build_functional_token_economics_report(rows)
    if benchmark_id in STORAGE_V2_BENCHMARKS:
        return build_storage_v2_report(rows, benchmark_id)
    if benchmark_id == "memory_eval_matrix":
        return build_memory_eval_matrix_report(rows)
    if benchmark_id == "retrieval_quality_pack":
        return build_retrieval_quality_pack_report(rows)
    if benchmark_id == "code_memory_federation":
        return build_code_memory_federation_report(rows)
    if benchmark_id == "claim_promotion_pack":
        return build_claim_promotion_pack_report(rows)
    if benchmark_id == "release_evidence_pack":
        return build_release_evidence_pack_report(rows)
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


def build_memory_shortcut_report(rows: list[dict]) -> str:
    lines = ["# Memory Shortcut vs Source Recovery Report", "", "## Result Table", ""]
    lines.append(
        "| Task | Type | Condition | Accepted | Runtime (s) | Total Tokens | Cache-adjusted Proxy | Cached Input | Token Source | Source Reads | Repo Calls | Budget | Notes |"
    )
    lines.append("|---|---|---|---|---:|---|---|---|---|---:|---:|---|---|")
    for row in rows:
        usage = _token_usage(row)
        lines.append(
            "| {task_id} | {task_type} | {condition} | {accepted} | {runtime_seconds} | {token_total} | {token_proxy} | {cached_input} | {token_source} | {source_read_count} | {repo_call_count} | {budget_violation} | {acceptance_notes} |".format(
                task_id=row.get("task_id", ""),
                task_type=row.get("task_type", ""),
                condition=row.get("condition", ""),
                accepted=row.get("accepted", ""),
                runtime_seconds=row.get("runtime_seconds", ""),
                token_total=_token_total_display(row),
                token_proxy=_token_proxy_display(row),
                cached_input=_token_number_display(usage.get("cached_input")),
                token_source=usage.get("source", ""),
                source_read_count=row.get("source_read_count", ""),
                repo_call_count=_repo_call_count(row),
                budget_violation=_memory_shortcut_budget_violation(row),
                acceptance_notes=row.get("acceptance_notes", ""),
            )
        )

    grouped: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        grouped[row.get("task_id", "")][row.get("condition", "")] = row

    lines.extend(
        [
            "",
            "## Paired Shortcut Delta Table",
            "",
            "| Task | Type | Total Token Delta | Total Saving Ratio | Cache-adjusted Delta | Cache-adjusted Ratio | Source Read Delta | Runtime Delta | Outcome | Budget |",
            "|---|---|---:|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled and disabled:
            token_delta = _token_delta(disabled, enabled)
            ratio = _token_saving_ratio(disabled, enabled)
            proxy_delta = _token_proxy_delta(disabled, enabled)
            proxy_ratio = _token_proxy_saving_ratio(disabled, enabled)
            source_delta = _source_read_delta(disabled, enabled)
            runtime_delta = _safe_num(disabled.get("runtime_seconds")) - _safe_num(enabled.get("runtime_seconds"))
            outcome = _pair_outcome(enabled.get("accepted"), disabled.get("accepted"))
            task_type = enabled.get("task_type") or disabled.get("task_type") or ""
            budget = _pair_budget_status(enabled, disabled)
            lines.append(
                f"| {task_id} | {task_type} | {token_delta} | {_ratio_display(ratio)} | {proxy_delta} | {_ratio_display(proxy_ratio)} | {source_delta} | {runtime_delta:.2f} | {outcome} | {budget} |"
            )
        else:
            task_type = (enabled or disabled or {}).get("task_type", "")
            lines.append(
                f"| {task_id} | {task_type} | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | missing_pair | missing_pair |"
            )

    readiness = _memory_shortcut_claim_readiness(grouped)
    diagnostics = _memory_shortcut_proxy_diagnostics(grouped)
    lines.extend(
        [
            "",
            "## Memory Shortcut Claim Readiness",
            "",
            f"- Memory-shortcut saving claim ready: {readiness['ready']}",
            "- Rule: claim bounded memory-shortcut savings only when 6/8 long-source pairs pass, 6/8 passed pairs stay within the enabled source budget, the budget-ok median token saving ratio is at least 20%, 6/8 budget-ok passed pairs reduce source reads, all token totals are named, and negative controls do not show a meaningful memory advantage.",
            f"- Long-source both-passed pairs: {readiness['long_source_both_passed']}",
            f"- Median token saving ratio: {readiness['median_token_saving_ratio']}",
            f"- Source-read reduction pairs: {readiness['source_read_reduction_pairs']}",
            f"- Enabled source-budget-ok pairs: {readiness['enabled_source_budget_ok_pairs']}",
            f"- Negative-control pairs: {readiness['negative_control_pairs']}",
            f"- Negative-control budget-ok pairs: {readiness['negative_control_budget_ok_pairs']}",
            f"- Blocking rows: {readiness['blocking']}",
            "",
            "## Cache-Adjusted Diagnostic Signal",
            "",
            f"- Budget-ok long-source pairs with proxy: {diagnostics['budget_ok_proxy_pairs']}",
            f"- Median cache-adjusted saving ratio: {diagnostics['median_cache_adjusted_saving_ratio']}",
            f"- Proxy-positive budget-ok pairs: {diagnostics['proxy_positive_budget_ok_pairs']}",
            "- Proxy formula: `max(input - cached_input, 0) + output + reasoning`.",
            "- This proxy is diagnostic only. It does not unlock public token/cost saving claims, because cache behavior and local counters are not real billing telemetry.",
            "",
            "## Claim Boundary",
            "",
            "- This is a long-source recovery shortcut benchmark, not a global token/cost or real-billing benchmark.",
            "- Enabled answers still need source verification; memory prose is not authority.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_functional_token_economics_report(rows: list[dict]) -> str:
    lines = ["# Functional Token Economics Report", "", "## Result Table", ""]
    lines.append(
        "| Scenario | Workflow | Baseline Tokens | Optimized Tokens | Delta | Saving Ratio | Accepted |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---|")
    for row in rows:
        lines.append(
            "| {scenario_id} | {workflow} | {baseline_tokens} | {optimized_tokens} | {token_delta} | {saving_ratio} | {accepted} |".format(
                scenario_id=row.get("scenario_id", ""),
                workflow=row.get("workflow", ""),
                baseline_tokens=row.get("baseline_tokens", ""),
                optimized_tokens=row.get("optimized_tokens", ""),
                token_delta=row.get("token_delta", ""),
                saving_ratio=_ratio_display(_safe_token_num(row.get("saving_ratio"))),
                accepted=row.get("accepted", ""),
            )
        )

    readiness = _functional_token_economics_readiness(rows)
    lines.extend(
        [
            "",
            "## Feature-Level Claim Readiness",
            "",
            f"- Functional fixture token-economics ready: {readiness['ready']}",
            f"- Scenario count: {readiness['scenario_count']}",
            f"- Minimum saving ratio: {readiness['minimum_saving_ratio']}",
            f"- Median saving ratio: {readiness['median_saving_ratio']}",
            f"- Blocking rows: {readiness['blocking']}",
            "",
            "## Global Claim Boundary",
            "",
            "- Global token/cost saving ready: no",
            "- Rule: this collection measures fixture payload economics only. It does not prove real billing, live-agent behavior, answer quality, or whole-product savings.",
            "- Use this for bounded feature-level wording such as compact progressive-disclosure payloads on the declared fixture corpus.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_storage_v2_report(rows: list[dict], benchmark_id: str) -> str:
    title = {
        "storage_v2_baseline": "Storage v2 Baseline Report",
        "migration_roundtrip": "Migration Roundtrip Report",
        "local_index_fabric_smoke": "Local Index Fabric Smoke Report",
    }.get(benchmark_id, "Storage v2 Report")
    lines = [f"# {title}", "", "## Result Table", ""]
    lines.append(
        "| Operation | Dataset | Entries | JSON Files | p50 ms | p95 ms | RSS MB | Disk Bytes | DB Bytes | Sidecar Bytes | Accepted |"
    )
    lines.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|")
    for row in rows:
        lines.append(
            "| {operation} | {dataset_id} | {entry_count} | {json_file_count} | {p50_ms} | {p95_ms} | {rss_peak_mb} | {disk_bytes} | {db_size_bytes} | {sidecar_size_bytes} | {accepted} |".format(
                operation=row.get("operation", ""),
                dataset_id=row.get("dataset_id", ""),
                entry_count=row.get("entry_count", ""),
                json_file_count=row.get("json_file_count", ""),
                p50_ms=row.get("p50_ms", ""),
                p95_ms=row.get("p95_ms", ""),
                rss_peak_mb=row.get("rss_peak_mb", ""),
                disk_bytes=row.get("disk_bytes", ""),
                db_size_bytes=row.get("db_size_bytes", ""),
                sidecar_size_bytes=row.get("sidecar_size_bytes", ""),
                accepted=row.get("accepted", ""),
            )
        )

    if benchmark_id == "migration_roundtrip":
        lines.extend(["", "## Roundtrip Checks", ""])
        lines.append(
            "| Dataset | Dry-run Checksum | Canonical Checksum | Rollback Checksum | Apply Match | Rollback Match |"
        )
        lines.append("|---|---|---|---|---|---|")
        for row in rows:
            lines.append(
                "| {dataset_id} | {dry} | {canonical} | {rollback} | {apply_match} | {rollback_match} |".format(
                    dataset_id=row.get("dataset_id", ""),
                    dry=_short_hash(row.get("dry_run_checksum")),
                    canonical=_short_hash(row.get("canonical_checksum")),
                    rollback=_short_hash(row.get("rollback_checksum")),
                    apply_match=row.get("apply_checksum_match", ""),
                    rollback_match=row.get("rollback_checksum_match", ""),
                )
            )

    if benchmark_id == "local_index_fabric_smoke":
        lines.extend(["", "## Manifest-Last Checks", ""])
        lines.append(
            "| Dataset | Manifest Commit | Interrupted Visible | Fingerprint Drift | Fallback |"
        )
        lines.append("|---|---|---|---|---|")
        for row in rows:
            lines.append(
                "| {dataset_id} | {manifest_commit} | {interrupted} | {drift} | {fallback} |".format(
                    dataset_id=row.get("dataset_id", ""),
                    manifest_commit=row.get("manifest_commit", ""),
                    interrupted=row.get("interrupted_generation_visible", ""),
                    drift=row.get("source_fingerprint_drift_detected", ""),
                    fallback=row.get("fallback_reason", ""),
                )
            )

    readiness = _storage_v2_readiness(rows, benchmark_id)
    lines.extend(
        [
            "",
            "## Storage v2 Claim Readiness",
            "",
            f"- Storage v2 public performance claim ready: {readiness['public_performance_ready']}",
            f"- Contract smoke accepted: {readiness['contract_smoke_accepted']}",
            f"- Blocking rows: {readiness['blocking']}",
            "",
            "## Claim Boundary",
            "",
            "- v4.0.0 establishes migration and benchmark contracts; it does not switch the default storage backend.",
            "- Diagnostic smoke rows are not 10k / 100k / 1M release evidence and must not be used as public speedup claims.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_memory_eval_matrix_report(rows: list[dict]) -> str:
    lines = ["# Memory Eval Matrix Report", "", "## Dimensions", ""]
    lines.append("| Dimension | Task | Accepted | Safe To Answer | False Positives | Artifact |")
    lines.append("|---|---|---|---|---:|---|")
    for row in rows:
        lines.append(
            "| {dimension} | {task_id} | {accepted} | {safe_to_answer} | {false_positive_count} | {artifact_state} |".format(
                dimension=row.get("dimension", ""),
                task_id=row.get("task_id", ""),
                accepted=row.get("accepted", ""),
                safe_to_answer=row.get("safe_to_answer", ""),
                false_positive_count=row.get("false_positive_count", ""),
                artifact_state=row.get("artifact_state", ""),
            )
        )
    covered = {str(row.get("dimension") or "") for row in rows}
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            f"- Covered dimensions: {len(covered)}",
            "- This is a release gate for memory-runtime behavior, not a global answer-quality or token-saving claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_retrieval_quality_pack_report(rows: list[dict]) -> str:
    lines = ["# Retrieval Quality Pack Report", "", "## Components", ""]
    lines.append(
        "| Capability | Default | Accepted | Precision@k | Recall Delta | FP Delta | Fanout | Duplicate Rate |"
    )
    lines.append("|---|---|---|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            "| {capability} | {default_enabled} | {accepted} | {precision_at_k} | {recall_delta} | {false_positive_delta} | {fanout_cost} | {duplicate_rate} |".format(
                capability=row.get("capability", ""),
                default_enabled=row.get("default_enabled", ""),
                accepted=row.get("accepted", ""),
                precision_at_k=row.get("precision_at_k", ""),
                recall_delta=row.get("recall_delta", ""),
                false_positive_delta=row.get("false_positive_delta", ""),
                fanout_cost=row.get("fanout_cost", ""),
                duplicate_rate=row.get("duplicate_rate", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- Reranker, query rewriting, and HyDE remain opt-in unless component gates pass.",
            "- Query rewriting must show recall uplift greater than false-positive drift.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_code_memory_federation_report(rows: list[dict]) -> str:
    lines = ["# Code-Memory Federation Report", "", "## Evidence Rows", ""]
    lines.append("| Task | File | Source | Stale Status | Generated Is Truth | Accepted |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        stale_check = row.get("stale_check") if isinstance(row.get("stale_check"), dict) else {}
        lines.append(
            "| {task_id} | {file_path} | {source_id} | {stale_status} | {generated_layer_is_truth} | {accepted} |".format(
                task_id=row.get("task_id", ""),
                file_path=row.get("file_path", ""),
                source_id=row.get("source_id", ""),
                stale_status=stale_check.get("status", ""),
                generated_layer_is_truth=row.get("generated_layer_is_truth", ""),
                accepted=row.get("accepted", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- file_context federates current code evidence with memory; it is not a full code search engine.",
            "- Generated code wiki or module-atlas prose remains derived evidence, not canonical truth.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_claim_promotion_pack_report(rows: list[dict]) -> str:
    lines = ["# Claim Promotion Pack Report", "", "## Promotion Policy Rows", ""]
    lines.append("| Claim | Status | Ready | Source Gate | Type | Accepted |")
    lines.append("|---|---|---|---|---|---|")
    for row in rows:
        lines.append(
            "| {claim_id} | {status} | {ready} | {source_gate} | {claim_type} | {accepted} |".format(
                claim_id=row.get("claim_id", ""),
                status=row.get("status", ""),
                ready=row.get("ready", ""),
                source_gate=row.get("source_gate", ""),
                claim_type=row.get("claim_type", ""),
                accepted=row.get("accepted", ""),
            )
        )
    blocked = sorted(str(row.get("claim_id")) for row in rows if row.get("status") == "blocked")
    bounded = sorted(str(row.get("claim_id")) for row in rows if row.get("status") == "bounded_ready")
    lines.extend(
        [
            "",
            "## Claim Promotion Gate",
            "",
            f"- Blocked claims: {', '.join(blocked) if blocked else 'none'}",
            f"- Bounded local claims: {', '.join(bounded) if bounded else 'none'}",
            "- Public promotion requires machine-readable gates; bounded local readiness is not a broad performance or token-saving claim.",
        ]
    )
    return "\n".join(lines) + "\n"


def build_release_evidence_pack_report(rows: list[dict]) -> str:
    lines = ["# Release Evidence Pack Report", "", "## Evidence Packs", ""]
    lines.append(
        "| Pack | Snapshot Runs | Accepted | Failed | Unknown | Blocked Claims | Bounded Claims | Package Match | Gate |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---|---|")
    for row in rows:
        package_match = bool(row.get("packaged_suite_match")) and bool(row.get("packaged_snapshot_match"))
        lines.append(
            "| {pack_id} | {snapshot_run_count} | {accepted_runs} | {failed_runs} | {unknown_runs} | {blocked_claim_count} | {bounded_claim_count} | {package_match} | {gate_passed} |".format(
                pack_id=row.get("pack_id", ""),
                snapshot_run_count=row.get("snapshot_run_count", ""),
                accepted_runs=row.get("accepted_runs", ""),
                failed_runs=row.get("failed_runs", ""),
                unknown_runs=row.get("unknown_runs", ""),
                blocked_claim_count=row.get("blocked_claim_count", ""),
                bounded_claim_count=row.get("bounded_claim_count", ""),
                package_match=package_match,
                gate_passed=row.get("gate_passed", ""),
            )
        )
    lines.extend(
        [
            "",
            "## Claim Boundary",
            "",
            "- The release evidence pack proves clean-checkout evidence packaging and claim-gate visibility.",
            "- It does not turn blocked claims into public performance, token-saving, or default-behavior claims.",
        ]
    )
    return "\n".join(lines) + "\n"


def _safe_num(value) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _short_hash(value) -> str:
    if isinstance(value, str) and len(value) > 12:
        return value[:12]
    return str(value or "")


def _storage_v2_readiness(rows: list[dict], benchmark_id: str) -> dict[str, str]:
    blockers: list[str] = []
    accepted_count = 0
    for row in rows:
        row_id = row.get("operation") or row.get("dataset_id") or "unknown"
        if row.get("accepted") == "yes":
            accepted_count += 1
        else:
            blockers.append(f"{row_id}/accepted={row.get('accepted') or 'missing'}")
        readiness = row.get("claim_readiness")
        if isinstance(readiness, dict):
            if benchmark_id == "storage_v2_baseline" and readiness.get("ready") is True:
                blockers.append(f"{row_id}/baseline_smoke_claim_ready_should_be_false")
        else:
            blockers.append(f"{row_id}/claim_readiness_missing")
        if benchmark_id == "migration_roundtrip":
            if row.get("apply_checksum_match") is not True:
                blockers.append(f"{row_id}/apply_checksum_match=false")
            if row.get("rollback_checksum_match") is not True:
                blockers.append(f"{row_id}/rollback_checksum_match=false")
        if benchmark_id == "local_index_fabric_smoke":
            if row.get("manifest_commit") is not True:
                blockers.append(f"{row_id}/manifest_commit=false")
            if row.get("interrupted_generation_visible") is not False:
                blockers.append(f"{row_id}/interrupted_generation_visible=true")
            if row.get("source_fingerprint_drift_detected") is not True:
                blockers.append(f"{row_id}/source_fingerprint_drift_detected=false")

    return {
        "public_performance_ready": "no",
        "contract_smoke_accepted": "yes" if rows and not blockers else "no",
        "blocking": ", ".join(blockers) if blockers else "none",
    }


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


def _token_number_display(value) -> str:
    number = _safe_token_num(value)
    if number is None:
        return "unavailable"
    return str(int(number)) if number.is_integer() else f"{number:.2f}"


def _cache_adjusted_token_proxy(row: dict) -> float | None:
    usage = _token_usage(row)
    input_tokens = _safe_token_num(usage.get("input"))
    if input_tokens is None:
        return None
    cached_input = _safe_token_num(usage.get("cached_input")) or 0.0
    output_tokens = _safe_token_num(usage.get("output")) or 0.0
    reasoning_tokens = _safe_token_num(usage.get("reasoning")) or 0.0
    uncached_input = max(input_tokens - cached_input, 0.0)
    return uncached_input + output_tokens + reasoning_tokens


def _token_proxy_display(row: dict) -> str:
    proxy = _cache_adjusted_token_proxy(row)
    if proxy is None:
        return "unavailable"
    return str(int(proxy)) if proxy.is_integer() else f"{proxy:.2f}"


def _token_delta(disabled: dict, enabled: dict) -> str:
    disabled_total = _safe_token_num(_token_usage(disabled).get("total"))
    enabled_total = _safe_token_num(_token_usage(enabled).get("total"))
    if disabled_total is None or enabled_total is None:
        return "unavailable"
    delta = disabled_total - enabled_total
    return str(int(delta)) if delta.is_integer() else f"{delta:.2f}"


def _token_saving_ratio(disabled: dict, enabled: dict) -> float | None:
    disabled_total = _safe_token_num(_token_usage(disabled).get("total"))
    enabled_total = _safe_token_num(_token_usage(enabled).get("total"))
    if disabled_total is None or enabled_total is None or disabled_total <= 0:
        return None
    return (disabled_total - enabled_total) / disabled_total


def _token_proxy_delta(disabled: dict, enabled: dict) -> str:
    disabled_proxy = _cache_adjusted_token_proxy(disabled)
    enabled_proxy = _cache_adjusted_token_proxy(enabled)
    if disabled_proxy is None or enabled_proxy is None:
        return "unavailable"
    delta = disabled_proxy - enabled_proxy
    return str(int(delta)) if delta.is_integer() else f"{delta:.2f}"


def _token_proxy_saving_ratio(disabled: dict, enabled: dict) -> float | None:
    disabled_proxy = _cache_adjusted_token_proxy(disabled)
    enabled_proxy = _cache_adjusted_token_proxy(enabled)
    if disabled_proxy is None or enabled_proxy is None or disabled_proxy <= 0:
        return None
    return (disabled_proxy - enabled_proxy) / disabled_proxy


def _ratio_display(value: float | None) -> str:
    if value is None:
        return "unavailable"
    return f"{value:.3f}"


def _source_read_delta(disabled: dict, enabled: dict) -> str:
    delta = _source_read_delta_num(disabled, enabled)
    if delta is None:
        return "unavailable"
    return str(int(delta)) if delta.is_integer() else f"{delta:.2f}"


def _source_read_delta_num(disabled: dict, enabled: dict) -> float | None:
    disabled_reads = _safe_token_num(disabled.get("source_read_count"))
    enabled_reads = _safe_token_num(enabled.get("source_read_count"))
    if disabled_reads is None or enabled_reads is None:
        return None
    return disabled_reads - enabled_reads


def _repo_call_count(row: dict) -> int:
    calls = row.get("repo_calls")
    if isinstance(calls, list):
        return len(calls)
    if calls:
        return 1
    return 0


def _memory_shortcut_budget_violation(row: dict) -> str:
    task_type = str(row.get("task_type") or "")
    condition = str(row.get("condition") or "")
    source_reads = _safe_token_num(row.get("source_read_count"))
    source_reads = 0 if source_reads is None else int(source_reads)
    repo_calls = _repo_call_count(row)
    if task_type == "long_source_recovery" and condition == "enabled":
        if source_reads > 2:
            return f"enabled_source_reads>{2}"
    if task_type == "negative_control":
        if source_reads > 1:
            return "negative_control_source_reads>1"
        if repo_calls > 3:
            return "negative_control_repo_calls>3"
    return "none"


def _budget_ok(row: dict | None) -> bool:
    if row is None:
        return False
    return _memory_shortcut_budget_violation(row) == "none"


def _pair_budget_status(enabled: dict, disabled: dict) -> str:
    task_type = str(enabled.get("task_type") or disabled.get("task_type") or "")
    if task_type == "long_source_recovery":
        return _memory_shortcut_budget_violation(enabled)
    if task_type == "negative_control":
        violations = []
        for condition, row in [("enabled", enabled), ("disabled", disabled)]:
            violation = _memory_shortcut_budget_violation(row)
            if violation != "none":
                violations.append(f"{condition}:{violation}")
        return ", ".join(violations) if violations else "none"
    return "none"


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


def _memory_shortcut_claim_readiness(grouped: dict[str, dict[str, dict]]) -> dict[str, str]:
    long_source_ratios: list[float] = []
    long_source_both_passed = 0
    source_read_reduction_pairs = 0
    enabled_source_budget_ok_pairs = 0
    negative_control_pairs = 0
    negative_control_budget_ok_pairs = 0
    blockers: list[str] = []

    for task_id, pair in sorted(grouped.items()):
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled is None or disabled is None:
            blockers.append(f"{task_id}/missing_pair")
            continue
        for condition, row in [("enabled", enabled), ("disabled", disabled)]:
            if not _has_token_total(row):
                blockers.append(f"{task_id}/{condition}/token_total_unavailable")

        task_type = str(enabled.get("task_type") or disabled.get("task_type") or "")
        both_passed = enabled.get("accepted") == "yes" and disabled.get("accepted") == "yes"
        ratio = _token_saving_ratio(disabled, enabled)
        source_delta = _source_read_delta_num(disabled, enabled)
        if task_type == "negative_control":
            negative_control_pairs += 1
            if _budget_ok(enabled) and _budget_ok(disabled):
                negative_control_budget_ok_pairs += 1
            else:
                budget_status = _pair_budget_status(enabled, disabled)
                blockers.append(f"{task_id}/budget={budget_status}")
            memory_calls = enabled.get("memory_calls")
            used_memory = bool(memory_calls) if isinstance(memory_calls, list) else bool(memory_calls)
            if used_memory and ratio is not None and ratio >= 0.2:
                blockers.append(f"{task_id}/negative_control_token_advantage={ratio:.3f}")
            if source_delta is not None and source_delta > 0:
                blockers.append(f"{task_id}/negative_control_source_read_advantage={int(source_delta)}")
            if used_memory:
                blockers.append(f"{task_id}/negative_control_memory_calls_present")
            continue
        if task_type != "long_source_recovery":
            blockers.append(f"{task_id}/task_type={task_type or 'missing'}")
            continue
        if both_passed:
            long_source_both_passed += 1
            if _budget_ok(enabled):
                enabled_source_budget_ok_pairs += 1
                if ratio is not None:
                    long_source_ratios.append(ratio)
                    if ratio <= 0:
                        blockers.append(
                            f"{task_id}/token_delta_not_saving={_token_delta(disabled, enabled)}"
                        )
                if source_delta is not None and source_delta > 0:
                    source_read_reduction_pairs += 1
            else:
                blockers.append(f"{task_id}/budget={_memory_shortcut_budget_violation(enabled)}")

    median_ratio: float | None = None
    if long_source_ratios:
        ordered = sorted(long_source_ratios)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            median_ratio = ordered[midpoint]
        else:
            median_ratio = (ordered[midpoint - 1] + ordered[midpoint]) / 2

    if long_source_both_passed < 6:
        blockers.append(f"long_source_both_passed={long_source_both_passed}/6")
    if median_ratio is None or median_ratio < 0.2:
        blockers.append(f"median_token_saving_ratio={_ratio_display(median_ratio)}")
    if source_read_reduction_pairs < 6:
        blockers.append(f"source_read_reduction_pairs={source_read_reduction_pairs}/6")
    if enabled_source_budget_ok_pairs < 6:
        blockers.append(f"enabled_source_budget_ok_pairs={enabled_source_budget_ok_pairs}/6")
    if negative_control_pairs < 2:
        blockers.append(f"negative_control_pairs={negative_control_pairs}/2")
    if negative_control_budget_ok_pairs < 2:
        blockers.append(f"negative_control_budget_ok_pairs={negative_control_budget_ok_pairs}/2")

    return {
        "ready": "no" if blockers else "yes",
        "long_source_both_passed": str(long_source_both_passed),
        "median_token_saving_ratio": _ratio_display(median_ratio),
        "source_read_reduction_pairs": str(source_read_reduction_pairs),
        "enabled_source_budget_ok_pairs": str(enabled_source_budget_ok_pairs),
        "negative_control_pairs": str(negative_control_pairs),
        "negative_control_budget_ok_pairs": str(negative_control_budget_ok_pairs),
        "blocking": ", ".join(blockers) if blockers else "none",
    }


def _memory_shortcut_proxy_diagnostics(grouped: dict[str, dict[str, dict]]) -> dict[str, str]:
    ratios: list[float] = []
    positive_pairs = 0

    for pair in grouped.values():
        enabled = pair.get("enabled")
        disabled = pair.get("disabled")
        if enabled is None or disabled is None:
            continue
        task_type = str(enabled.get("task_type") or disabled.get("task_type") or "")
        if task_type != "long_source_recovery":
            continue
        both_passed = enabled.get("accepted") == "yes" and disabled.get("accepted") == "yes"
        if not both_passed or not _budget_ok(enabled):
            continue
        ratio = _token_proxy_saving_ratio(disabled, enabled)
        if ratio is None:
            continue
        ratios.append(ratio)
        if ratio > 0:
            positive_pairs += 1

    median_ratio: float | None = None
    if ratios:
        ordered = sorted(ratios)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            median_ratio = ordered[midpoint]
        else:
            median_ratio = (ordered[midpoint - 1] + ordered[midpoint]) / 2

    return {
        "budget_ok_proxy_pairs": str(len(ratios)),
        "median_cache_adjusted_saving_ratio": _ratio_display(median_ratio),
        "proxy_positive_budget_ok_pairs": str(positive_pairs),
    }


def _functional_token_economics_readiness(rows: list[dict]) -> dict[str, str]:
    blockers: list[str] = []
    ratios: list[float] = []

    for row in rows:
        scenario_id = row.get("scenario_id") or "unknown"
        ratio = _safe_token_num(row.get("saving_ratio"))
        minimum = _safe_token_num(row.get("minimum_saving_ratio"))
        token_delta = _safe_token_num(row.get("token_delta"))
        if ratio is None:
            blockers.append(f"{scenario_id}/saving_ratio_missing")
            continue
        if minimum is None:
            blockers.append(f"{scenario_id}/minimum_saving_ratio_missing")
            continue
        ratios.append(ratio)
        if row.get("accepted") != "yes":
            blockers.append(f"{scenario_id}/accepted={row.get('accepted') or 'missing'}")
        if row.get("fixture_only") is not True:
            blockers.append(f"{scenario_id}/fixture_only_not_true")
        if token_delta is None or token_delta <= 0:
            blockers.append(f"{scenario_id}/token_delta_not_saving={row.get('token_delta')}")
        if ratio < minimum:
            blockers.append(
                f"{scenario_id}/saving_ratio={ratio:.3f}<minimum={minimum:.3f}"
            )

    median_ratio: float | None = None
    if ratios:
        ordered = sorted(ratios)
        midpoint = len(ordered) // 2
        if len(ordered) % 2:
            median_ratio = ordered[midpoint]
        else:
            median_ratio = (ordered[midpoint - 1] + ordered[midpoint]) / 2

    min_ratio = min(ratios) if ratios else None
    return {
        "ready": "yes" if rows and not blockers else "no",
        "scenario_count": str(len(rows)),
        "minimum_saving_ratio": _ratio_display(min_ratio),
        "median_saving_ratio": _ratio_display(median_ratio),
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
