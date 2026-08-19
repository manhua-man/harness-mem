import json
from pathlib import Path
import subprocess
import sys

from harness_mem.qualification.clean_retrieval_outcome_probe import (
    run_clean_retrieval_outcome_probe,
)


def test_clean_retrieval_outcome_probe() -> None:
    assert run_clean_retrieval_outcome_probe()["verified"] is True


def test_clean_retrieval_outcome_probe_emits_json_on_stdout() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "harness_mem.qualification.clean_retrieval_outcome_probe"],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        check=False,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["verified"] is True
    assert result.stderr == ""
