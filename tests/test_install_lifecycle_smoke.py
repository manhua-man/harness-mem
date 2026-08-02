from __future__ import annotations

import json
from pathlib import Path

import harness_mem
import pytest
from scripts import smoke_install_lifecycle as smoke


def test_install_lifecycle_smoke_exercises_recovery_and_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    state_dir = tmp_path / "upgrade state" / "项目"

    prepared = smoke.prepare_upgrade_state(state_dir)
    verified = smoke.verify_upgrade_state(state_dir)

    assert prepared["canonical_seeded"] is True
    assert prepared["legacy_seeded"] is True
    assert verified["success"] is True
    assert verified["legacy_restore"] == {
        "canonical_preserved": True,
        "legacy_restored": True,
        "fault_injection_observed": True,
        "rollback_preserved_live_store": True,
        "retry_activated": True,
        "backup_verified": True,
        "checksum_relation": "canonical_superset_expected",
    }
    assert verified["cleanup_retry"]["partial_failure_retried"] is True
    assert verified["cleanup_retry"]["native_source_deleted"] is True
    assert verified["cleanup_retry"]["stored_raw_deleted"] is True
    assert verified["cleanup_retry"]["content_free_receipt_verified"] is True
    report = json.dumps(verified, sort_keys=True)
    assert smoke._CANONICAL_BODY not in report
    assert smoke._LEGACY_BODY not in report
    assert smoke._CLEANUP_BODY not in report
    assert smoke._CLEANUP_SESSION_ID not in report
    assert str(state_dir) not in report


def test_install_lifecycle_cli_checks_installed_version(
    tmp_path: Path,
    capsys,
) -> None:
    exit_code = smoke.main(
        [
            "prepare-upgrade",
            "--expected-version",
            harness_mem.__version__,
            "--state-dir",
            str(tmp_path / "state"),
        ]
    )

    assert exit_code == 0
    report = json.loads(capsys.readouterr().out)
    assert report["installed_version"] == harness_mem.__version__
    assert report["phase"] == "prepared"
    assert smoke._CANONICAL_BODY not in json.dumps(report)


def test_install_lifecycle_can_reject_checkout_source() -> None:
    with pytest.raises(RuntimeError, match="checkout source"):
        smoke._require_installed_wheel()


def test_release_workflow_gates_host_replay_and_upgrade_lifecycle() -> None:
    workflow = Path(".github/workflows/release-wheels.yml").read_text(
        encoding="utf-8"
    )

    assert (
        "python scripts/smoke_host_replay.py --require-installed-wheel" in workflow
    )
    assert "windows-upgrade-lifecycle-smoke" in workflow
    assert "smoke_install_lifecycle.py prepare-upgrade" in workflow
    assert "smoke_install_lifecycle.py verify-upgrade" in workflow
    assert workflow.count("--require-installed-wheel") == 3
    assert "publish-github-release:" in workflow
    assert "windows-upgrade-lifecycle-smoke" in workflow.split(
        "publish-github-release:", maxsplit=1
    )[1]
