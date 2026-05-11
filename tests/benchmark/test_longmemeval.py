from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from harness_mem.tools import longmemeval

pytestmark = pytest.mark.benchmark


def test_default_output_path_targets_benchmarks_results():
    path = longmemeval.default_output_path(
        mode="raw",
        top_k=5,
        now=datetime(2026, 4, 23, 6, 14),
    )
    expected = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "results"
        / "results_harness_top5_20260423_0614.json"
    )
    assert path == expected


def test_main_preserves_explicit_out_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    explicit_out = tmp_path / "custom" / "result.json"
    captured: dict[str, str | int | bool] = {}

    def fake_run_benchmark(
        data_file: str,
        mode: str,
        limit: int,
        top_k: int,
        out_file: str,
        use_real_hybrid: bool = False,
        temporal_bias: bool = False,
    ) -> float:
        captured["data_file"] = data_file
        captured["mode"] = mode
        captured["limit"] = limit
        captured["top_k"] = top_k
        captured["out_file"] = out_file
        captured["use_real_hybrid"] = use_real_hybrid
        captured["temporal_bias"] = temporal_bias
        return 1.0

    monkeypatch.setattr(longmemeval, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(
        "sys.argv",
        [
            "python",
            "dataset.json",
            "--mode",
            "hybrid",
            "--top-k",
            "10",
            "--out",
            str(explicit_out),
        ],
    )

    longmemeval.main()

    assert captured["out_file"] == str(explicit_out)
    assert captured["use_real_hybrid"] is False
    assert captured["temporal_bias"] is False


def test_main_passes_temporal_bias_to_real_hybrid(monkeypatch: pytest.MonkeyPatch):
    captured: dict[str, str | int | bool] = {}

    def fake_run_benchmark(
        data_file: str,
        mode: str,
        limit: int,
        top_k: int,
        out_file: str,
        use_real_hybrid: bool = False,
        temporal_bias: bool = False,
    ) -> float:
        captured["mode"] = mode
        captured["use_real_hybrid"] = use_real_hybrid
        captured["temporal_bias"] = temporal_bias
        captured["out_file"] = out_file
        return 1.0

    monkeypatch.setattr(longmemeval, "run_benchmark", fake_run_benchmark)
    monkeypatch.setattr(
        "sys.argv",
        [
            "python",
            "dataset.json",
            "--mode",
            "hybrid",
            "--use-real-hybrid",
            "--temporal-bias",
        ],
    )

    longmemeval.main()

    assert captured["mode"] == "hybrid"
    assert captured["use_real_hybrid"] is True
    assert captured["temporal_bias"] is True
    assert "_temporal_" in str(captured["out_file"])


def test_main_rejects_temporal_bias_without_real_hybrid(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "sys.argv",
        ["python", "dataset.json", "--mode", "hybrid", "--temporal-bias"],
    )

    with pytest.raises(SystemExit):
        longmemeval.main()


def test_temporal_bias_comparison_writes_delta(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
):
    calls: list[dict[str, bool]] = []

    def fake_run_benchmark(
        data_file: str,
        mode: str,
        limit: int,
        top_k: int,
        out_file: str,
        use_real_hybrid: bool = False,
        temporal_bias: bool = False,
    ) -> float:
        calls.append({
            "use_real_hybrid": use_real_hybrid,
            "temporal_bias": temporal_bias,
        })
        payload = {
            "mode": mode,
            "use_real_hybrid": use_real_hybrid,
            "temporal_bias": temporal_bias,
            "top_k": top_k,
            "total_questions": 2,
            "avg_recall": 0.75 if temporal_bias else 0.5,
            "per_type": {
                "temporal-reasoning": 1.0 if temporal_bias else 0.5,
                "single-session-user": 0.5,
            },
            "results": [],
        }
        Path(out_file).write_text(longmemeval.json.dumps(payload), encoding="utf-8")
        return float(payload["avg_recall"])

    monkeypatch.setattr(longmemeval, "run_benchmark", fake_run_benchmark)
    out_file = tmp_path / "comparison.json"

    comparison = longmemeval.run_temporal_bias_comparison(
        "dataset.json",
        limit=2,
        top_k=5,
        out_file=str(out_file),
    )

    assert calls == [
        {"use_real_hybrid": True, "temporal_bias": False},
        {"use_real_hybrid": True, "temporal_bias": True},
    ]
    assert comparison["delta"]["avg_recall"] == 0.25
    assert comparison["delta"]["per_type"]["temporal-reasoning"] == 0.5
    assert comparison["gate"]["decision"] == "candidate-for-dogfood"
    assert out_file.exists()


def test_session_doc_includes_assistant_turns_for_assistant_recall_query():
    session = [
        {"role": "user", "content": "I asked for alternatives."},
        {"role": "assistant", "content": "Try option alpha and option beta."},
    ]

    assistant_doc = longmemeval._session_doc_for_query(
        session,
        "Can you remind me what you suggested in our previous chat?",
    )
    user_doc = longmemeval._session_doc_for_query(
        session,
        "What did I ask about?",
    )

    assert "option alpha" in assistant_doc
    assert "assistant:" in assistant_doc
    assert "option alpha" not in user_doc
