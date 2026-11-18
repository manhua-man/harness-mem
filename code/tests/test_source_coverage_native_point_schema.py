"""V5 native points expose their actual user-only evidence authority."""
from __future__ import annotations

import copy

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.models import (
    AgentExtractionDecision,
    AgentExtractionPoint,
    NativeSourceCoverageExtractionDecision,
    NativeSourceCoverageExtractionPoint,
)
from harness_mem.autonomous.provider import (
    _build_prompt,
    _strict_output_schema,
    expand_agent_extraction_decision,
    get_source_coverage_inventory,
)
from test_source_coverage_inventory_transport import fixture


def test_native_json_schema_exposes_only_user_evidence_and_null_report_repository_fields():
    schema = NativeSourceCoverageExtractionDecision.model_json_schema()
    assert schema["type"] == "object" and "anyOf" not in schema
    assert set(schema["properties"]) == {"extraction", "inventory"}
    assert len(schema["properties"]["extraction"]["anyOf"]) == 2
    branch = schema["properties"]["extraction"]["anyOf"][0]["$ref"].split("/")[-1]
    reference = schema["$defs"][branch]["properties"]["points"]["items"]["$ref"].split("/")[-1]
    fields = schema["$defs"][reference]["properties"]
    assert fields["evidence_basis"]["const"] == "user_statement"
    for name in ("report_role", "repository_locator", "repository_sha256"):
        assert fields[name]["type"] == "null"
        assert "enum" not in fields[name] and "anyOf" not in fields[name]
    assert set(fields["kind"]["enum"]) == {"memory", "rule", "relation"}
    assert schema["properties"]["inventory"]["type"] == "array"


@pytest.mark.parametrize("zero", [False, True])
def test_nested_wire_roundtrip_preserves_legacy_private_projection(zero):
    manifest, flat = fixture(zero=zero)
    from_flat = NativeSourceCoverageExtractionDecision.model_validate(flat)
    wire = from_flat.model_dump(mode="json")
    assert set(wire) == {"extraction", "inventory"}
    from_wire = NativeSourceCoverageExtractionDecision.model_validate(wire)
    assert from_wire.review == from_flat.review and from_wire.points == from_flat.points
    actual = expand_agent_extraction_decision(from_wire, manifest=manifest)
    expected = expand_agent_extraction_decision(from_flat, manifest=manifest)
    assert actual.model_dump(mode="json") == expected.model_dump(mode="json")
    assert get_source_coverage_inventory(actual) == get_source_coverage_inventory(expected)


@pytest.mark.parametrize("fault", [
    "candidate_reason", "candidate_signals", "candidate_empty", "zero_reason", "zero_points", "short_reason",
])
def test_strict_native_schema_and_runtime_both_reject_cross_branch_combinations(fault):
    from jsonschema import Draft202012Validator

    zero = fault.startswith("zero") or fault == "short_reason"
    _manifest, flat = fixture(zero=zero)
    wire = NativeSourceCoverageExtractionDecision.model_validate(flat).model_dump(mode="json")
    extraction = wire["extraction"]
    if fault == "candidate_reason":
        extraction["review"]["no_candidate_reason"] = "A complete reason belongs only to the zero-candidate branch."
    elif fault == "candidate_signals":
        extraction["review"]["not_durable_signals"] = ["explicit_decision"]
    elif fault == "candidate_empty":
        extraction["points"] = []
    elif fault == "zero_reason":
        extraction["review"]["no_candidate_reason"] = None
    elif fault == "short_reason":
        extraction["review"]["no_candidate_reason"] = "short"
    else:
        _other_manifest, positive = fixture()
        extraction["points"] = [NativeSourceCoverageExtractionPoint.model_validate(
            positive["points"][0]).model_dump(mode="json")]
    schema = _strict_output_schema(NativeSourceCoverageExtractionDecision.model_json_schema())
    Draft202012Validator.check_schema(schema)
    assert list(Draft202012Validator(schema).iter_errors(wire))
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(wire)
    # Lossless old-private wrapping must reject the same semantic contradiction.
    legacy = {**extraction, "inventory": wire["inventory"]}
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(legacy)


@pytest.mark.parametrize("zero", [False, True])
def test_strict_native_schema_accepts_exactly_its_own_valid_branch(zero):
    from jsonschema import Draft202012Validator

    _manifest, flat = fixture(zero=zero)
    wire = NativeSourceCoverageExtractionDecision.model_validate(flat).model_dump(mode="json")
    schema = _strict_output_schema(NativeSourceCoverageExtractionDecision.model_json_schema())
    assert schema["type"] == "object" and "anyOf" not in schema
    branches = schema["properties"]["extraction"]["anyOf"]
    assert len(branches) == 2
    assert not list(Draft202012Validator(schema).iter_errors(wire))
    assert sum(Draft202012Validator({**branch, "$defs": schema["$defs"]}).is_valid(wire["extraction"])
               for branch in branches) == 1


@pytest.mark.parametrize("fault", ["flat_extra", "nested_extra", "mixed", "zero_signal"])
def test_legacy_wrapping_never_discards_unknown_fields_or_relaxes_zero_signal_checks(fault):
    _manifest, flat = fixture(zero=fault == "zero_signal")
    if fault == "flat_extra":
        flat["untrusted_override"] = True
        output = flat
    elif fault == "zero_signal":
        flat["review"]["not_durable_signals"] = ["invented_signal"]
        output = flat
    else:
        output = NativeSourceCoverageExtractionDecision.model_validate(flat).model_dump(mode="json")
        if fault == "nested_extra":
            output["extraction"]["untrusted_override"] = True
        else:
            output["review"] = flat["review"]
            output["points"] = flat["points"]
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(output)


def test_v5_prompt_and_hermes_contract_describe_the_same_nested_branches():
    from harness_mem.autonomous.executors.host_structured_cli import _hermes_output_contract

    manifest, _output = fixture()
    prompt = _build_prompt(manifest)
    contract = _hermes_output_contract(NativeSourceCoverageExtractionDecision)
    assert "extraction:{review,points}" in prompt
    assert 'Use {"extraction":{"review":' in contract
    for text in (prompt, contract):
        assert "exclusive extraction shape" in text
        assert "not_durable_signals is []" in text
        assert "24 characters" in text


def test_zero_branch_preserves_explicit_not_durable_signals_in_runtime_challenge():
    manifest, flat = fixture(zero=True)
    manifest["zero_candidate_challenge_template"]["checks"]["explicit_decision"] = "candidate_required"
    flat["review"]["not_durable_signals"] = ["explicit_decision"]
    native = NativeSourceCoverageExtractionDecision.model_validate(flat)
    runtime = expand_agent_extraction_decision(native, manifest=manifest)
    assert native.review.not_durable_signals == ["explicit_decision"]
    assert runtime.semantic_review.zero_candidate_challenge.checks.explicit_decision == "not_durable"
    assert runtime.semantic_review.zero_candidate_challenge.future_utility == "session_only"
    assert get_source_coverage_inventory(runtime)


@pytest.mark.parametrize("basis", ["source_report", "transcript", "repository_file"])
def test_native_point_refuses_non_user_evidence(basis):
    _manifest, output = fixture()
    output["points"][0].update(evidence_basis=basis, report_role="assistant")
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(output)


@pytest.mark.parametrize("field,value", [
    ("report_role", "assistant"),
    ("report_role", "user"),
    ("repository_locator", "file:///repository.py"),
    ("repository_sha256", "a" * 64),
])
def test_native_point_refuses_irrelevant_evidence_fields(field, value):
    _manifest, output = fixture(kind="rule")
    output["points"][0][field] = value
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(output)


@pytest.mark.parametrize("kind,field,value", [
    ("rule", "condition", None),
    ("rule", "condition", "   "),
    ("relation", "target_entity", None),
    ("memory", "exchange_indexes", []),
    ("memory", "exchange_indexes", [0]),
])
def test_native_point_retains_parent_kind_and_source_validation(kind, field, value):
    _manifest, output = fixture(kind=kind)
    output["points"][0][field] = value
    with pytest.raises(ValidationError):
        NativeSourceCoverageExtractionDecision.model_validate(output)


@pytest.mark.parametrize("kind", ["memory", "rule", "relation"])
def test_native_to_runtime_projection_preserves_ordinary_point_semantics_and_inventory(kind):
    manifest, output = fixture(kind=kind)
    native = NativeSourceCoverageExtractionDecision.model_validate(output)
    assert isinstance(native.points[0], NativeSourceCoverageExtractionPoint)
    runtime = expand_agent_extraction_decision(native, manifest=manifest)
    ordinary_manifest = copy.deepcopy(manifest)
    ordinary_manifest.pop("source_coverage")
    ordinary = AgentExtractionDecision.model_validate({
        "review": output["review"], "points": output["points"],
    })
    expected = expand_agent_extraction_decision(ordinary, manifest=ordinary_manifest)
    assert runtime.model_dump(mode="json") == expected.model_dump(mode="json")
    assert get_source_coverage_inventory(runtime)["extracted_points"]


def test_native_parent_no_write_reason_and_complete_inventory_gates_remain():
    manifest, output = fixture(zero=True)
    native = NativeSourceCoverageExtractionDecision.model_validate(output)
    assert not expand_agent_extraction_decision(native, manifest=manifest).candidates
    bad_reason = copy.deepcopy(output)
    bad_reason["review"]["no_candidate_reason"] = None
    with pytest.raises(ValidationError, match="no_candidate_reason"):
        NativeSourceCoverageExtractionDecision.model_validate(bad_reason)
    missing_inventory = copy.deepcopy(output)
    missing_inventory.pop("inventory")
    with pytest.raises(ValidationError, match="inventory"):
        NativeSourceCoverageExtractionDecision.model_validate(missing_inventory)
    partial_inventory = copy.deepcopy(output)
    partial_inventory["inventory"].pop()
    with pytest.raises(ValueError):
        expand_agent_extraction_decision(
            NativeSourceCoverageExtractionDecision.model_validate(partial_inventory), manifest=manifest,
        )


def test_ordinary_report_authority_remains_separate_and_validated():
    _manifest, output = fixture()
    point = output["points"][0]
    point.update(evidence_basis="source_report", report_role="assistant")
    ordinary = AgentExtractionDecision.model_validate({"review": output["review"], "points": [point]})
    assert ordinary.points[0].report_role == "assistant"
    assert type(ordinary.points[0]) is AgentExtractionPoint
    point["kind"] = "rule"
    point["condition"] = "During maintenance"
    with pytest.raises(ValidationError, match="source_report requires"):
        AgentExtractionDecision.model_validate({"review": output["review"], "points": [point]})
