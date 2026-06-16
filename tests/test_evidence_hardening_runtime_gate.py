from __future__ import annotations

import json
from pathlib import Path
import subprocess

from harness_mem.benchmark_matrix import benchmark_matrix_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _write_repo_suite(target: Path) -> None:
    suite = json.loads(
        (REPO_ROOT / "benchmark-suite" / "suite.json").read_text(encoding="utf-8")
    )
    target.mkdir(parents=True, exist_ok=True)
    (target / "suite.json").write_text(
        json.dumps(suite, indent=2),
        encoding="utf-8",
    )


def _write_run(
    suite_root: Path,
    run_id: str,
    benchmark_id: str,
    rows: list[dict],
    *,
    artifact_state: str | None = None,
    release_snapshot: bool | None = None,
    accepted: bool | None = True,
) -> None:
    run_dir = suite_root / "artifacts" / run_id
    (run_dir / "results").mkdir(parents=True, exist_ok=True)
    manifest = {
        "run_id": run_id,
        "benchmark_id": benchmark_id,
        "accepted": accepted,
    }
    if artifact_state is not None:
        manifest["artifact_state"] = artifact_state
    if release_snapshot is not None:
        manifest["release_snapshot"] = release_snapshot
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    for index, row in enumerate(rows, 1):
        (run_dir / "results" / f"result-{index}.json").write_text(
            json.dumps(row),
            encoding="utf-8",
        )


def _memory_shortcut_rows(*, include_one_negative_long_source_pair: bool = False) -> list[dict]:
    rows: list[dict] = []
    for index in range(1, 9):
        task_id = f"LS{index}"
        enabled_total = 80
        disabled_total = 120
        if include_one_negative_long_source_pair and index == 6:
            enabled_total = 140
            disabled_total = 120
        rows.append(
            {
                "task_id": task_id,
                "task_type": "long_source_recovery",
                "condition": "enabled",
                "accepted": "yes",
                "source_read_count": 1,
                "memory_calls": ["search_memory"],
                "repo_calls": ["read_text_file"],
                "token_usage": {
                    "available": True,
                    "source": "codex-session-observer",
                    "total": enabled_total,
                },
            }
        )
        rows.append(
            {
                "task_id": task_id,
                "task_type": "long_source_recovery",
                "condition": "disabled",
                "accepted": "yes",
                "source_read_count": 3,
                "memory_calls": [],
                "repo_calls": ["read_text_file", "read_text_file", "read_text_file"],
                "token_usage": {
                    "available": True,
                    "source": "codex-session-observer",
                    "total": disabled_total,
                },
            }
        )
    for index in range(1, 3):
        task_id = f"NC{index}"
        rows.append(
            {
                "task_id": task_id,
                "task_type": "negative_control",
                "condition": "enabled",
                "accepted": "yes",
                "source_read_count": 1,
                "memory_calls": [],
                "repo_calls": ["read_text_file"],
                "token_usage": {
                    "available": True,
                    "source": "codex-session-observer",
                    "total": 50,
                },
            }
        )
        rows.append(
            {
                "task_id": task_id,
                "task_type": "negative_control",
                "condition": "disabled",
                "accepted": "yes",
                "source_read_count": 1,
                "memory_calls": [],
                "repo_calls": ["read_text_file"],
                "token_usage": {
                    "available": True,
                    "source": "codex-session-observer",
                    "total": 50,
                },
            }
        )
    return rows


def _functional_token_rows() -> list[dict]:
    return [
        {
            "scenario_id": "FT1",
            "accepted": "yes",
            "fixture_only": True,
            "saving_ratio": 0.30,
            "minimum_saving_ratio": 0.20,
            "token_delta": 120,
        },
        {
            "scenario_id": "FT2",
            "accepted": "yes",
            "fixture_only": True,
            "saving_ratio": 0.24,
            "minimum_saving_ratio": 0.20,
            "token_delta": 80,
        },
    ]


def _storage_rows(benchmark_id: str) -> list[dict]:
    rows: list[dict] = []
    for profile, entry_count in [("10k", 10_000), ("100k", 100_000), ("1m", 1_000_000)]:
        row = {
            "benchmark_id": benchmark_id,
            "dataset_id": f"{benchmark_id}-{profile}",
            "corpus_profile": profile,
            "entry_count": entry_count,
            "accepted": "yes",
        }
        if benchmark_id == "migration_roundtrip":
            row.update(
                {
                    "apply_checksum_match": True,
                    "rollback_checksum_match": True,
                }
            )
        if benchmark_id == "canonical_store_runtime_baseline":
            row.update({"checksum_match": True})
        rows.append(row)
    return rows


def _storage_rows_for_profile(benchmark_id: str, profile: str) -> list[dict]:
    entry_counts = {"10k": 10_000, "100k": 100_000, "1m": 1_000_000}
    row = {
        "benchmark_id": benchmark_id,
        "dataset_id": f"{benchmark_id}-{profile}",
        "corpus_profile": profile,
        "entry_count": entry_counts[profile],
        "accepted": "yes",
    }
    if benchmark_id == "migration_roundtrip":
        row.update(
            {
                "apply_checksum_match": True,
                "rollback_checksum_match": True,
            }
        )
    if benchmark_id == "canonical_store_runtime_baseline":
        row.update({"checksum_match": True})
    return [row]


def _index_fabric_rows() -> list[dict]:
    return [
        {
            "operation": "exact_search",
            "accepted": "yes",
            "first_lazy_load": True,
            "warm_run": False,
            "manifest_commit": True,
            "search_backend_conformance": True,
            "source_fingerprint_drift_detected": True,
            "interrupted_generation_visible": False,
            "fallback_reason": "none",
        },
        {
            "operation": "word_search",
            "accepted": "yes",
            "first_lazy_load": False,
            "warm_run": True,
            "manifest_commit": True,
            "search_backend_conformance": True,
            "source_fingerprint_drift_detected": True,
            "interrupted_generation_visible": False,
            "fallback_reason": "none",
        },
        {
            "operation": "trigram_search",
            "accepted": "yes",
            "first_lazy_load": False,
            "warm_run": True,
            "manifest_commit": True,
            "search_backend_conformance": True,
            "source_fingerprint_drift_detected": True,
            "interrupted_generation_visible": False,
            "fallback_reason": "none",
        },
        {
            "operation": "graph_search",
            "accepted": "yes",
            "first_lazy_load": False,
            "warm_run": True,
            "manifest_commit": True,
            "search_backend_conformance": True,
            "source_fingerprint_drift_detected": True,
            "interrupted_generation_visible": False,
            "fallback_reason": "none",
        },
    ]


def _rust_rows() -> list[dict]:
    return [
        {
            "operation": "scan_jsonl",
            "accepted": "yes",
            "native_available": True,
            "rust_mode": "rust",
        },
        {
            "operation": "bulk_index_rows",
            "accepted": "yes",
            "native_available": True,
            "rust_mode": "rust",
        },
        {
            "operation": "reciprocal_rank_fusion",
            "accepted": "yes",
            "native_available": True,
            "rust_mode": "rust",
        },
        {
            "operation": "rank_candidates",
            "accepted": "yes",
            "native_available": True,
            "rust_mode": "rust",
        },
        {
            "operation": "tokenize",
            "accepted": "yes",
            "native_available": True,
            "rust_mode": "rust",
        },
    ]


def _seed_ready_suite(suite_root: Path) -> None:
    _write_repo_suite(suite_root)
    _write_run(
        suite_root,
        "2026-06-20-memory-shortcut",
        "memory_shortcut_vs_source_recovery",
        _memory_shortcut_rows(),
    )
    _write_run(
        suite_root,
        "2026-06-20-functional-token",
        "functional_token_economics",
        _functional_token_rows(),
    )
    _write_run(
        suite_root,
        "2026-06-20-storage-scale",
        "storage_v2_baseline",
        _storage_rows("storage_v2_baseline"),
    )
    _write_run(
        suite_root,
        "2026-06-20-migration-scale",
        "migration_roundtrip",
        _storage_rows("migration_roundtrip"),
    )
    _write_run(
        suite_root,
        "2026-06-20-canonical-scale",
        "canonical_store_runtime_baseline",
        _storage_rows("canonical_store_runtime_baseline"),
    )
    _write_run(
        suite_root,
        "2026-06-20-index-runtime",
        "index_fabric_runtime_conformance",
        _index_fabric_rows(),
    )
    _write_run(
        suite_root,
        "2026-06-20-rust-native",
        "rust_core_hot_path",
        _rust_rows(),
    )


def test_evidence_hardening_track_stays_blocked_without_future_artifacts(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _write_repo_suite(suite_root)

    report = benchmark_matrix_report(suite_root)

    track = report["evidence_hardening_track"]
    assert track["cost_token_evidence"]["passed"] is False
    assert "memory_shortcut_vs_source_recovery/missing" in track["cost_token_evidence"][
        "blocking"
    ]
    assert track["storage_v2_scale_evidence"]["passed"] is False
    assert track["index_fabric_runtime_evidence"]["passed"] is False
    assert track["rust_native_hot_path_evidence"]["passed"] is False
    assert report["default_change_decision_gate"]["ready"] is False
    assert "cost_token_evidence" in report["default_change_decision_gate"]["blocking"]


def test_evidence_hardening_track_and_default_change_gate_can_turn_ready(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _seed_ready_suite(suite_root)

    report = benchmark_matrix_report(suite_root)

    track = report["evidence_hardening_track"]
    assert track["cost_token_evidence"]["passed"] is True
    assert track["cost_token_evidence"]["memory_shortcut_ready"] is True
    assert track["cost_token_evidence"]["functional_token_economics_ready"] is True
    assert track["storage_v2_scale_evidence"]["passed"] is True
    assert track["storage_v2_scale_evidence"]["baseline_profiles"] == [
        "10k",
        "100k",
        "1m",
    ]
    assert track["index_fabric_runtime_evidence"]["passed"] is True
    assert track["rust_native_hot_path_evidence"]["passed"] is True
    assert report["release_evidence_pack"]["passed"] is True
    assert report["default_change_decision_gate"]["ready"] is True


def test_evidence_hardening_cost_gate_follows_documented_median_rule(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _write_repo_suite(suite_root)
    _write_run(
        suite_root,
        "2026-06-20-memory-shortcut",
        "memory_shortcut_vs_source_recovery",
        _memory_shortcut_rows(include_one_negative_long_source_pair=True),
    )
    _write_run(
        suite_root,
        "2026-06-20-functional-token",
        "functional_token_economics",
        _functional_token_rows(),
    )

    report = benchmark_matrix_report(suite_root)

    cost_gate = report["evidence_hardening_track"]["cost_token_evidence"]
    assert cost_gate["long_source_both_passed"] == 8
    assert cost_gate["median_token_saving_ratio"] == "0.333"
    assert cost_gate["passed"] is True
    assert cost_gate["memory_shortcut_ready"] is True


def test_storage_scale_evidence_aggregates_profiles_across_multiple_runs(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _write_repo_suite(suite_root)
    for profile in ["10k", "100k", "1m"]:
        _write_run(
            suite_root,
            f"2026-06-20-storage-{profile}",
            "storage_v2_baseline",
            _storage_rows_for_profile("storage_v2_baseline", profile),
        )
        _write_run(
            suite_root,
            f"2026-06-20-migration-{profile}",
            "migration_roundtrip",
            _storage_rows_for_profile("migration_roundtrip", profile),
        )
        _write_run(
            suite_root,
            f"2026-06-20-canonical-{profile}",
            "canonical_store_runtime_baseline",
            _storage_rows_for_profile("canonical_store_runtime_baseline", profile),
        )

    report = benchmark_matrix_report(suite_root)

    storage_gate = report["evidence_hardening_track"]["storage_v2_scale_evidence"]
    assert storage_gate["passed"] is True
    assert storage_gate["baseline_profiles"] == ["10k", "100k", "1m"]
    assert storage_gate["migration_profiles"] == ["10k", "100k", "1m"]
    assert storage_gate["canonical_profiles"] == ["10k", "100k", "1m"]


def test_evidence_hardening_ignores_newer_diagnostic_memory_shortcut_runs(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _write_repo_suite(suite_root)
    _write_run(
        suite_root,
        "2026-06-20-memory-shortcut-release",
        "memory_shortcut_vs_source_recovery",
        _memory_shortcut_rows(),
        artifact_state="accepted",
        release_snapshot=True,
        accepted=True,
    )
    _write_run(
        suite_root,
        "2026-06-21-memory-shortcut-diagnostic",
        "memory_shortcut_vs_source_recovery",
        _memory_shortcut_rows()[-2:],
        artifact_state="diagnostic",
        release_snapshot=False,
        accepted=None,
    )
    _write_run(
        suite_root,
        "2026-06-20-functional-token",
        "functional_token_economics",
        _functional_token_rows(),
        artifact_state="accepted",
        release_snapshot=True,
        accepted=True,
    )

    report = benchmark_matrix_report(suite_root)

    cost_gate = report["evidence_hardening_track"]["cost_token_evidence"]
    assert cost_gate["passed"] is True
    assert cost_gate["long_source_both_passed"] == 8
    assert cost_gate["negative_control_pairs"] == 2


def test_release_snapshot_carries_evidence_hardening_track(
    tmp_path: Path,
) -> None:
    suite_root = tmp_path / "benchmark-suite"
    _seed_ready_suite(suite_root)
    output = suite_root / "release-snapshot.json"

    result = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/build_release_snapshot.py",
            "--suite-root",
            str(suite_root),
            "--output",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["evidence_hardening_track"]["cost_token_evidence"]["passed"] is True
    assert payload["default_change_decision_gate"]["ready"] is True

    validate = subprocess.run(
        [
            "python",
            "benchmark-suite/tools/validate_release_snapshot.py",
            "--path",
            str(output),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert validate.returncode == 0, validate.stderr
