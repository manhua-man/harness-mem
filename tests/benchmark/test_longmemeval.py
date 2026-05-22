from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("Stemmer")

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
    ) -> float:
        captured["data_file"] = data_file
        captured["mode"] = mode
        captured["limit"] = limit
        captured["top_k"] = top_k
        captured["out_file"] = out_file
        captured["use_real_hybrid"] = use_real_hybrid
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
