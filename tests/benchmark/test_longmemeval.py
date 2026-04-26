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
    captured: dict[str, str | int] = {}

    def fake_run_benchmark(data_file: str, mode: str, limit: int, top_k: int, out_file: str) -> float:
        captured["data_file"] = data_file
        captured["mode"] = mode
        captured["limit"] = limit
        captured["top_k"] = top_k
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
            "--top-k",
            "10",
            "--out",
            str(explicit_out),
        ],
    )

    longmemeval.main()

    assert captured["out_file"] == str(explicit_out)
