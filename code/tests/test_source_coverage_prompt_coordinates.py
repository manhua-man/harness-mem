"""Native addressing hints do not change V5 evidence or output contracts."""
from __future__ import annotations

import copy
import hashlib
import json

import pytest

from test_source_coverage_inventory_transport import fixture, verification
from harness_mem.autonomous.models import NativeSourceCoverageExtractionDecision, NativeSourceCoverageVerificationDecision
from harness_mem.autonomous.provider import (
    _build_prompt, _build_verification_prompt, _coverage_digest,
    _source_coverage_conversation_context, expand_agent_extraction_decision,
    expand_source_coverage_verification_decision, get_source_coverage_audit_binding,
    get_source_coverage_inventory, source_coverage_audit_binding_block,
)
from harness_mem.commands.separated_assimilation import target_version


def packet(prompt, tag):
    return json.loads(prompt.split(f"<{tag}>", 1)[1].rsplit(f"</{tag}>", 1)[0])


def unicode_fixture(*, zero=False):
    manifest, extraction = fixture(zero=zero)
    source = manifest["source_coverage"]["inventory_input"]
    text = source["windows"][0]["text"] + "\r\n中文 e\u0301 👩\u200d💻  "
    window = source["windows"][0]
    window.update(text=text, sha256=hashlib.sha256(text.encode()).hexdigest())
    extraction["inventory"][0]["spans"][0]["e"] = len(text)
    source["current"][0]["statement"] = text
    source["current"][0]["version"] = target_version(source["current"][0])
    manifest["semantic_decision_exchanges"][0]["content"] = f"User: {text}\nAssistant outcome: Report only 0."
    return manifest, extraction


def strip_coordinates(scope):
    result = copy.deepcopy(scope)
    for row in result["inventory_input"]["windows"]:
        row.pop("window_index")
        row.pop("char_count")
    for row in result["inventory_input"]["current"]:
        row.pop("current_index")
    return result


@pytest.mark.parametrize("zero", [False, True])
def test_two_native_stages_have_identical_exact_unicode_addresses_without_manifest_mutation(zero):
    manifest, extraction = unicode_fixture(zero=zero)
    original = copy.deepcopy(manifest)
    canonical_hash = _coverage_digest(manifest["source_coverage"]["inventory_input"])
    original_decision, verify, native = verification(manifest, extraction)
    before_verify = copy.deepcopy(verify)
    before_audit_input = _coverage_digest(verify["source_coverage"]["inventory_input"])
    extract_prompt = _build_prompt(manifest)
    verify_prompt = _build_verification_prompt(verify)
    extract_packet = packet(extract_prompt, "source_coverage")
    verify_packet = packet(verify_prompt, "verification_manifest")
    left = extract_packet["source_coverage"]["inventory_input"]
    right = verify_packet["source_coverage"]["inventory_input"]
    assert left == right
    for index, row in enumerate(left["windows"]):
        original_row = original["source_coverage"]["inventory_input"]["windows"][index]
        assert row["window_index"] == index and row["char_count"] == len(original_row["text"])
        assert row["text"] == original_row["text"]
        assert {key: value for key, value in row.items() if key not in {"window_index", "char_count"}} == original_row
    assert left["windows"][0]["char_count"] != len(left["windows"][0]["text"].encode())
    assert left["windows"][0]["char_count"] != len(left["windows"][0]["text"].encode("utf-16-le")) // 2
    assert len("e\u0301") == 2 and len("👩\u200d💻") == 3
    assert [row["current_index"] for row in left["current"]] == list(range(len(left["current"])))
    assert strip_coordinates(extract_packet["source_coverage"]) == original["source_coverage"]
    assert strip_coordinates(verify_packet["source_coverage"]) == before_verify["source_coverage"]
    # An aliased current_successors row must not receive inventory-only hints.
    assert extract_packet["source_coverage"]["current_successors"] == original["source_coverage"]["current_successors"]
    assert extract_packet["conversation_context"] == _source_coverage_conversation_context(original)
    assert verify_packet["conversation_context"] == _source_coverage_conversation_context(before_verify)
    assert manifest == original and verify == before_verify
    assert _coverage_digest(manifest["source_coverage"]["inventory_input"]) == canonical_hash == before_audit_input
    for prompt in (extract_prompt, verify_prompt):
        assert "addressing hints only" in prompt and "not source evidence" in prompt
    # The existing compact output has no coordinate fields and is still bound/audited normally.
    decision = expand_agent_extraction_decision(NativeSourceCoverageExtractionDecision.model_validate(extraction), manifest=manifest)
    assert get_source_coverage_inventory(decision) == get_source_coverage_inventory(original_decision)
    verified = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify)
    binding = get_source_coverage_audit_binding(verified, verify)
    assert source_coverage_audit_binding_block(binding, verify) is None
    assert binding["input_sha256"] == canonical_hash


def test_large_inventory_gets_direct_window_and_current_addresses_without_reordering():
    manifest, _extraction = unicode_fixture(zero=True)
    source = manifest["source_coverage"]["inventory_input"]
    for index in range(3, 82):
        text = f"Original scoped condition {index}: 中文 e\u0301 🚀"
        source["windows"].append({"exchange_index": index + 1, "message_index": 0, "role": "user",
            "text": text, "sha256": hashlib.sha256(text.encode()).hexdigest(), "exchange_sha256": "f" * 64})
    for index in range(1, 35):
        row = copy.deepcopy(source["current"][0])
        row["id"] = f"current-{index}"
        row["version"] = target_version(row)
        source["current"].append(row)
    before = copy.deepcopy(manifest)
    projected = packet(_build_prompt(manifest), "source_coverage")["source_coverage"]["inventory_input"]
    assert [row["window_index"] for row in projected["windows"]] == list(range(82))
    assert [row["current_index"] for row in projected["current"]] == list(range(35))
    assert [row["text"] for row in projected["windows"]] == [row["text"] for row in source["windows"]]
    assert [row["id"] for row in projected["current"]] == [row["id"] for row in source["current"]]
    assert manifest == before


@pytest.mark.parametrize("stage", ["extract", "verify"])
@pytest.mark.parametrize("fault", ["role", "text_hash", "current_version", "write_authority"])
def test_coordinates_do_not_relax_original_input_rejection(stage, fault):
    manifest, extraction = unicode_fixture()
    if stage == "verify":
        _decision, manifest, _native = verification(manifest, extraction)
    source = manifest["source_coverage"]["inventory_input"]
    if fault == "role":
        source["windows"][0]["role"] = "assistant"
    elif fault == "text_hash":
        source["windows"][0]["text"] += " unbound"
    elif fault == "current_version":
        source["current"][0]["version"] = "unbound"
    else:
        source["current"][0]["allowed_targets"] = ["current-0"]
    with pytest.raises(ValueError):
        (_build_prompt if stage == "extract" else _build_verification_prompt)(manifest)


@pytest.mark.parametrize("fault", ["gap", "overlap", "wrong_current_index"])
def test_hints_do_not_relax_old_output_span_or_current_links(fault):
    manifest, extraction = unicode_fixture(zero=True)
    original_hash = _coverage_digest(manifest["source_coverage"]["inventory_input"])
    _build_prompt(manifest)
    first = extraction["inventory"][0]["spans"][0]
    if fault == "gap":
        first["s"] = 1
    elif fault == "overlap":
        extraction["inventory"][0]["spans"].append(copy.deepcopy(first))
    else:
        first["c"] = [1]
    with pytest.raises(ValueError):
        expand_agent_extraction_decision(NativeSourceCoverageExtractionDecision.model_validate(extraction), manifest=manifest)
    assert _coverage_digest(manifest["source_coverage"]["inventory_input"]) == original_hash
