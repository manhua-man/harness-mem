from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from types import ModuleType


def _load_verifier() -> ModuleType:
    path = (
        Path(__file__).resolve().parents[1]
        / "tools"
        / "outcome-verifier"
        / "scripts"
        / "verify_outcomes.py"
    )
    spec = importlib.util.spec_from_file_location("outcome_verifier_script", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _check(command: list[str], *, expected: bool) -> dict:
    return {
        "id": "consumer_probe",
        "description": "Run the real consumer probe.",
        "evidence_tier": "direct",
        "command": command,
        "expect": {
            "exit_code": 0,
            "json": {"consumer_opened": {"equals": expected}},
        },
    }


def test_verifier_rejects_present_artifact_that_consumer_cannot_open(
    tmp_path: Path,
) -> None:
    verifier = _load_verifier()
    project = tmp_path / "project"
    config_dir = project / ".codex"
    config_dir.mkdir(parents=True)
    probe = project / "probe.py"
    probe.write_text(
        "import json\nprint(json.dumps({'artifact_exists': True, 'consumer_opened': False}))\n",
        encoding="utf-8",
    )
    config = {
        "schema_version": 1,
        "project": "fixture",
        "claims": [
            {
                "id": "export_consumable",
                "description": "The consumer opens the export.",
                "required": True,
                "checks": [_check(["{python}", "probe.py"], expected=True)],
            }
        ],
    }
    config_path = config_dir / "outcomes.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = project / "report.json"

    exit_code = verifier.main(
        ["--config", str(config_path), "--output", str(output)]
    )
    report = json.loads(output.read_text(encoding="utf-8"))

    assert exit_code == 1
    assert report["status"] == "failed"
    assert report["claims"][0]["checks"][0]["failures"] == [
        "consumer_opened: equals expected True, got False"
    ]


def test_verifier_caches_identical_read_probe_across_claims(tmp_path: Path) -> None:
    verifier = _load_verifier()
    project = tmp_path / "project"
    config_dir = project / ".codex"
    config_dir.mkdir(parents=True)
    probe = project / "probe.py"
    probe.write_text(
        """
import json
from pathlib import Path

counter = Path('counter.txt')
value = int(counter.read_text() if counter.exists() else '0') + 1
counter.write_text(str(value))
print(json.dumps({'consumer_opened': True}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    command = ["{python}", "probe.py"]
    config = {
        "schema_version": 1,
        "project": "fixture",
        "claims": [
            {
                "id": claim_id,
                "description": claim_id,
                "required": True,
                "checks": [_check(command, expected=True)],
            }
            for claim_id in ("artifact_visible", "artifact_consumable")
        ],
    }
    config_path = config_dir / "outcomes.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    report = verifier.verify(
        verifier._load_contract(config_path),
        project,
        set(),
    )

    assert report["status"] == "passed"
    assert (project / "counter.txt").read_text(encoding="utf-8") == "1"
    first, second = (
        report["claims"][index]["checks"][0] for index in range(2)
    )
    assert first["started_at"] == second["started_at"]
    assert first["completed_at"] == second["completed_at"]
    assert first["duration_seconds"] == second["duration_seconds"]


def test_verifier_records_run_and_check_timings(tmp_path: Path) -> None:
    verifier = _load_verifier()
    project = tmp_path / "project"
    project.mkdir()
    contract = {
        "schema_version": 1,
        "project": "fixture",
        "claims": [
            {
                "id": "artifact_visible",
                "required": True,
                "checks": [
                    _check(
                        [
                            "{python}",
                            "-c",
                            "import json; print(json.dumps({'consumer_opened': True}))",
                        ],
                        expected=True,
                    )
                ],
            }
        ],
    }

    report = verifier.verify(contract, project, set())
    check = report["claims"][0]["checks"][0]

    assert report["run_id"]
    assert report["generated_at"] == report["completed_at"]
    assert datetime.fromisoformat(report["started_at"]) <= datetime.fromisoformat(
        report["completed_at"]
    )
    assert report["duration_seconds"] >= 0
    assert check["run_id"] == report["run_id"]
    assert datetime.fromisoformat(check["started_at"]) <= datetime.fromisoformat(
        check["completed_at"]
    )
    assert check["duration_seconds"] >= 0


def test_verifier_keeps_selected_claim_behavior(tmp_path: Path) -> None:
    verifier = _load_verifier()
    project = tmp_path / "project"
    project.mkdir()
    passing = _check(
        [
            "{python}",
            "-c",
            "import json; print(json.dumps({'consumer_opened': True}))",
        ],
        expected=True,
    )
    contract = {
        "schema_version": 1,
        "project": "fixture",
        "claims": [
            {
                "id": claim_id,
                "description": claim_id,
                "required": True,
                "checks": [passing],
            }
            for claim_id in ("selected", "not_selected")
        ],
    }

    report = verifier.verify(contract, project, {"selected"})

    assert report["status"] == "passed"
    assert [claim["id"] for claim in report["claims"]] == ["selected"]


def test_second_process_fails_closed_without_overwriting_active_report(
    tmp_path: Path,
) -> None:
    verifier = _load_verifier()
    project = tmp_path / "project"
    config_dir = project / ".codex"
    config_dir.mkdir(parents=True)
    started = project / "started"
    release = project / "release"
    probe = project / "probe.py"
    probe.write_text(
        """
import json
import time
from pathlib import Path

Path('started').write_text('ready')
while not Path('release').exists():
    time.sleep(0.01)
print(json.dumps({'consumer_opened': True}))
""".strip()
        + "\n",
        encoding="utf-8",
    )
    config = {
        "schema_version": 1,
        "project": "fixture",
        "claims": [
            {
                "id": "artifact_visible",
                "required": True,
                "checks": [_check(["{python}", "probe.py"], expected=True)],
            }
        ],
    }
    config_path = config_dir / "outcomes.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    output = project / "report.json"
    original = '{"owner": "previous"}\n'
    output.write_text(original, encoding="utf-8")
    script = Path(verifier.__file__)

    first = subprocess.Popen(
        [
            sys.executable,
            str(script),
            "--config",
            str(config_path),
            "--output",
            str(output),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        deadline = time.monotonic() + 5
        while not started.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert started.exists(), "first verifier did not start its probe"

        second_exit = verifier.main(
            ["--config", str(config_path), "--output", str(output)]
        )

        assert second_exit == 2
        assert output.read_text(encoding="utf-8") == original
    finally:
        release.touch()
        stdout, stderr = first.communicate(timeout=5)

    assert first.returncode == 0, (stdout, stderr)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["status"] == "passed"
    assert not verifier._output_lock_path(output).exists()
    assert not list(project.glob(f".{output.name}.*.tmp"))


def test_atomic_report_publish_does_not_expose_partial_contents(
    tmp_path: Path, monkeypatch
) -> None:
    verifier = _load_verifier()
    output = tmp_path / "report.json"
    output.write_text("old report\n", encoding="utf-8")
    observed: list[str] = []
    real_replace = verifier.os.replace

    def inspect_then_replace(source: Path, destination: Path) -> None:
        observed.append(output.read_text(encoding="utf-8"))
        real_replace(source, destination)

    monkeypatch.setattr(verifier.os, "replace", inspect_then_replace)
    verifier._write_report_atomic(output, "new report\n", "run-a")

    assert observed == ["old report\n"]
    assert output.read_text(encoding="utf-8") == "new report\n"
    assert not list(tmp_path.glob(f".{output.name}.*.tmp"))
