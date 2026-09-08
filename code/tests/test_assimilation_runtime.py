"""Direct runtime proof for the current separated assimilation path."""

from harness_mem.qualification.memory_assimilation_outcome_probe import (
    run_memory_assimilation_outcome_probe,
)


def test_multi_point_assimilation_outcome_probe() -> None:
    result = run_memory_assimilation_outcome_probe()

    assert result["verified"] is True
    assert result["new_session_does_not_write_legacy_truth"] is True
    assert result["terminal_processing_material_cleaned"] is True
