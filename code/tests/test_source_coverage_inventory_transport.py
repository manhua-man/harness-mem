"""V5 inventory transport: offsets and independent audits, no real host I/O."""

import copy
import hashlib
from dataclasses import replace

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.executors import host_structured_cli as cli
from harness_mem.autonomous.models import (
    AgentExtractionDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
    NativeSourceCoverageExtractionDecision,
    NativeSourceCoverageVerificationDecision,
)
from harness_mem.autonomous.provider import (
    ProviderError,
    ProviderResult,
    _build_prompt,
    _build_verification_prompt,
    _coverage_digest,
    expand_agent_extraction_decision,
    expand_source_coverage_verification_decision,
    get_source_coverage_audit_binding,
    get_source_coverage_inventory,
    source_coverage_audit_binding_block,
    source_coverage_audit_block,
)
from harness_mem.commands.separated_assimilation import target_version


def fixture(*, zero=False, kind="memory"):
    texts = [
        'During this repair preserve "local" constraints.\nNo extra rituals. 🚀',
        "Export once today.",
        "Cancel that export.",
    ]
    current = dict(
        id="current-0",
        title="Repair scope",
        statement=texts[0],
        topic_path=["repair"],
        source_report=None,
    )
    current["version"] = target_version(current)
    windows = [
        dict(
            exchange_index=index + 1,
            message_index=0,
            role="user",
            text=text,
            sha256=hashlib.sha256(text.encode()).hexdigest(),
            exchange_sha256=str(index + 1) * 64,
        )
        for index, text in enumerate(texts)
    ]
    source = dict(
        contract="source-coverage-inventory-v1",
        source_id="original-source",
        source_revision="exact-revision",
        context_sha256="c" * 64,
        windows=windows,
        current=[current],
    )
    scope = dict(
        kind="runtime_maintenance_scope_not_source_evidence",
        contract="dream-applied-source-coverage-v5",
        retain_still_applicable_scoped_conditions=True,
        run_id="original-run",
        predecessor_id="old-point",
        current_successors=[current],
        inventory_input=source,
    )
    template = dict(
        version="v1",
        source_revision="exact-revision",
        evidence_fidelity="complete",
        future_utility="none",
        checks={
            key: "absent"
            for key in (
                "user_correction",
                "explicit_decision",
                "successful_solution",
                "repeated_failure",
                "rule_or_preference",
                "reusable_workflow_or_fact",
                "version_or_migration",
                "unfinished_handoff",
            )
        },
        inspected_exchange_refs=[dict(exchange_index=1, content_sha256="1" * 64)],
        conclusion="no_durable_candidate",
        rationale="Every source window receives a complete independent disposition audit.",
    )
    manifest = dict(
        source_coverage=scope,
        zero_candidate_challenge_template=template,
        semantic_decision_exchanges=[
            dict(
                exchange_index=index + 1,
                content_sha256=str(index + 1) * 64,
                content=f"User: {text}\nAssistant outcome: Report only {index}.",
                preceding_assistant_messages=[f"Intermediate assistant {index}."],
            )
            for index, text in enumerate(texts)
        ],
    )
    point = dict(
        kind=kind,
        statement="Preserve local constraints during this repair.",
        condition=None,
        evidence_basis="user_statement",
        report_role=None,
        exchange_indexes=[1],
    )
    if kind == "rule":
        # Obvious reversal must replay the existing pure normalizer exactly.
        point.update(statement="When repairing", condition="Preserve local constraints")
    elif kind == "relation":
        point.update(
            source_entity="Repair",
            relation_type="preserves",
            target_entity="constraints",
        )
    extraction = dict(
        review=dict(
            summary="Keep the exact scoped original repair requirements.",
            final_request="Preserve constraints.",
            actual_result="Requirements remain source-supported.",
            contradictions=[],
            unfinished=[],
            no_candidate_reason="All useful scoped source conditions are already covered by exact current memory."
            if zero
            else None,
            not_durable_signals=[],
        ),
        points=[] if zero else [point],
        inventory=[
            dict(
                w=0,
                spans=[
                    dict(
                        s=0,
                        e=len(texts[0]),
                        d="covered" if zero else "extract",
                        p=[] if zero else [0],
                        c=[0] if zero else [],
                        r=[],
                    )
                ],
            ),
            dict(
                w=1,
                spans=[
                    dict(
                        s=0,
                        e=len(texts[1]),
                        d="superseded",
                        p=[],
                        c=[],
                        r=[dict(w=2, s=0, e=len(texts[2]))],
                    )
                ],
            ),
            dict(
                w=2, spans=[dict(s=0, e=len(texts[2]), d="temporary", p=[], c=[], r=[])]
            ),
        ],
    )
    return manifest, extraction


def verification(manifest, extraction):
    from harness_mem.autonomous.worker import (
        _candidate_statement_from_arguments,
        _normalize_rule_candidate_fields,
    )

    decision = expand_agent_extraction_decision(
        NativeSourceCoverageExtractionDecision.model_validate(extraction),
        manifest=manifest,
    )
    inventory = get_source_coverage_inventory(decision)
    scope = {**copy.deepcopy(manifest["source_coverage"]), "inventory": inventory}
    rows, points = [], []
    for index, candidate in enumerate(decision.candidates):
        arguments = candidate.model_dump(mode="json")
        if candidate.kind == "rule":
            pattern, trigger = _normalize_rule_candidate_fields(
                candidate.pattern, candidate.trigger
            )
            arguments.update(pattern=pattern, trigger=trigger)
        statement = _candidate_statement_from_arguments(arguments)
        sources = [
            dict(
                kind=ref.kind,
                exchange_index=ref.exchange_index,
                content_sha256=ref.content_sha256,
                content=manifest["semantic_decision_exchanges"][ref.exchange_index - 1][
                    "content"
                ],
            )
            for ref in candidate.verification_refs
        ]
        rows.append(
            dict(
                candidate_index=index,
                kind=candidate.kind,
                statement=statement,
                sources=sources,
            )
        )
        points.append(
            dict(
                candidate_index=index,
                semantic_support="supported",
                future_scope="durable",
                source_use="standing_decision",
                reason="The complete original user source entails the scoped requirement.",
                claim_units=[],
                scope_segments=[
                    dict(
                        text=statement,
                        source_support="supported",
                        source_use="standing_decision",
                        future_scope="durable",
                        standalone=True,
                        content_role="claim",
                    )
                ],
            )
        )
    verify = dict(
        contract_version="candidate-semantic-verification-v2",
        source_coverage=scope,
        candidates=rows,
        session_context=copy.deepcopy(manifest["semantic_decision_exchanges"]),
    )
    native = dict(
        points=points,
        audit=[
            dict(w=row["w"], span_index=index, verdict="supported")
            for row in inventory["windows"]
            for index in range(len(row["spans"]))
        ],
    )
    return decision, verify, native


@pytest.mark.parametrize(
    "zero,kind",
    [(True, "memory"), (False, "memory"), (False, "rule"), (False, "relation")],
)
def test_full_original_inventory_uses_same_candidate_verification_even_for_zero(
    zero, kind
):
    manifest, extraction = fixture(zero=zero, kind=kind)
    original, verify, native = verification(manifest, extraction)
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify
    )
    assert source_coverage_audit_block(decision, verify) is None
    binding = get_source_coverage_audit_binding(decision, verify)
    assert source_coverage_audit_binding_block(binding, verify) is None
    assert len(binding["windows"]) == len(binding["audit"]) == 3
    assert len(binding["extracted_point_sha256"]) == (0 if zero else 1)
    assert "source_coverage" not in original.model_dump()
    assert "_source_coverage_inventory" not in original.model_dump()
    assert "_source_coverage_audit" not in decision.model_dump()
    assert all(
        text not in str(binding)
        for text in [
            row["text"]
            for row in manifest["source_coverage"]["inventory_input"]["windows"]
        ]
    )
    for prompt in [_build_prompt(manifest), _build_verification_prompt(verify)]:
        assert "Intermediate assistant 0." in prompt and "Report only 0." in prompt
        assert (
            "not user source or approval" in prompt
            or "not independent user evidence or approval" in prompt
        )


@pytest.mark.parametrize(
    "fault",
    [
        "missing_window",
        "gap",
        "overlap",
        "range",
        "bool",
        "point",
        "point_unlinked",
        "covered_missing",
        "covered_foreign",
        "superseded_earlier",
        "superseded_range",
        "hidden_link",
        "assistant",
        "hash",
        "version",
    ],
)
def test_invalid_disposition_map_or_source_is_never_silently_accepted(fault):
    manifest, extraction = fixture()
    span = extraction["inventory"][0]["spans"][0]
    if fault == "missing_window":
        extraction["inventory"].pop()
    elif fault == "gap":
        span["s"] = 1
    elif fault == "overlap":
        extraction["inventory"][0]["spans"].append(copy.deepcopy(span))
    elif fault == "range":
        span["e"] += 1
    elif fault == "bool":
        span["p"] = [False]
    elif fault == "point":
        span["p"] = [1]
    elif fault == "point_unlinked":
        span.update(d="temporary", p=[])
    elif fault == "covered_missing":
        span.update(d="covered", p=[], c=[])
    elif fault == "covered_foreign":
        span.update(d="covered", p=[], c=[7])
    elif fault == "superseded_earlier":
        extraction["inventory"][1]["spans"][0]["r"][0]["w"] = 0
    elif fault == "superseded_range":
        extraction["inventory"][1]["spans"][0]["r"][0]["e"] = 10000
    elif fault == "hidden_link":
        extraction["inventory"][2]["spans"][0]["c"] = [0]
    elif fault == "assistant":
        manifest["source_coverage"]["inventory_input"]["windows"][0]["role"] = (
            "assistant"
        )
    elif fault == "hash":
        manifest["source_coverage"]["inventory_input"]["windows"][0]["text"] += (
            " changed"
        )
    else:
        manifest["source_coverage"]["inventory_input"]["current"][0]["version"] = (
            "f" * 64
        )
    with pytest.raises((ValueError, ValidationError)):
        expand_agent_extraction_decision(
            NativeSourceCoverageExtractionDecision.model_validate(extraction),
            manifest=manifest,
        )


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown",
        "wrong_point",
        "point_bool",
        "candidate_changed",
        "refs_changed",
        "input_changed",
        "inventory_changed",
    ],
)
def test_verification_cannot_skip_source_inventory_or_change_its_bound_outputs(fault):
    manifest, extraction = fixture()
    _, verify, native = verification(manifest, extraction)
    if fault == "missing":
        native["audit"].pop()
    elif fault == "duplicate":
        native["audit"].append(copy.deepcopy(native["audit"][0]))
    elif fault == "unknown":
        native["audit"][0]["w"] = 999
    elif fault == "wrong_point":
        native["points"][0]["candidate_index"] = 1
    elif fault == "point_bool":
        native["points"][0]["candidate_index"] = False
    elif fault == "candidate_changed":
        verify["candidates"][0]["statement"] += " changed"
    elif fault == "refs_changed":
        verify["candidates"][0]["sources"][0]["content_sha256"] = "f" * 64
    elif fault == "input_changed":
        verify["source_coverage"]["inventory_input"]["source_revision"] += " changed"
    else:
        verify["source_coverage"]["inventory"]["windows"][0]["spans"][0]["d"] = (
            "temporary"
        )
    with pytest.raises((ValueError, ValidationError)):
        expand_source_coverage_verification_decision(
            NativeSourceCoverageVerificationDecision.model_validate(native),
            manifest=verify,
        )


@pytest.mark.parametrize("verdict", ["unclear", "contradicted"])
def test_one_negative_span_refuses_all_writes_despite_supported_selected_point(verdict):
    manifest, extraction = fixture()
    _, verify, native = verification(manifest, extraction)
    native["audit"][1]["verdict"] = verdict
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify
    )
    assert decision.points[0].semantic_support == "supported"
    assert (
        source_coverage_audit_block(decision, verify)
        == "source_coverage_inventory_audit_unresolved"
    )
    with pytest.raises(ValueError):
        get_source_coverage_audit_binding(decision, verify)


def test_explicit_unclear_disposition_cannot_be_upgraded_by_positive_audit():
    manifest, extraction = fixture(zero=True)
    extraction["inventory"][2]["spans"][0]["d"] = "unclear"
    _, verify, native = verification(manifest, extraction)
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify
    )
    assert (
        source_coverage_audit_block(decision, verify)
        == "source_coverage_inventory_audit_unresolved"
    )


def test_checkpoint_summary_and_original_input_are_required_on_resume():
    manifest, extraction = fixture(zero=True)
    _, verify, native = verification(manifest, extraction)
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify
    )
    binding = get_source_coverage_audit_binding(decision, verify)
    resume = copy.deepcopy(verify)
    resume["source_coverage"].pop("inventory")
    assert source_coverage_audit_binding_block(binding, resume) is None
    changed = copy.deepcopy(binding)
    changed["windows"][0]["spans"][0]["d"] = "temporary"
    assert source_coverage_audit_binding_block(changed, resume)
    changed["summary_sha256"] = _coverage_digest(
        {key: value for key, value in changed.items() if key != "summary_sha256"}
    )
    assert source_coverage_audit_binding_block(
        changed, resume
    )  # The inventory digest still binds its original map.
    resume["source_coverage"]["inventory_input"]["source_revision"] = "different"
    assert source_coverage_audit_binding_block(binding, resume)


def test_private_inventory_copy_and_verdict_drift_cannot_change_bound_audit():
    manifest, extraction = fixture()
    original, verify, native = verification(manifest, extraction)
    copied = get_source_coverage_inventory(original)
    copied["windows"].clear()
    assert original._source_coverage_inventory["windows"]
    decision = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision.model_validate(native), manifest=verify
    )
    decision.points[0].semantic_support = "partial"
    assert (
        source_coverage_audit_block(decision, verify)
        == "source_coverage_inventory_audit_binding_incomplete"
    )


@pytest.mark.parametrize("host", ["codex", "hermes", "generic-fixture"])
def test_all_host_adapters_share_v5_shapes_and_known_usage_without_new_phase(
    tmp_path, monkeypatch, host
):
    manifest, extraction = fixture(zero=True)
    _, verify, native = verification(manifest, extraction)
    provider = cli.HostStructuredCliProvider(
        host_client=host, executable="never-started"
    )
    seen = []

    def run(_manifest, **kwargs):
        model = kwargs["decision_model"]
        seen.append(model)
        assert model in (
            NativeSourceCoverageExtractionDecision,
            NativeSourceCoverageVerificationDecision,
        )
        assert "inventory" in cli._hermes_output_contract(
            model
        ) or "audit" in cli._hermes_output_contract(model)
        return ProviderResult(
            decision=model.model_validate(extraction if len(seen) == 1 else native),
            provider=provider.name,
            model="isolated",
            duration_seconds=1,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=11,
            output_tokens=7,
            total_tokens=18,
            event_count=1,
        )

    monkeypatch.setattr(provider, "_run", run)
    assert isinstance(
        provider.decide(manifest, runtime_dir=tmp_path).decision, AutonomousDecision
    )
    result = provider.verify(verify, runtime_dir=tmp_path)
    assert (
        source_coverage_audit_block(result.decision, verify) is None
        and result.total_tokens == 18
    )
    assert seen == [
        NativeSourceCoverageExtractionDecision,
        NativeSourceCoverageVerificationDecision,
    ]


def test_normal_entry_schema_and_hermes_contract_do_not_acquire_inventory(
    tmp_path, monkeypatch
):
    manifest, extraction = fixture(zero=True)
    manifest["source_coverage"]["contract"] = "dream-applied-source-coverage-v4"
    extraction.pop("inventory")
    provider = cli.HostStructuredCliProvider(
        host_client="hermes", executable="never-started"
    )

    def run(_manifest, **kwargs):
        assert kwargs["decision_model"] is AgentExtractionDecision
        return ProviderResult(
            decision=AgentExtractionDecision.model_validate(extraction),
            provider=provider.name,
            model=None,
            duration_seconds=1,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            event_count=1,
        )

    monkeypatch.setattr(provider, "_run", run)
    assert (
        get_source_coverage_inventory(
            provider.decide(manifest, runtime_dir=tmp_path).decision
        )
        is None
    )
    assert "inventory" not in AgentExtractionDecision.model_json_schema()["properties"]
    assert "inventory" not in AutonomousDecision.model_json_schema()["properties"]
    assert (
        "audit" not in CandidateVerificationDecision.model_json_schema()["properties"]
    )


def test_failed_native_audit_binding_preserves_exact_usage_and_response_receipt(
    tmp_path, monkeypatch
):
    manifest, extraction = fixture()
    _, verify, native = verification(manifest, extraction)
    native["audit"].pop()
    provider = cli.HostStructuredCliProvider(
        host_client="hermes", executable="never-started"
    )
    result = ProviderResult(
        decision=NativeSourceCoverageVerificationDecision.model_validate(native),
        provider=provider.name,
        model=None,
        duration_seconds=12.5,
        input_sha256="a" * 64,
        response_sha256="b" * 64,
        input_tokens=11,
        output_tokens=7,
        total_tokens=18,
        event_count=1,
    )
    monkeypatch.setattr(provider, "_run", lambda *_a, **_k: result)
    with pytest.raises(ProviderError) as raised:
        provider.verify(verify, runtime_dir=tmp_path)
    assert raised.value.attempt_results == (
        replace(result, decision=None, schema_valid=False),
    )
    assert raised.value.failure_reason == "source_coverage_inventory_invalid"


def test_malformed_v5_input_cannot_downgrade_to_ordinary_extraction():
    manifest, _ = fixture()
    manifest["source_coverage"].pop("current_successors")
    with pytest.raises(ValueError):
        _build_prompt(manifest)


def test_hermes_v5_verification_preserves_quotes_backslashes_and_unicode():
    import json

    manifest, extraction = fixture()
    extraction["points"][0]["statement"] = (
        'Preserve "C:\\local\\data" 🚀 during this repair.'
    )
    _, verify, native = verification(manifest, extraction)
    decoded = NativeSourceCoverageVerificationDecision.model_validate_json(
        json.dumps(native, ensure_ascii=False)
    )
    decision = expand_source_coverage_verification_decision(decoded, manifest=verify)
    assert (
        decision.points[0].scope_segments[0].text
        == extraction["points"][0]["statement"]
    )
    contract = cli._hermes_output_contract(NativeSourceCoverageVerificationDecision)
    assert "standard JSON escaping" in contract and "paraphrase instead" not in contract


@pytest.mark.parametrize("host", ["hermes", "generic-fixture", "codex"])
@pytest.mark.parametrize("native_receipts", [False, True])
def test_failed_v5_extraction_binding_retains_completed_transport_receipt(
    tmp_path, monkeypatch, host, native_receipts
):
    manifest, extraction = fixture()
    extraction["inventory"].pop()  # Valid native shape, incomplete bound source.
    provider = cli.HostStructuredCliProvider(
        host_client=host, executable="never-started"
    )
    attempts = (
        (
            {
                "call_id": "already-settled",
                "status": "completed",
                "terminal": "completed",
                "model_dispatched": True,
                "input_sha256": "a" * 64,
                "response_text_sha256": "b" * 64,
                "usage": {"input_tokens": 31, "output_tokens": 7, "total_tokens": 38},
            },
        )
        if native_receipts
        else ()
    )
    result = ProviderResult(
        decision=NativeSourceCoverageExtractionDecision.model_validate(extraction),
        provider=provider.name,
        model="isolated",
        duration_seconds=12.5,
        input_sha256="a" * 64,
        response_sha256="b" * 64,
        input_tokens=31,
        output_tokens=7,
        total_tokens=38,
        event_count=1,
        native_attempts=attempts,
    )
    calls = []

    def completed_transport(*_args, **_kwargs):
        calls.append(True)
        return result

    monkeypatch.setattr(provider, "_run", completed_transport)
    with pytest.raises(ProviderError) as raised:
        provider.decide(manifest, runtime_dir=tmp_path)
    error = raised.value
    assert calls == [True]
    assert error.failure_reason == "source_coverage_inventory_invalid"
    assert error.native_attempts == attempts
    assert error.attempt_results == (
        replace(result, decision=None, schema_valid=False),
    )
    receipt = error.attempt_results[0]
    assert receipt.decision is None and receipt.schema_valid is False
    assert receipt.input_sha256 == "a" * 64 and receipt.response_sha256 == "b" * 64
    assert (receipt.input_tokens, receipt.output_tokens, receipt.total_tokens) == (
        31,
        7,
        38,
    )
    assert receipt.duration_seconds == 12.5
