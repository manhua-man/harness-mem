from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
VALIDATE_RUN_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "validate_run.py"
VALIDATE_RUN_SPEC = importlib.util.spec_from_file_location(
    "benchmark_validate_run_v42",
    VALIDATE_RUN_PATH,
)
assert VALIDATE_RUN_SPEC is not None
assert VALIDATE_RUN_SPEC.loader is not None
VALIDATE_RUN = importlib.util.module_from_spec(VALIDATE_RUN_SPEC)
VALIDATE_RUN_SPEC.loader.exec_module(VALIDATE_RUN)

RENDER_REPORT_PATH = REPO_ROOT / "benchmark-suite" / "tools" / "render_report.py"
RENDER_REPORT_SPEC = importlib.util.spec_from_file_location(
    "benchmark_render_report_v42",
    RENDER_REPORT_PATH,
)
assert RENDER_REPORT_SPEC is not None
assert RENDER_REPORT_SPEC.loader is not None
RENDER_REPORT = importlib.util.module_from_spec(RENDER_REPORT_SPEC)
RENDER_REPORT_SPEC.loader.exec_module(RENDER_REPORT)


def _write_run(run_dir: Path, benchmark_id: str, rows: list[dict]) -> None:
    (run_dir / "results").mkdir(parents=True)
    (run_dir / "notes").mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"benchmark_id": benchmark_id, "accepted": True}),
        encoding="utf-8",
    )
    (run_dir / "dataset.manifest.json").write_text(
        json.dumps(
            {
                "dataset": benchmark_id,
                "version": 1,
                "dataset_hash": f"{benchmark_id}-unit",
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "report.md").write_text("# report\n", encoding="utf-8")
    (run_dir / "summary.csv").write_text("task_id\n", encoding="utf-8")
    for index, row in enumerate(rows):
        (run_dir / "results" / f"row-{index}.json").write_text(
            json.dumps(row),
            encoding="utf-8",
        )


def _memory_eval_row(dimension: str) -> dict:
    return {
        "benchmark_id": "memory_eval_matrix",
        "dimension": dimension,
        "task_id": f"MEM-{dimension}",
        "dataset_id": "memory_eval_matrix",
        "dataset_hash": "memory-eval-unit",
        "expected_source_ids": ["source-1"],
        "retrieved_source_ids": ["source-1"],
        "safe_to_answer": dimension != "context_sufficiency_accuracy",
        "false_positive_count": 0,
        "artifact_state": "accepted",
        "claim_boundary": "release gate coverage only",
        "accepted": "yes",
        "acceptance_notes": "unit row",
    }


def _quality_row(capability: str) -> dict:
    return {
        "benchmark_id": "retrieval_quality_pack",
        "capability": capability,
        "task_id": f"RQP-{capability}",
        "dataset_id": "retrieval_quality_pack",
        "dataset_hash": "retrieval-quality-unit",
        "default_enabled": capability == "retrieval_drift_suite",
        "precision_at_k": 1.0,
        "recall_delta": 0.2,
        "false_positive_delta": 0.05,
        "fanout_cost": 1,
        "duplicate_rate": 0.0,
        "sufficiency_delta": 0.1,
        "model_size_mb": 0.0,
        "cold_start_ms": 0.0,
        "install_friction": "none",
        "claim_readiness": {"ready": True, "blocking": []},
        "accepted": "yes",
        "acceptance_notes": "unit row",
    }


def _code_memory_row(*, generated_layer_is_truth: bool = False) -> dict:
    return {
        "benchmark_id": "code_memory_federation",
        "task_id": "CMF-001",
        "dataset_id": "code_memory_federation",
        "dataset_hash": "code-memory-unit",
        "file_path": "harness_mem/file_context.py",
        "source_id": "code-file:test",
        "fingerprint": "abc123",
        "line_range": [1, 2],
        "stale_check": {"status": "current", "reason": ""},
        "current_code_symbols": ["build_file_context"],
        "generated_layer_is_truth": generated_layer_is_truth,
        "claim_boundary": "code evidence federation only",
        "accepted": "yes",
        "acceptance_notes": "unit row",
    }


def test_validate_run_accepts_memory_eval_matrix_bundle(tmp_path: Path) -> None:
    dimensions = sorted(VALIDATE_RUN.MEMORY_EVAL_DIMENSIONS)
    run_dir = tmp_path / "memory-eval"
    _write_run(run_dir, "memory_eval_matrix", [_memory_eval_row(item) for item in dimensions])

    result = VALIDATE_RUN.validate_run(run_dir)
    report = RENDER_REPORT.build_report(
        [_memory_eval_row(item) for item in dimensions],
        "memory_eval_matrix",
    )

    assert result["result_count"] == len(dimensions)
    assert "Memory Eval Matrix Report" in report
    assert "Covered dimensions: 8" in report


def test_validate_run_rejects_memory_eval_missing_dimension(tmp_path: Path) -> None:
    dimensions = sorted(VALIDATE_RUN.MEMORY_EVAL_DIMENSIONS)[:-1]
    run_dir = tmp_path / "memory-eval-missing"
    _write_run(run_dir, "memory_eval_matrix", [_memory_eval_row(item) for item in dimensions])

    with pytest.raises(SystemExit, match="memory_eval_matrix missing dimensions"):
        VALIDATE_RUN.validate_run(run_dir)


def test_validate_run_checks_retrieval_quality_drift_rule(tmp_path: Path) -> None:
    capabilities = sorted(VALIDATE_RUN.RETRIEVAL_QUALITY_CAPABILITIES)
    rows = [_quality_row(item) for item in capabilities]
    run_dir = tmp_path / "retrieval-quality"
    _write_run(run_dir, "retrieval_quality_pack", rows)

    result = VALIDATE_RUN.validate_run(run_dir)
    report = RENDER_REPORT.build_report(rows, "retrieval_quality_pack")

    assert result["result_count"] == len(capabilities)
    assert "Retrieval Quality Pack Report" in report
    assert "recall uplift greater than false-positive drift" in report


def test_validate_run_rejects_query_rewrite_false_positive_drift(tmp_path: Path) -> None:
    capabilities = sorted(VALIDATE_RUN.RETRIEVAL_QUALITY_CAPABILITIES)
    rows = [_quality_row(item) for item in capabilities]
    for row in rows:
        if row["capability"] == "query_rewriting":
            row["recall_delta"] = 0.01
            row["false_positive_delta"] = 0.05
    run_dir = tmp_path / "retrieval-quality-bad"
    _write_run(run_dir, "retrieval_quality_pack", rows)

    with pytest.raises(SystemExit, match="recall_delta > false_positive_delta"):
        VALIDATE_RUN.validate_run(run_dir)


def test_validate_run_checks_code_memory_generated_truth_boundary(tmp_path: Path) -> None:
    run_dir = tmp_path / "code-memory"
    _write_run(run_dir, "code_memory_federation", [_code_memory_row()])

    result = VALIDATE_RUN.validate_run(run_dir)
    report = RENDER_REPORT.build_report([_code_memory_row()], "code_memory_federation")

    assert result["result_count"] == 1
    assert "Code-Memory Federation Report" in report
    assert "not canonical truth" in report


def test_validate_run_rejects_generated_code_layer_as_truth(tmp_path: Path) -> None:
    run_dir = tmp_path / "code-memory-bad"
    _write_run(
        run_dir,
        "code_memory_federation",
        [_code_memory_row(generated_layer_is_truth=True)],
    )

    with pytest.raises(SystemExit, match="generated_layer_is_truth=false"):
        VALIDATE_RUN.validate_run(run_dir)
