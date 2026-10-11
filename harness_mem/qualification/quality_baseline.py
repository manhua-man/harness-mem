"""Offline matched-corpus scoring, without model or memory-store access.

Export the frozen corpus/contract::

    python -m harness_mem.qualification.quality_baseline --corpus

Score two separately collected normalized JSON results (stdout only)::

    python -m harness_mem.qualification.quality_baseline --left a.json --right b.json

Outputs must be the full final knowledge snapshot plus handoffs. Exact oracle
title/statement pairs still need genuine source spans. Other wording requires
an explicitly human-reviewed mapping covering EVERY output, including incorrect
and unrelated outputs. The scorer validates that attestation, not its semantics.
It never turns keyword overlap, output IDs or bare point IDs into semantic proof.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from harness_mem.qualification.distill_fixture_catalog import fixture


FIXTURE_PATH = Path(__file__).with_name("fixtures") / "quality_baseline.json"
MEASUREMENTS = (
    "necessary_user_operations", "agent_calls", "input_tokens", "output_tokens",
    "cached_tokens", "billed_cost", "workflow_seconds", "preflight_seconds",
)


def fingerprint(value: Any) -> str:
    """Stable SHA-256 of canonical UTF-8 JSON, including configuration/oracle."""
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _rows(value: Any, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise ValueError(f"{label} must be an array of objects")
    return value


def _unique(rows: list[dict[str, Any]], key: str, label: str) -> dict[str, Any]:
    indexed = {_text(row.get(key), label): row for row in rows}
    if len(indexed) != len(rows):
        raise ValueError(f"duplicate {label}")
    return indexed


def load_baseline() -> dict[str, Any]:
    """Expand pinned existing fixtures; fail closed on catalog/source drift."""
    baseline = read_json(FIXTURE_PATH)
    if baseline.get("schema_version") != 1:
        raise ValueError("unsupported baseline schema")
    sources = _unique(_rows(baseline.get("sources"), "sources"), "id", "source id")
    for source in sources.values():
        if "catalog_id" in source:
            source["text"] = fixture(source["catalog_id"])["transcript"]
        text = _text(source.get("text"), "source text")
        if hashlib.sha256(text.encode("utf-8")).hexdigest() != source.get("sha256"):
            raise ValueError(f"frozen source drift: {source['id']}")
    points = _unique(_rows(baseline.get("points"), "points"), "id", "point id")
    pairs: set[tuple[str, str]] = set()
    for point in points.values():
        if point.get("outcome") not in {"memory", "handoff", "no_write", "conflict"}:
            raise ValueError("invalid oracle outcome")
        pair = (_text(point.get("title"), "title"), _text(point.get("statement"), "statement"))
        if pair in pairs:
            raise ValueError("ambiguous oracle wording")
        pairs.add(pair)
        for group in _evidence_groups(point):
            evidence = _rows(group, "oracle evidence")
            if not evidence:
                raise ValueError("oracle point needs source evidence")
            for ref in evidence:
                quote = _text(ref.get("quote"), "oracle quote")
                source_id = ref.get("source_id")
                source = sources.get(source_id) if isinstance(source_id, str) else None
                if source is None or source["text"].count(quote) != 1:
                    raise ValueError(f"oracle quote absent or ambiguous: {point['id']}")
                ref["start"] = source["text"].index(quote)
                ref["end"] = ref["start"] + len(quote)
    baseline["corpus_sha256"] = fingerprint(baseline)
    return baseline


def result_template(baseline: dict[str, Any]) -> dict[str, Any]:
    """An UNRUN contract, never an auto-generated passing product result."""
    return {
        "schema_version": 1,
        "product": {"name": "REQUIRED", "version": "REQUIRED", "revision": "REQUIRED"},
        "configuration": {"model": None, "host": None, "background_enabled": False},
        "run_kind": "unrun",
        "corpus_version": baseline["corpus_version"],
        "corpus_sha256": baseline["corpus_sha256"],
        "source_hashes": {s["id"]: s["sha256"] for s in baseline["sources"]},
        "coverage": [],
        "outputs": [],
        "human_review": None,
        "measurements": {key: None for key in MEASUREMENTS},
        "measurement_evidence": {},
        "recovery": None,
        "readability": None,
        "contract": {
            "coverage": "Exactly one {source_id,start:0,end:len(text)} per complete source; offsets are Unicode characters, not bytes.",
            "outputs": "Every final memory/handoff: {id,kind,title,statement,evidence:[{source_id,start,end,quote}]}. Include seeded knowledge; source_hashes pins its text.",
            "human_review": "For any nonexact wording: {reviewed_by,confirmed:true,mappings:[{output_id,point_ids:[one id or multiple for overbroad],verdict:matches|incorrect,rationale}]}. Exactly one mapping per output. incorrect may have empty point_ids.",
            "measurements": "Nonnegative measured values or null; every known value needs a nonempty measurement_evidence[key] reference. Cost currency/configuration belongs in configuration.",
            "recovery_and_readability": "Recorded but not scored automatically; attach human/runtime evidence outside this scorer.",
        },
    }


def _review(result: dict[str, Any], outputs: dict[str, Any], points: dict[str, Any]) -> dict[str, Any] | None:
    review = result.get("human_review")
    if review is None:
        return None
    if not isinstance(review, dict) or review.get("confirmed") is not True:
        raise ValueError("human review requires confirmed=true")
    _text(review.get("reviewed_by"), "human reviewer")
    mappings = _unique(_rows(review.get("mappings"), "mappings"), "output_id", "mapping output id")
    if set(mappings) != set(outputs):
        raise ValueError("human mapping must cover every output exactly once")
    for mapping in mappings.values():
        ids = mapping.get("point_ids")
        if (not isinstance(ids, list) or any(not isinstance(p, str) for p in ids)
                or len(ids) != len(set(ids)) or not set(ids) <= set(points)):
            raise ValueError("invalid mapped point ids")
        if mapping.get("verdict") not in {"matches", "incorrect"}:
            raise ValueError("invalid mapping verdict")
        if mapping["verdict"] == "matches" and not ids:
            raise ValueError("matches requires at least one point")
        _text(mapping.get("rationale"), "mapping rationale")
    return mappings


def _evidence_errors(output: dict[str, Any], mapped: list[dict[str, Any]], sources: dict[str, Any]) -> list[str]:
    refs = _rows(output.get("evidence"), "output evidence")
    errors: list[str] = []
    valid: list[dict[str, Any]] = []
    for ref in refs:
        source_id = ref.get("source_id")
        source = sources.get(source_id) if isinstance(source_id, str) else None
        start, end, quote = ref.get("start"), ref.get("end"), ref.get("quote")
        if (source is None or type(start) is not int or type(end) is not int
                or not 0 <= start < end <= len(source["text"])
                or not isinstance(quote, str) or source["text"][start:end] != quote):
            errors.append("invalid_source_span")
        else:
            valid.append(ref)
    for point in mapped:
        supported = any(all(any(
            ref["source_id"] == required["source_id"]
            and ref["start"] <= required["start"] and ref["end"] >= required["end"]
            for ref in valid) for required in group) for group in _evidence_groups(point))
        if not supported:
            errors.append(f"missing_point_evidence:{point['id']}")
    if not refs:
        errors.append("no_source_evidence")
    return sorted(set(errors))


def _evidence_groups(point: dict[str, Any]) -> list[Any]:
    alternatives = point.get("alternative_evidence", [])
    if not isinstance(alternatives, list):
        raise ValueError("alternative evidence must be an array of evidence groups")
    return [point.get("evidence"), *alternatives]


def score_result(baseline: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    """Score exact or attested associations; never infer semantic relationships."""
    if result.get("schema_version") != 1:
        raise ValueError("unsupported result schema")
    product = result.get("product")
    if not isinstance(product, dict):
        raise ValueError("product identity required")
    for key in ("name", "version", "revision"):
        value = _text(product.get(key), f"product {key}")
        if value == "REQUIRED":
            raise ValueError("replace REQUIRED product identity")
    config = result.get("configuration")
    if not isinstance(config, dict) or not config:
        raise ValueError("frozen configuration required")
    if not {"model", "host", "background_enabled"} <= set(config):
        raise ValueError("configuration requires model/host (null if unknown) and background_enabled")
    if config["background_enabled"] is not False:
        raise ValueError("manual quality baseline requires background_enabled=false")
    for key in ("model", "host"):
        if config[key] is not None:
            _text(config[key], f"configuration {key}")
    if result.get("run_kind") not in {"synthetic_fixture", "recorded_product_run"}:
        raise ValueError("run_kind must label a synthetic fixture or recorded product run")
    if (result.get("corpus_version") != baseline["corpus_version"]
            or result.get("corpus_sha256") != baseline["corpus_sha256"]):
        raise ValueError("corpus version/hash mismatch")
    sources = {s["id"]: s for s in baseline["sources"]}
    if result.get("source_hashes") != {k: s["sha256"] for k, s in sources.items()}:
        raise ValueError("source hashes must cover exactly the frozen sources")
    coverage = _unique(_rows(result.get("coverage"), "coverage"), "source_id", "coverage source id")
    if set(coverage) != set(sources):
        raise ValueError("complete source coverage required")
    for source_id, row in coverage.items():
        if (type(row.get("start")) is not int or type(row.get("end")) is not int
                or row["start"] != 0 or row["end"] != len(sources[source_id]["text"])):
            raise ValueError("coverage must include the complete source, including its tail")
    points = {p["id"]: p for p in baseline["points"]}
    exact = {(p["title"], p["statement"]): p["id"] for p in points.values()}
    outputs = _unique(_rows(result.get("outputs"), "outputs"), "id", "output id")
    for row in outputs.values():
        if row.get("kind") not in {"memory", "handoff"}:
            raise ValueError("output kind must be memory or handoff")
        _text(row.get("title"), "output title")
        _text(row.get("statement"), "output statement")
    mappings = _review(result, outputs, points)
    accepted: dict[str, list[str]] = {}
    incorrect, unverified, overbroad, rows = [], [], [], []
    duplicates: list[list[str]] = []
    seen_pairs: dict[tuple[str, str, str], list[str]] = {}
    for output_id, output in outputs.items():
        pair = (output["title"], output["statement"])
        exact_id = exact.get(pair)
        if mappings is not None:
            mapping = mappings[output_id]
            ids = mapping["point_ids"]
            verdict = mapping["verdict"]
            if exact_id and (ids != [exact_id] or verdict != "matches"):
                raise ValueError("human mapping contradicts exact oracle wording")
        else:
            ids = [exact_id] if exact_id else []
            verdict = "matches" if exact_id else "unverified"
        mapped = [points[p] for p in ids]
        errors = _evidence_errors(output, mapped, sources)
        if verdict == "unverified" or errors:
            unverified.append(output_id)
        if len(ids) > 1:
            overbroad.append(output_id)
        wrong_route = any(p["outcome"] != output["kind"] for p in mapped)
        if verdict == "incorrect" or wrong_route or len(ids) > 1:
            incorrect.append(output_id)
        if verdict == "matches" and len(ids) == 1 and not errors and not wrong_route:
            accepted.setdefault(ids[0], []).append(output_id)
        seen_pairs.setdefault((output["kind"], *pair), []).append(output_id)
        rows.append({"output_id": output_id, "kind": output["kind"], "point_ids": ids, "evidence_errors": errors,
                     "mapping_basis": "human_attestation" if mappings is not None else "exact_pair"})
    for group in [*accepted.values(), *seen_pairs.values()]:
        if len(group) > 1 and group not in duplicates:
            duplicates.append(group)
    expected_memory = [p for p in points if points[p]["outcome"] == "memory"]
    expected_handoffs = [p for p in points if points[p]["outcome"] == "handoff"]
    missed = [p for p in expected_memory if p not in accepted]
    missed_handoffs = [p for p in expected_handoffs if p not in accepted]
    measurements = result.get("measurements", {})
    evidence = result.get("measurement_evidence", {})
    if not isinstance(measurements, dict) or not isinstance(evidence, dict):
        raise ValueError("measurements and measurement_evidence must be objects")
    if not set(measurements) <= set(MEASUREMENTS):
        raise ValueError("unknown measurement key")
    for key, value in measurements.items():
        if value is not None:
            if (type(value) not in {int, float} or not math.isfinite(value) or value < 0
                    or (key not in {"billed_cost", "workflow_seconds", "preflight_seconds"}
                        and type(value) is not int)):
                raise ValueError(f"invalid measured value: {key}")
            _text(evidence.get(key), f"measurement evidence for {key}")
    status = "failed" if missed or missed_handoffs or incorrect or duplicates else "passed"
    if unverified and status == "passed":
        status = "partial"
    return {
        "product": product, "run_kind": result["run_kind"], "configuration": config,
        "configuration_sha256": fingerprint(config), "result_sha256": fingerprint(result),
        "quality_status": status,
        "memory_recall": {"verified": len(expected_memory) - len(missed), "expected": len(expected_memory)},
        "missed_points": missed, "incorrect_outputs": incorrect,
        "incorrect_writes": [oid for oid in incorrect if outputs[oid]["kind"] == "memory"],
        "duplicate_output_groups": duplicates, "overbroad_outputs": overbroad,
        "handoffs": {"verified": len(expected_handoffs) - len(missed_handoffs),
                     "expected": len(expected_handoffs), "missed_points": missed_handoffs},
        "unverified_outputs": unverified, "output_checks": rows,
        "measurements": {key: measurements.get(key) for key in MEASUREMENTS},
        "measurement_evidence": evidence,
        "recovery": result.get("recovery"), "readability": result.get("readability"),
        "recovery_status": "not_automatically_verified", "readability_status": "not_automatically_verified",
        "user_operations_status": "unknown" if measurements.get("necessary_user_operations") is None else "reported_only",
    }


def compare_results(baseline: dict[str, Any], left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    scores = [score_result(baseline, value) for value in (left, right)]
    return {
        "schema_version": 1, "scope": "provided_normalized_results_only",
        "corpus_version": baseline["corpus_version"], "corpus_sha256": baseline["corpus_sha256"],
        "source_hashes": {s["id"]: s["sha256"] for s in baseline["sources"]},
        "products": scores,
        "same_configuration": scores[0]["configuration_sha256"] == scores[1]["configuration_sha256"],
        "configuration_equality_scope": "declared JSON only; unknown models/hosts do not prove matched execution",
        "real_upstream_comparison_verified": False,
        "limitations": baseline["limitations"],
    }


def read_json(path: Path) -> dict[str, Any]:
    def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    def invalid_constant(value: str) -> Any:
        raise ValueError(f"invalid JSON constant: {value}")

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=strict_object,
                       parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("JSON root must be an object")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", action="store_true", help="Export frozen sources, oracle and unrun result template")
    parser.add_argument("--left", type=Path, help="First product's normalized result JSON")
    parser.add_argument("--right", type=Path, help="Second product's normalized result JSON")
    args = parser.parse_args(argv)
    if args.corpus == bool(args.left or args.right) or (not args.corpus and not (args.left and args.right)):
        parser.error("use --corpus OR both --left and --right")
    try:
        baseline = load_baseline()
        report: dict[str, Any]
        if args.corpus:
            report = {"baseline": baseline, "result_template": result_template(baseline)}
        else:
            report = compare_results(baseline, read_json(args.left), read_json(args.right))
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "invalid", "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    if args.corpus:
        return 0
    return 0 if all(p["quality_status"] == "passed" for p in report["products"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
