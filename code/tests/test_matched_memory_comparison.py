"""The comparison fixtures preserve the complete source dialogue."""
from __future__ import annotations

import importlib.util
from pathlib import Path

from harness_mem.qualification.quality_baseline import load_baseline


SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_matched_memory_comparison.py"
spec = importlib.util.spec_from_file_location("matched_comparison", SCRIPT)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def test_role_conversion_keeps_middle_and_tail_and_original_bytes():
    baseline = load_baseline()
    source = next(row for row in baseline["sources"] if row["id"] == "F5")
    messages = mod.source_messages(source["text"])
    combined = "\n".join(body for _, body in messages)
    assert "F5-MIDDLE-ERROR" in combined
    assert "Security review remains unfinished." in combined
    assert len(messages) == 120
    rows = mod.native_records(source, Path("/fictional/lantern"), "fixed-id", 0)
    assert sum(row["type"] == "response_item" for row in rows) == 120
    assert sum(row["type"] == "turn_context" for row in rows) == 60


def test_unheaded_project_preamble_is_not_discarded():
    baseline = load_baseline()
    source = next(row for row in baseline["sources"] if row["id"] == "F10")
    assert mod.source_messages(source["text"])[0][1].startswith("Fictional project Lantern.")
