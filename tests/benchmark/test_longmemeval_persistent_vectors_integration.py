from __future__ import annotations

import os
import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("Stemmer")

from harness_mem.tools import longmemeval
from harness_mem.tools.embedding_shootout import load_baseline

pytestmark = [pytest.mark.benchmark, pytest.mark.integration]


def _dataset_paths() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.environ.get("LONGMEMEVAL_DATASET")
    if env_path:
        candidates.append(Path(env_path))
    temp_dir = Path(tempfile.gettempdir())
    candidates.extend(
        [
            temp_dir / "longmemeval_s_cleaned.json",
            temp_dir / "longmemeval-data" / "longmemeval_s_cleaned.json",
        ]
    )
    return candidates


def _find_dataset() -> Path | None:
    for candidate in _dataset_paths():
        if candidate and candidate.exists():
            return candidate
    return None


def test_persistent_vectors_longmemeval_smoke(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    if os.environ.get("LONGMEMEVAL_INTEGRATION") != "1":
        pytest.skip("Set LONGMEMEVAL_INTEGRATION=1 to run the full LongMemEval integration check")

    dataset = _find_dataset()
    if dataset is None:
        pytest.skip("LongMemEval dataset not available locally")

    try:
        from sentence_transformers import SentenceTransformer  # noqa: F401
    except Exception:
        pytest.skip("sentence-transformers not installed")

    output_path = tmp_path / "v162-longmemeval-smoke.json"
    baseline_path = Path(__file__).resolve().parents[2] / "docs" / "benchmark" / "v160-baseline.md"

    result = longmemeval.run_benchmark(
        str(dataset),
        mode="hybrid",
        limit=0,
        top_k=5,
        out_file=str(output_path),
        use_real_hybrid=True,
    )

    assert result >= 0.0
    assert output_path.exists()
    payload = output_path.read_text(encoding="utf-8")
    assert "avg_recall" in payload
    assert baseline_path.exists()

    report = json.loads(payload)
    baseline = load_baseline(baseline_path)
    baseline_map = {
        "knowledge-update": baseline.knowledge_update,
        "multi-session": baseline.multi_session,
        "single-session-assistant": baseline.single_session_assistant,
        "single-session-preference": baseline.single_session_preference,
        "single-session-user": baseline.single_session_user,
        "temporal-reasoning": baseline.temporal_reasoning,
    }
    per_type = report["per_type"]
    non_regressing = [
        qtype
        for qtype, baseline_score in baseline_map.items()
        if per_type.get(qtype, 0.0) >= baseline_score
    ]
    assert len(non_regressing) >= 3, (
        f"Expected at least 3 dimensions to meet or exceed baseline; "
        f"got {non_regressing} from {per_type}"
    )
