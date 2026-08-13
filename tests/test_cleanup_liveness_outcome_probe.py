from harness_mem.qualification.cleanup_liveness_outcome_probe import (
    run_cleanup_liveness_probe,
)


def test_cleanup_liveness_outcome_probe() -> None:
    result = run_cleanup_liveness_probe()
    assert result["verified"] is True, result
