"""rank_candidates native vs Python fallback parity."""

from __future__ import annotations

import pytest

from harness_mem import rust_core
from harness_mem.rust_core import rank_candidates, rust_core_status


def _representative_rows() -> list[dict]:
    return [
        {
            "id": "a",
            "tokens": ["storage", "v2"],
            "confidence": 0.8,
            "truth_status": "user_confirmed",
            "project_id": "demo",
        },
        {
            "id": "b",
            "tokens": ["storage"],
            "confidence": 0.8,
            "truth_status": "pending",
            "project_id": "demo",
        },
        {
            "id": "c",
            "tokens": ["v2", "token"],
            "confidence": 0.55,
            "truth_status": "provisional",
            "project_id": "other",
        },
        {
            "id": "d",
            "tokens": ["storage", "v2", "extra"],
            "confidence": 0.9,
            "truth_status": "auto_confirmed",
            "project_id": "demo",
            "source_id": "demo",
        },
    ]


def test_rank_candidates_fallback_is_deterministic() -> None:
    rows = _representative_rows()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(rust_core, "_native", lambda: None)
    try:
        first = rank_candidates(rows, query="storage v2 token")
        second = rank_candidates(rows, query="storage v2 token")
    finally:
        monkeypatch.undo()
    assert first == second
    assert len(first) == len(rows)


def test_rank_candidates_native_matches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    if not rust_core_status().available:
        pytest.skip("harness_mem_core_rs native extension not installed")

    rows = _representative_rows()
    query = "storage v2 token"
    native_result = rank_candidates(rows, query=query)

    monkeypatch.setattr(rust_core, "_native", lambda: None)
    fallback_result = rank_candidates(rows, query=query)

    assert native_result == fallback_result