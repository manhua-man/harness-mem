"""Strict synthetic tests, not a comparison with any executed upstream product."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys

import pytest

from harness_mem.qualification.quality_baseline import (
    FIXTURE_PATH,
    compare_results,
    fingerprint,
    load_baseline,
    main,
    read_json,
    result_template,
    score_result,
)


@pytest.fixture
def baseline() -> dict:
    return load_baseline()


def _output(point: dict, *, kind: str | None = None) -> dict:
    return {"id": point["id"], "kind": kind or point["outcome"],
            "title": point["title"], "statement": point["statement"],
            "evidence": [{k: ref[k] for k in ("source_id", "start", "end", "quote")}
                         for ref in point["evidence"]]}


def _result(baseline: dict, name: str = "offline-fixture-a") -> dict:
    result = result_template(baseline)
    result.pop("contract")
    result.update(product={"name": name, "version": "fixture-v1", "revision": "fixture-revision-1"},
                  run_kind="synthetic_fixture",
                  coverage=[{"source_id": s["id"], "start": 0, "end": len(s["text"])}
                            for s in baseline["sources"]],
                  outputs=[_output(p) for p in baseline["points"]
                           if p["outcome"] in {"memory", "handoff"}])
    return result


def _review(result: dict) -> None:
    result["human_review"] = {
        "reviewed_by": "synthetic-test-reviewer", "confirmed": True,
        "mappings": [{"output_id": row["id"], "point_ids": [row["id"]],
                      "verdict": "matches", "rationale": "Reviewed against the complete fictional source."}
                     for row in result["outputs"]],
    }


def test_frozen_corpus_reuses_catalog_and_covers_independent_points(baseline: dict) -> None:
    assert load_baseline() == baseline
    assert len(baseline["corpus_sha256"]) == 64
    assert {s["catalog_id"] for s in baseline["sources"] if "catalog_id" in s} == {"F1", "F2", "F3", "F5"}
    long_source = next(s for s in baseline["sources"] if s["id"] == "F5")
    assert "## Turn 120" in long_source["text"]
    score = score_result(baseline, _result(baseline))
    assert score["quality_status"] == "passed"
    assert score["memory_recall"] == {"verified": 7, "expected": 7}
    assert score["handoffs"] == {"verified": 3, "expected": 3, "missed_points": []}
    assert all(v is None for v in score["measurements"].values())
    assert score["user_operations_status"] == "unknown"
    assert score["recovery_status"] == "not_automatically_verified"


def test_catalog_drift_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harness_mem.qualification.quality_baseline.fixture",
                        lambda _: {"transcript": "changed"})
    with pytest.raises(ValueError, match="frozen source drift"):
        load_baseline()


def test_repeated_point_can_use_either_frozen_supporting_session(baseline: dict) -> None:
    result = _result(baseline)
    performance = baseline["points"][0]
    result["outputs"][0]["evidence"] = deepcopy(performance["alternative_evidence"][0])
    assert score_result(baseline, result)["quality_status"] == "passed"


@pytest.mark.parametrize("background", [True, None, 0])
def test_manual_baseline_requires_background_disabled(baseline: dict, background: object) -> None:
    result = _result(baseline)
    result["configuration"]["background_enabled"] = background
    with pytest.raises(ValueError, match="background_enabled=false"):
        score_result(baseline, result)


def test_missing_points_and_handoff_are_not_pass(baseline: dict) -> None:
    result = _result(baseline)
    result["outputs"] = [r for r in result["outputs"] if r["id"] not in {"compact", "security"}]
    score = score_result(baseline, result)
    assert score["quality_status"] == "failed"
    assert score["missed_points"] == ["compact"]
    assert score["handoffs"]["missed_points"] == ["security"]


@pytest.mark.parametrize("point_id", ["greeting", "obsolete", "old-sync", "migration", "list-now", "conflict", "security"])
def test_forbidden_or_unfinished_content_written_as_memory_fails(baseline: dict, point_id: str) -> None:
    result = _result(baseline)
    point = next(p for p in baseline["points"] if p["id"] == point_id)
    row = _output(point, kind="memory")
    row["id"] += "-bad-write"
    result["outputs"].append(row)
    score = score_result(baseline, result)
    assert score["quality_status"] == "failed"
    assert score["incorrect_writes"] == [row["id"]]


def test_duplicate_and_paraphrased_duplicate_are_reported(baseline: dict) -> None:
    result = _result(baseline)
    duplicate = deepcopy(result["outputs"][0])
    duplicate["id"] = "duplicate"
    duplicate["statement"] = "Keep quality while reducing latency and tokens."
    result["outputs"].append(duplicate)
    _review(result)
    result["human_review"]["mappings"][-1]["point_ids"] = ["performance"]
    score = score_result(baseline, result)
    assert score["quality_status"] == "failed"
    assert ["performance", "duplicate"] in score["duplicate_output_groups"]


def test_keywords_and_bare_point_ids_do_not_establish_semantics(baseline: dict) -> None:
    result = _result(baseline)
    result["outputs"][0]["statement"] = "time token quality"
    result["outputs"][0]["point_ids"] = ["performance"]
    score = score_result(baseline, result)
    assert score["quality_status"] != "passed"
    assert score["unverified_outputs"] == ["performance"]
    assert score["missed_points"] == ["performance"]
    _review(result)
    result["outputs"][0]["statement"] = "Reduce latency and tokens, maintaining quality."
    assert score_result(baseline, result)["quality_status"] == "passed"


@pytest.mark.parametrize("mutation", ["missing", "extra", "duplicate", "unknown_point", "unconfirmed", "empty_reason"])
def test_human_mapping_integrity_is_strict(baseline: dict, mutation: str) -> None:
    result = _result(baseline)
    _review(result)
    review = result["human_review"]
    if mutation == "missing":
        review["mappings"].pop()
    elif mutation == "extra":
        extra = deepcopy(review["mappings"][0])
        extra["output_id"] = "absent-output"
        review["mappings"].append(extra)
    elif mutation == "duplicate":
        review["mappings"].append(deepcopy(review["mappings"][0]))
    elif mutation == "unknown_point":
        review["mappings"][0]["point_ids"] = ["invented"]
    elif mutation == "unconfirmed":
        review["confirmed"] = False
    else:
        review["mappings"][0]["rationale"] = ""
    with pytest.raises(ValueError):
        score_result(baseline, result)


@pytest.mark.parametrize("mutation", ["empty", "quote", "offset", "other_point", "bool_offset"])
def test_exact_wording_still_requires_matching_real_source_span(baseline: dict, mutation: str) -> None:
    result = _result(baseline)
    row = result["outputs"][0]
    if mutation == "empty":
        row["evidence"] = []
    elif mutation == "quote":
        row["evidence"][0]["quote"] = "fabricated"
    elif mutation == "offset":
        row["evidence"][0]["start"] += 1
    elif mutation == "bool_offset":
        row["evidence"][0]["start"] = True
    else:
        row["evidence"] = deepcopy(result["outputs"][1]["evidence"])
    score = score_result(baseline, result)
    assert score["quality_status"] != "passed"
    assert score["unverified_outputs"] == ["performance"]
    assert score["output_checks"][0]["evidence_errors"]


def test_overbroad_mapping_does_not_count_as_two_independent_memories(baseline: dict) -> None:
    result = _result(baseline)
    first, second = result["outputs"][:2]
    first["statement"] += " " + second["statement"]
    first["evidence"] += second["evidence"]
    result["outputs"].pop(1)
    _review(result)
    result["human_review"]["mappings"][0]["point_ids"] = ["performance", "compact"]
    score = score_result(baseline, result)
    assert score["overbroad_outputs"] == ["performance"]
    assert score["missed_points"] == ["performance", "compact"]


@pytest.mark.parametrize("mutation", ["source_hash", "corpus_hash", "version", "coverage", "tail", "revision", "unrun"])
def test_pins_and_full_source_coverage_are_required(baseline: dict, mutation: str) -> None:
    result = _result(baseline)
    if mutation == "source_hash":
        result["source_hashes"]["F1"] = "changed"
    elif mutation == "corpus_hash":
        result["corpus_sha256"] = "changed"
    elif mutation == "version":
        result["corpus_version"] = "other"
    elif mutation == "coverage":
        result["coverage"].pop()
    elif mutation == "tail":
        result["coverage"][3]["end"] -= 1
    elif mutation == "revision":
        result["product"]["revision"] = ""
    else:
        result["run_kind"] = "unrun"
    with pytest.raises(ValueError):
        score_result(baseline, result)


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan")])
def test_measurements_cannot_fabricate_usage(baseline: dict, value: object) -> None:
    result = _result(baseline)
    result["measurements"]["input_tokens"] = value
    result["measurement_evidence"]["input_tokens"] = "fictional fixture receipt"
    with pytest.raises(ValueError, match="invalid measured value"):
        score_result(baseline, result)


def test_known_measurement_requires_evidence_and_config_diff_is_visible(baseline: dict) -> None:
    left, right = _result(baseline), _result(baseline, "offline-fixture-b")
    right["configuration"]["model"] = "fictional-other-model"
    left["measurements"]["necessary_user_operations"] = 2
    with pytest.raises(ValueError, match="measurement evidence"):
        compare_results(baseline, left, right)
    left["measurement_evidence"]["necessary_user_operations"] = "synthetic operator log"
    report = compare_results(baseline, left, right)
    assert report["same_configuration"] is False
    assert report["real_upstream_comparison_verified"] is False
    assert report["products"][0]["measurements"]["billed_cost"] is None
    assert report["products"][0]["configuration_sha256"] == fingerprint(left["configuration"])


def test_cli_exports_unrun_contract_and_scores_two_json_files(baseline: dict, tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    assert main(["--corpus"]) == 0
    exported = json.loads(capsys.readouterr().out)
    assert exported["baseline"]["corpus_sha256"] == baseline["corpus_sha256"]
    assert exported["result_template"]["run_kind"] == "unrun"
    paths = [tmp_path / "a.json", tmp_path / "b.json"]
    for index, path in enumerate(paths):
        path.write_text(json.dumps(_result(baseline, f"synthetic-{index}")), encoding="utf-8")
    completed = subprocess.run([sys.executable, "-m", "harness_mem.qualification.quality_baseline",
                                "--left", str(paths[0]), "--right", str(paths[1])],
                               capture_output=True, text=True, encoding="utf-8", check=False)
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["real_upstream_comparison_verified"] is False
    failed = read_json(paths[0])
    failed["outputs"] = []
    paths[0].write_text(json.dumps(failed), encoding="utf-8")
    assert main(["--left", str(paths[0]), "--right", str(paths[1])]) == 1
    capsys.readouterr()
    paths[0].write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
    assert main(["--left", str(paths[0]), "--right", str(paths[1])]) == 2
    assert json.loads(capsys.readouterr().out)["status"] == "invalid"
    assert FIXTURE_PATH.is_file()
