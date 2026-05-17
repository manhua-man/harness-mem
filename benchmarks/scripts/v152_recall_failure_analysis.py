"""Analyze hybrid recall failures with FTS/vector/hybrid ablations."""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from harness_mem.tools.longmemeval import (
    BenchVerbatimStore,
    RealHybridSearch,
    _session_doc_for_query,
    compute_recall,
)

MAIN_BUCKETS = ("fts_miss", "vector_miss", "fusion_sort_error")


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * pct))))
    return ordered[index]


def summarize_latencies(values: list[float]) -> dict[str, float]:
    return {
        "avg_ms": round(sum(values) / len(values), 2) if values else 0.0,
        "p50_ms": round(percentile(values, 0.50), 2),
        "p95_ms": round(percentile(values, 0.95), 2),
        "max_ms": round(max(values), 2) if values else 0.0,
    }


def classify_failure_case(fts_recall: float, vector_recall: float, hybrid_recall: float) -> str:
    best_component = max(fts_recall, vector_recall)
    if hybrid_recall + 1e-9 < best_component:
        return "fusion_sort_error"
    if fts_recall + 1e-9 < vector_recall:
        return "fts_miss"
    if vector_recall + 1e-9 < fts_recall:
        return "vector_miss"
    return "mixed_or_both_miss"


def _build_case_payload(entry: dict) -> tuple[list[str], list[str], dict[str, str]]:
    corpus_ids: list[str] = []
    corpus_texts: list[str] = []
    corpus_dates: dict[str, str] = {}
    question = entry["question"]
    haystack_session_ids = entry["haystack_session_ids"]
    haystack_sessions = entry["haystack_sessions"]
    haystack_dates = entry.get("haystack_dates", [""] * len(haystack_session_ids))

    for sess_id, session, date in zip(haystack_session_ids, haystack_sessions, haystack_dates):
        doc = _session_doc_for_query(session, question)
        if not doc:
            continue
        corpus_ids.append(sess_id)
        corpus_texts.append(doc)
        corpus_dates[sess_id] = date
    return corpus_ids, corpus_texts, corpus_dates


def _run_variant_case(
    entry: dict,
    searcher: RealHybridSearch,
    *,
    top_k: int,
    variant: str,
) -> tuple[list[str], float, str, str | None]:
    corpus_ids, corpus_texts, corpus_dates = _build_case_payload(entry)
    tmpdir = tempfile.mkdtemp(prefix="hm_v152_")
    try:
        db_path = Path(tmpdir) / "bench.sqlite"
        store = BenchVerbatimStore(str(db_path))
        for sess_id, text in zip(corpus_ids, corpus_texts):
            timestamp = corpus_dates.get(sess_id, datetime.now(timezone.utc).isoformat())
            store.add(str(uuid4()), sess_id, text, timestamp)

        searcher.set_path(str(db_path))
        start = time.perf_counter()
        result = searcher.search_result(entry["question"], limit=top_k, variant=variant)
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        retrieved_ids = [row["session_id"] for row in result.rows]
        return retrieved_ids, latency_ms, result.effective_mode, result.fallback_reason
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def analyze_failures(
    dataset_path: Path,
    baseline_path: Path,
    *,
    top_k: int = 5,
) -> dict:
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    dataset_by_qid = {entry["question_id"]: entry for entry in dataset}
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    failed_cases = [case for case in baseline.get("results", []) if case.get("recall", 1.0) < 1.0]

    searcher = RealHybridSearch()
    bucket_counts: Counter[str] = Counter()
    type_counts: defaultdict[str, Counter[str]] = defaultdict(Counter)
    latencies_by_variant: dict[str, list[float]] = {"fts": [], "vector": [], "hybrid": []}
    analyzed_cases: list[dict] = []

    for failed in failed_cases:
        entry = dataset_by_qid.get(failed["question_id"])
        if entry is None:
            continue

        variant_results: dict[str, dict] = {}
        answer_session_ids = set(entry["answer_session_ids"])
        for variant in ("fts", "vector", "hybrid"):
            retrieved_ids, latency_ms, effective_mode, fallback_reason = _run_variant_case(
                entry,
                searcher,
                top_k=top_k,
                variant=variant,
            )
            variant_results[variant] = {
                "retrieved_ids": retrieved_ids,
                "recall": compute_recall(retrieved_ids, answer_session_ids),
                "latency_ms": latency_ms,
                "effective_mode": effective_mode,
                "fallback_reason": fallback_reason,
            }
            latencies_by_variant[variant].append(latency_ms)

        bucket = classify_failure_case(
            variant_results["fts"]["recall"],
            variant_results["vector"]["recall"],
            variant_results["hybrid"]["recall"],
        )
        bucket_counts[bucket] += 1
        type_counts[entry["question_type"]][bucket] += 1

        analyzed_cases.append(
            {
                "question_id": entry["question_id"],
                "question_type": entry["question_type"],
                "question": entry["question"],
                "answer_session_ids": entry["answer_session_ids"],
                "baseline_recall": failed["recall"],
                "bucket": bucket,
                "variants": variant_results,
            }
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_path": str(dataset_path),
        "baseline_path": str(baseline_path),
        "top_k": top_k,
        "failed_case_count": len(analyzed_cases),
        "bucket_counts": dict(bucket_counts),
        "latency_summary": {
            variant: summarize_latencies(values)
            for variant, values in latencies_by_variant.items()
        },
        "per_type_bucket_counts": {
            question_type: dict(counter)
            for question_type, counter in sorted(type_counts.items())
        },
        "cases": analyzed_cases,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# v1.5.2 Recall Failure Analysis",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dataset: `{report['dataset_path']}`",
        f"- Baseline: `{report['baseline_path']}`",
        f"- Failed hybrid cases analyzed: {report['failed_case_count']}",
        "",
        "## Bucket Summary",
        "",
        "| Bucket | Cases |",
        "|--------|-------|",
    ]

    for bucket in (*MAIN_BUCKETS, "mixed_or_both_miss"):
        lines.append(f"| {bucket} | {report['bucket_counts'].get(bucket, 0)} |")

    lines.extend(
        [
            "",
            "## Latency Snapshot",
            "",
            "| Variant | Avg (ms) | P50 (ms) | P95 (ms) | Max (ms) |",
            "|---------|----------|----------|----------|----------|",
        ]
    )
    for variant in ("fts", "vector", "hybrid"):
        summary = report["latency_summary"][variant]
        lines.append(
            f"| {variant} | {summary['avg_ms']:.2f} | {summary['p50_ms']:.2f} | "
            f"{summary['p95_ms']:.2f} | {summary['max_ms']:.2f} |"
        )

    lines.extend(
        [
            "",
            "## Per-Type Buckets",
            "",
            "| Question Type | FTS Miss | Vector Miss | Fusion Sort Error | Mixed/Both |",
            "|---------------|----------|-------------|-------------------|------------|",
        ]
    )
    for question_type, counts in report["per_type_bucket_counts"].items():
        lines.append(
            f"| {question_type} | {counts.get('fts_miss', 0)} | {counts.get('vector_miss', 0)} | "
            f"{counts.get('fusion_sort_error', 0)} | {counts.get('mixed_or_both_miss', 0)} |"
        )

    lines.append("")
    lines.append("## Representative Cases")
    lines.append("")
    for bucket in (*MAIN_BUCKETS, "mixed_or_both_miss"):
        lines.append(f"### {bucket}")
        bucket_cases = [
            case
            for case in report["cases"]
            if case["bucket"] == bucket
        ]
        if not bucket_cases:
            lines.append("")
            lines.append("- No cases fell into this bucket in the current run.")
            lines.append("")
            continue

        bucket_cases.sort(
            key=lambda case: (
                max(case["variants"]["fts"]["recall"], case["variants"]["vector"]["recall"])
                - case["variants"]["hybrid"]["recall"],
                1.0 - case["variants"]["hybrid"]["recall"],
            ),
            reverse=True,
        )
        for case in bucket_cases[:3]:
            lines.append("")
            lines.append(
                f"- `{case['question_id']}` [{case['question_type']}] {case['question']}"
            )
            lines.append(
                "  "
                f"Recall -> fts {case['variants']['fts']['recall']:.3f}, "
                f"vector {case['variants']['vector']['recall']:.3f}, "
                f"hybrid {case['variants']['hybrid']['recall']:.3f}"
            )
            lines.append(
                "  "
                f"Latency -> fts {case['variants']['fts']['latency_ms']:.2f}ms, "
                f"vector {case['variants']['vector']['latency_ms']:.2f}ms, "
                f"hybrid {case['variants']['hybrid']['latency_ms']:.2f}ms"
            )
            lines.append(f"  Answer sessions: {', '.join(case['answer_session_ids'])}")
            lines.append(
                "  "
                f"Hybrid top-{len(case['variants']['hybrid']['retrieved_ids'])}: "
                + ", ".join(case["variants"]["hybrid"]["retrieved_ids"])
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze v1.5.2 recall failures.")
    parser.add_argument("--dataset", required=True, help="Path to LongMemEval JSON dataset")
    parser.add_argument(
        "--baseline",
        default=(
            Path(__file__).resolve().parents[1]
            / "results"
            / "results_harness_hybrid_temporal_compare_top5_20260512_fixed_baseline.json"
        ),
        help="Path to baseline hybrid benchmark result JSON",
    )
    parser.add_argument(
        "--out-json",
        default=(
            Path(__file__).resolve().parents[1]
            / "results"
            / "v152_recall_failure_analysis.json"
        ),
        help="Output JSON path",
    )
    parser.add_argument(
        "--out-md",
        default=(
            Path(__file__).resolve().parents[2]
            / "docs"
            / "benchmark"
            / "v152-recall-failure-analysis.md"
        ),
        help="Output Markdown report path",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Top-k cutoff")
    args = parser.parse_args()

    baseline_path = Path(args.baseline)
    out_json_path = Path(args.out_json)
    out_md_path = Path(args.out_md)
    dataset_path = Path(args.dataset)

    report = analyze_failures(
        dataset_path,
        baseline_path,
        top_k=args.top_k,
    )
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    out_md_path.parent.mkdir(parents=True, exist_ok=True)
    out_md_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"Wrote JSON report to {out_json_path}")
    print(f"Wrote Markdown report to {out_md_path}")


if __name__ == "__main__":
    main()
