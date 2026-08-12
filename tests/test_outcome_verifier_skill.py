from __future__ import annotations

import importlib.util
import json
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
