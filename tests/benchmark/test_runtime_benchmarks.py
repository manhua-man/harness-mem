from __future__ import annotations

import pytest

from harness_mem.benchmarks import benchmark_daily_wake_temporal_safety
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.helpers import run


pytestmark = pytest.mark.benchmark


def test_daily_wake_temporal_safety_retains_old_critical_memory(tmp_path):
    backend = LocalMemoryBackend(tmp_path)
    run(backend.init())
    try:
        result = run(
            benchmark_daily_wake_temporal_safety(
                backend,
                project_name="demo",
                limit=5,
            )
        )
    finally:
        run(backend.close())

    assert result["operation"] == "daily-wake-temporal-safety"
    assert result["expected_critical_count"] == 1
    assert result["critical_retained"] is True
    assert result["critical_recall"] == 1.0
    assert result["gate"] == "pass"
    assert result["default_temporal_bias_candidate"] is True
    assert len(result["selected_ids"]) == 5
