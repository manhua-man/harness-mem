from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "scripts"
    / "v152_recall_failure_analysis.py"
)
SPEC = importlib.util.spec_from_file_location("v152_recall_failure_analysis", SCRIPT_PATH)
assert SPEC and SPEC.loader
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def test_classify_failure_case_prefers_fusion_sort_error_when_hybrid_underperforms_best_component():
    assert analysis.classify_failure_case(0.6, 1.0, 0.4) == "fusion_sort_error"


def test_classify_failure_case_marks_fts_miss_when_vector_beats_hybrid_and_fts():
    assert analysis.classify_failure_case(0.2, 0.8, 0.8) == "fts_miss"


def test_render_markdown_surfaces_bucket_summary_and_representatives():
    report = {
        "generated_at": "2026-05-16T00:00:00+00:00",
        "dataset_path": "dataset.json",
        "baseline_path": "baseline.json",
        "failed_case_count": 1,
        "bucket_counts": {"fusion_sort_error": 1},
        "latency_summary": {
            "fts": {"avg_ms": 1.0, "p50_ms": 1.0, "p95_ms": 1.0, "max_ms": 1.0},
            "vector": {"avg_ms": 2.0, "p50_ms": 2.0, "p95_ms": 2.0, "max_ms": 2.0},
            "hybrid": {"avg_ms": 3.0, "p50_ms": 3.0, "p95_ms": 3.0, "max_ms": 3.0},
        },
        "per_type_bucket_counts": {"multi-session": {"fusion_sort_error": 1}},
        "cases": [
            {
                "question_id": "q-1",
                "question_type": "multi-session",
                "question": "What did we decide?",
                "answer_session_ids": ["answer-1"],
                "bucket": "fusion_sort_error",
                "variants": {
                    "fts": {"recall": 1.0, "latency_ms": 1.0, "retrieved_ids": ["answer-1"]},
                    "vector": {"recall": 0.8, "latency_ms": 2.0, "retrieved_ids": ["answer-1"]},
                    "hybrid": {"recall": 0.0, "latency_ms": 3.0, "retrieved_ids": ["miss-1"]},
                },
            }
        ],
    }

    markdown = analysis.render_markdown(report)

    assert "# v1.5.2 Recall Failure Analysis" in markdown
    assert "| fusion_sort_error | 1 |" in markdown
    assert "`q-1` [multi-session] What did we decide?" in markdown
