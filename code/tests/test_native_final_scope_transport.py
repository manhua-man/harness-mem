"""Native final-proof shape/projection with fake I/O, never product models.

Canonical semantic/source/meaning and transaction checks remain independent.
Actual v12 condition prose was not recovered; malformed-prose tests below are
synthetic representations of the observed 4+3+6 invalid-condition shape.
"""
import copy
from dataclasses import replace
import hashlib
import json

import pytest
from pydantic import ValidationError

from harness_mem.autonomous.executors import host_structured_cli as cli
from harness_mem.autonomous.models import (
    CandidateVerificationDecision, DREAM_SOURCE_RECHECK_CONTRACT,
    NativeFinalScopeDecision, NativeFinalStatementSpan, SourceClassificationDecision,
    UpdateMeaningJudgment, verification_scope_status,
)
from harness_mem.autonomous.provider import ProviderError, ProviderResult, _build_assimilation_prompt, _build_verification_prompt
from harness_mem.commands.separated_assimilation import (
    final_scope_verification_rows, judged_update_payload, prove_supplied_final_scope, target_version,
)
from harness_mem.core.schemas.source_report import SourceReport, source_report_snapshot


def segment(text, *, temporary=False):
    return dict(text=text, source_support="supported", source_use="task_context" if temporary else "reusable_knowledge",
                future_scope="session_only" if temporary else "durable", standalone=True,
                content_role="temporary_context" if temporary else "claim")


def fixture_manifest(*, outputs=None, owners=1, disposition="refine"):
    outputs = outputs or ["Cache stays local only offline.", "Signing stays required; selection remains undecided."]
    rows, payloads = [], []
    for owner_index in range(owners):
        owner = f"owner-{owner_index}"
        owner_outputs = [f"Owner {owner_index}: {statement}" if owners > 1 else statement for statement in outputs]
        targets = [dict(id=f"original-{owner_index}-{index}", title=f"Old {index}", statement=statement,
                        topic_path=["cache"], source_report=None)
                   for index, statement in enumerate(owner_outputs)]
        for target in targets:
            target["version"] = target_version(target)
        items = [dict(title=f"Output {index}", statement=statement, topic_path=["cache"], claim_kind="implementation_fact")
                 for index, statement in enumerate(owner_outputs)]
        payload = dict(candidate_id=owner, disposition=disposition, targets=targets, knowledge_items=items)
        payloads.append(payload)
        for row in final_scope_verification_rows(payload, sources=[dict(kind="repository", content="Complete fixture source.")]):
            row["candidate_index"] = len(rows)
            rows.append(row)
    return dict(contract_version="final-knowledge-scope-v1", scope_partition_required=True, candidates=rows), payloads


def native_payload(manifest):
    points = []
    for row in manifest["candidates"]:
        context = row.get("update_context")
        proof = None
        if context is not None:
            statement = context["successors"][0]["statement"]
            proof = dict(relationship="preserves_applicable_meaning", inventory_complete=True,
                         condition_spans=[dict(successor_index=0, char_start=0, char_end=len(statement))],
                         undecided_span=None, basis="All original conditions remain in the complete successor set.")
        points.append(dict(candidate_index=row["candidate_index"], semantic_support="supported", source_use="reusable_knowledge",
                           future_scope="durable", reason="Read exact complete sources and independently judge the final scope.",
                           scope_segments=[segment(row["scope_text"])], update_meaning_judgment=proof))
    return {"points": points}


def expanded(manifest, payload=None):
    return NativeFinalScopeDecision.model_validate(payload or native_payload(manifest)).as_verification(manifest)


def test_exact_schema_cannot_return_free_text_conditions_endpoints_or_writes():
    schema = NativeFinalScopeDecision.model_json_schema()
    proof = schema["$defs"]["NativeFinalUpdateMeaning"]["properties"]
    assert set(proof) == {"relationship", "inventory_complete", "condition_spans", "undecided_span", "basis",
                          "report_preservation"}
    assert set(schema["$defs"]["NativeReportPreservation"]["properties"]) == {
        "inventory_complete", "units", "omissions"}
    assert set(schema["$defs"]["NativeReportUnitPreservation"]["properties"]) == {
        "unit_index", "verdict", "successor_spans"}
    assert set(schema["$defs"]["NativeReportOmissionPreservation"]["properties"]) == {
        "omission_index", "claim", "evidence", "causality", "boundary", "permission", "scope"}
    assert all(schema["$defs"][name]["additionalProperties"] is False for name in (
        "NativeReportPreservation", "NativeReportUnitPreservation", "NativeReportOmissionPreservation"))
    point = schema["$defs"]["NativeFinalScopePoint"]["properties"]
    assert not {"claim_units", "literal_edit_contract", "replacement_items", "report_outputs", "output_verifications"} & point.keys()
    manifest, _ = fixture_manifest()
    for forbidden, value in [("predecessor_conditions", ["a descriptive paraphrase"] * 13),
                             ("predecessor_statements", ["invented original"]),
                             ("predecessor_versions", ["forged"]), ("successor_statements", ["invented output"]),
                             ("undecided_state", "paraphrased setting")]:
        payload = native_payload(manifest)
        payload["points"][0]["update_meaning_judgment"][forbidden] = value
        with pytest.raises(ValidationError):
            NativeFinalScopeDecision.model_validate(payload)


def test_multiple_owners_and_outputs_bind_full_local_order_without_borrowing():
    manifest, payloads = fixture_manifest(owners=2)
    payload = native_payload(manifest)
    # Owner-local successor 1 is distinct from batch candidate index 1/3.
    for point in payload["points"]:
        statement = manifest["candidates"][point["candidate_index"]]["update_context"]["successors"][1]["statement"]
        point["update_meaning_judgment"]["undecided_span"] = dict(
            successor_index=1, char_start=statement.index("selection"), char_end=len(statement) - 1)
    decision = expanded(manifest, payload)
    for index, point in enumerate(decision.points):
        owner_payload = payloads[index // 2]
        judgment = point.update_meaning_judgment
        statements = [item["statement"] for item in owner_payload["knowledge_items"]]
        assert judgment.covers(statements)
        assert judgment.binds_predecessors(owner_payload["targets"])
        assert judgment.successor_statements == statements
        assert judgment.predecessor_statements == [item["statement"] for item in owner_payload["targets"]]
        assert judgment.undecided_state == "selection remains undecided"
        assert len(judgment.predecessor_versions) == 2
    first = decision.points[0].update_meaning_judgment
    second_owner = decision.points[2].update_meaning_judgment
    assert first.predecessor_versions != second_owner.predecessor_versions
    assert first.predecessor_conditions != second_owner.predecessor_conditions
    assert first is not decision.points[1].update_meaning_judgment


@pytest.mark.parametrize("field,value", [("successor_index", True), ("successor_index", "0"), ("successor_index", 0.0),
                                        ("char_start", False), ("char_start", "0"), ("char_start", -1),
                                        ("char_end", True), ("char_end", "4"), ("char_end", 4.5),
                                        ("char_end", 0), ("char_end", -1)])
def test_ranges_require_strict_nonnegative_integers(field, value):
    span = dict(successor_index=0, char_start=0, char_end=4)
    span[field] = value
    with pytest.raises(ValidationError):
        NativeFinalStatementSpan.model_validate(span)


@pytest.mark.parametrize("start,end", [(4, 4), (8, 4)])
def test_empty_or_reversed_ranges_are_not_repaired(start, end):
    with pytest.raises(ValidationError):
        NativeFinalStatementSpan(successor_index=0, char_start=start, char_end=end)


@pytest.mark.parametrize("index,start,end", [(2, 0, 4), (0, 100, 101), (0, 0, 100),
                                         (0, 5, 6), (0, 0, 6), (0, 6, 13)])
def test_out_of_owner_or_noncanonical_ranges_fail_without_dropping(index, start, end):
    manifest, _ = fixture_manifest(outputs=["Alpha \n Beta stays local."])
    payload = native_payload(manifest)
    payload["points"][0]["update_meaning_judgment"]["condition_spans"] = [dict(
        successor_index=index, char_start=start, char_end=end)]
    with pytest.raises(ValueError):
        expanded(manifest, payload)


@pytest.mark.parametrize("invalid", ["context_owner", "context_disposition", "same_owner_context", "output_title", "output_body",
                                    "output_report", "output_order", "missing_output", "missing_predecessor", "duplicate_predecessor",
                                    "scope_text", "missing_owner", "duplicate_index", "missing_index", "extra_index", "wrong_contract"])
def test_context_and_complete_output_binding_fail_closed(invalid):
    manifest, _ = fixture_manifest()
    payload = native_payload(manifest)
    rows = manifest["candidates"]
    if invalid == "context_owner":
        for row in rows:
            row["update_context"]["owner_candidate_id"] = "another-owner"
    elif invalid == "context_disposition":
        for row in rows:
            row["update_context"]["disposition"] = "add"
    elif invalid == "same_owner_context":
        rows[1]["update_context"] = copy.deepcopy(rows[1]["update_context"])
        rows[1]["update_context"]["predecessors"][0]["statement"] = "Different original."
    elif invalid in {"output_title", "output_body", "output_report"}:
        key = {"output_title": "title", "output_body": "statement", "output_report": "source_report"}[invalid]
        rows[0]["update_context"]["successors"][0][key] = "forged"
    elif invalid == "output_order":
        rows.reverse()
    elif invalid == "missing_output":
        rows.pop()
        payload["points"].pop()
    elif invalid == "missing_predecessor":
        rows[0]["update_context"]["predecessors"] = []
    elif invalid == "duplicate_predecessor":
        rows[0]["update_context"]["predecessors"].append(copy.deepcopy(rows[0]["update_context"]["predecessors"][0]))
    elif invalid == "scope_text":
        rows[0]["scope_text"] = "different output projection"
    elif invalid == "missing_owner":
        rows[0].pop("owner_candidate_id")
    elif invalid == "duplicate_index":
        payload["points"][1]["candidate_index"] = 0
    elif invalid == "missing_index":
        payload["points"].pop()
    elif invalid == "extra_index":
        payload["points"][1]["candidate_index"] = 99
    else:
        manifest["contract_version"] = "candidate-verification-v1"
    with pytest.raises(ValueError):
        expanded(manifest, payload)


def test_incomplete_inventory_and_missing_proof_remain_missing_without_positive_synthesis():
    manifest, payloads = fixture_manifest()
    payload = native_payload(manifest)
    payload["points"][0]["update_meaning_judgment"]["inventory_complete"] = False
    payload["points"][1]["update_meaning_judgment"] = None
    decision = expanded(manifest, payload)
    assert all(point.update_meaning_judgment is None for point in decision.points)
    assert judged_update_payload(payloads[0], decision)[1] == "final_update_meaning_incomplete"
    with pytest.raises(ValidationError):
        payload["points"][0]["update_meaning_judgment"]["inventory_complete"] = "false"
        NativeFinalScopeDecision.model_validate(payload)


@pytest.mark.parametrize("relationship", ["drops_applicable_meaning", "unclear"])
def test_negative_semantic_votes_are_not_upgraded_by_valid_literal_ranges(relationship):
    manifest, payloads = fixture_manifest()
    payload = native_payload(manifest)
    for point in payload["points"]:
        point["update_meaning_judgment"]["relationship"] = relationship
    decision = expanded(manifest, payload)
    assert all(point.update_meaning_judgment.relationship == relationship for point in decision.points)
    assert not decision.points[0].update_meaning_judgment.covers([item["statement"] for item in payloads[0]["knowledge_items"]])
    assert judged_update_payload(payloads[0], decision)[1] == "final_update_meaning_incomplete"


@pytest.mark.parametrize("difference", ["condition", "undecided", "relationship", "missing"])
def test_every_output_keeps_its_own_inventory_and_shared_gate_rejects_disagreement(difference):
    manifest, payloads = fixture_manifest()
    payload = native_payload(manifest)
    proof = payload["points"][1]["update_meaning_judgment"]
    if difference == "condition":
        proof["condition_spans"] = []
    elif difference == "undecided":
        proof["undecided_span"] = dict(successor_index=0, char_start=0, char_end=5)
    elif difference == "relationship":
        proof["relationship"] = "unclear"
    else:
        payload["points"][1]["update_meaning_judgment"] = None
    decision = expanded(manifest, payload)
    assert judged_update_payload(payloads[0], decision)[1] == "final_update_meaning_incomplete"


def test_literal_preservation_does_not_override_mixed_or_unsupported_final_scope():
    manifest, payloads = fixture_manifest()
    for issue in ("temporary", "unsupported", "unclear"):
        payload = native_payload(manifest)
        part = payload["points"][0]["scope_segments"][0]
        if issue == "temporary":
            part.update(source_use="task_context", future_scope="session_only", content_role="temporary_context")
        elif issue == "unsupported":
            part["source_support"] = "unsupported"
        else:
            part.update(source_use="unclear", future_scope="unclear")
        decision = expanded(manifest, payload)
        stamped, blocked = judged_update_payload(payloads[0], decision)
        assert blocked is None
        assert verification_scope_status(decision.points[0], manifest["candidates"][0]["scope_text"]) != "source_scope_durable"
        with pytest.raises(ValueError):
            prove_supplied_final_scope(payload=stamped, judgment=decision)


def test_unicode_and_quotes_use_python_statement_coordinates_without_normalization():
    statement = '中文🚀条件：“仅离线” and "quoted" \\ literal.'
    manifest, payloads = fixture_manifest(outputs=[statement])
    payload = native_payload(manifest)
    start, end = statement.index("条件"), statement.index(" and")
    payload["points"][0]["update_meaning_judgment"]["condition_spans"] = [dict(successor_index=0, char_start=start, char_end=end)]
    decision = NativeFinalScopeDecision.model_validate_json(json.dumps(payload, ensure_ascii=False)).as_verification(manifest)
    judgment = decision.points[0].update_meaning_judgment
    assert judgment.predecessor_conditions == ['条件：“仅离线”']
    assert judgment.successor_statements == [statement]
    assert judgment.covers([statement]) and judgment.binds_predecessors(payloads[0]["targets"])
    assert statement == payloads[0]["knowledge_items"][0]["statement"]


def test_existing_endpoint_and_literal_membership_checks_still_reject_tampering():
    manifest, payloads = fixture_manifest()
    judgment = expanded(manifest).points[0].update_meaning_judgment
    wrong_statement = ["An invented successor.", payloads[0]["knowledge_items"][1]["statement"]]
    assert not judgment.covers(wrong_statement)
    changed_predecessors = copy.deepcopy(payloads[0]["targets"])
    changed_predecessors[0]["version"] = "different-current-version"
    assert not judgment.binds_predecessors(changed_predecessors)
    changed_predecessors = copy.deepcopy(payloads[0]["targets"])
    changed_predecessors[0]["statement"] = "Different original meaning."
    assert not judgment.binds_predecessors(changed_predecessors)
    malformed = judgment.model_copy(update={"predecessor_conditions": ["a descriptive condition absent from final text"]})
    assert not malformed.covers(judgment.successor_statements)


def test_bound_title_or_other_owner_text_cannot_be_selected_as_statement_range():
    manifest, _payloads = fixture_manifest(outputs=["Short."], owners=2)
    manifest["candidates"][0]["title"] = "A much longer title that is not the final statement."
    manifest["candidates"][0]["update_context"]["successors"][0]["title"] = manifest["candidates"][0]["title"]
    manifest["candidates"][0]["scope_text"] = manifest["candidates"][0]["title"] + "\n" + manifest["candidates"][0]["statement"]
    payload = native_payload(manifest)
    payload["points"][0]["update_meaning_judgment"]["condition_spans"] = [dict(successor_index=0, char_start=0, char_end=40)]
    with pytest.raises(ValueError, match="beyond its exact successor"):
        expanded(manifest, payload)


def test_report_title_body_authority_projection_is_unchanged():
    report = SourceReport(speaker="assistant", period="2024-01-01", session_id="fixture-session", source_id="fixture-source",
                          source_revision="sha256:" + "a" * 64, exchange_indexes=[1], text="Only offline behavior was reported.")
    target = dict(id="report-old", title=report.render_title(), statement=report.render_statement(),
                  topic_path=["reports"], source_report=source_report_snapshot(report))
    target["version"] = target_version(target)
    payload = dict(candidate_id="report-owner", disposition="replace", targets=[target], knowledge_items=[dict(
        title=report.render_title(), statement=report.render_statement(), topic_path=["reports"],
        claim_kind="source_report", source_report=source_report_snapshot(report))])
    manifest = dict(contract_version="final-knowledge-scope-v1", candidates=final_scope_verification_rows(payload, []))
    decision = expanded(manifest)
    assert decision.points[0].update_meaning_judgment.successor_statements == [report.render_statement()]
    manifest["candidates"][0]["source_report"]["speaker"] = "user"
    with pytest.raises(ValueError):
        expanded(manifest)


@pytest.mark.parametrize("disposition", ["add", "confirm"])
def test_add_confirmation_have_no_invented_predecessor_context(disposition):
    manifest, _payloads = fixture_manifest(disposition=disposition)
    assert all(row.get("update_context") is None for row in manifest["candidates"])
    assert all(point.update_meaning_judgment is None for point in expanded(manifest).points)
    payload = native_payload(manifest)
    other, _ = fixture_manifest()
    payload["points"][0]["update_meaning_judgment"] = native_payload(other)["points"][0]["update_meaning_judgment"]
    with pytest.raises(ValueError, match="no bound update context"):
        expanded(manifest, payload)


def test_default_canonical_and_classification_contracts_do_not_change():
    manifest, payloads = fixture_manifest()
    canonical = dict(relationship="preserves_applicable_meaning", predecessor_conditions=["only offline"],
                     predecessor_statements=[item["statement"] for item in payloads[0]["targets"]],
                     predecessor_versions=[item["version"] for item in payloads[0]["targets"]],
                     successor_statements=[item["statement"] for item in payloads[0]["knowledge_items"]],
                     undecided_state="selection remains undecided", basis="Independent canonical current-Agent judgment.")
    assert UpdateMeaningJudgment.model_validate(canonical).covers(canonical["successor_statements"])
    default = _build_verification_prompt(manifest)
    native = _build_verification_prompt(manifest, native_final_transport=True)
    assert "NativeFinalScopeDecision" not in default
    assert "NativeFinalScopeDecision" in native and "condition_spans" in native
    classification = dict(contract_version=DREAM_SOURCE_RECHECK_CONTRACT, candidates=[])
    assert _build_verification_prompt(classification) == _build_verification_prompt(classification, native_final_transport=True)
    assert "condition_spans" not in _build_verification_prompt(classification)
    schema = SourceClassificationDecision.model_json_schema()
    assert "update_meaning_judgment" not in schema["$defs"]["SourceClassificationPoint"]["properties"]


def test_repair_prompt_contract_is_only_present_for_explicit_maintenance_feedback():
    ordinary = _build_assimilation_prompt({})
    maintenance = dict(maintenance_candidates=[dict(candidate_id="fixture")])
    plain = _build_assimilation_prompt(maintenance)
    revised = _build_assimilation_prompt({**maintenance, "proposal_repair": dict(attempt=1, previous_rejections=[])})
    assert "proposal_repair is one bounded revision" not in ordinary + plain
    assert "proposal_repair is one bounded revision" in revised
    assert "untrusted feedback" in revised and "no_write/defer remain valid" in revised


@pytest.mark.parametrize("attempts", [(), (dict(call_id="same-call", status="completed", usage=dict(input_tokens=31, output_tokens=7, total_tokens=38)),)])
@pytest.mark.parametrize("fault", ["point_span", "candidate_identity"])
def test_normalization_failure_preserves_exact_completed_usage_hashes_and_attempts(tmp_path, monkeypatch, attempts, fault):
    manifest, _ = fixture_manifest()
    payload = native_payload(manifest)
    if fault == "point_span":
        payload["points"][0]["update_meaning_judgment"]["condition_spans"][0]["char_end"] = 99999
    else:
        payload["points"][0]["candidate_index"] = 99
    raw = json.dumps(payload)
    calls = []
    provider = cli.HostStructuredCliProvider(host_client="claude-code", executable="never-started")
    result = ProviderResult(decision=NativeFinalScopeDecision.model_validate(payload), provider=provider.name, model="fixture",
                            duration_seconds=42.25, input_sha256="a" * 64, response_sha256=hashlib.sha256(raw.encode()).hexdigest(),
                            input_tokens=31, output_tokens=7, total_tokens=38, event_count=1, native_attempts=attempts)
    def run(_manifest, **kwargs):
        calls.append(kwargs)
        return result
    monkeypatch.setattr(provider, "_run", run)
    if fault == "point_span":
        actual = provider.verify(manifest, runtime_dir=tmp_path)
        assert len(calls) == 1
        assert actual.decision.points[0].semantic_support == "partial"
        assert actual.decision.points[0].source_use == "unclear"
        assert actual.decision.points[0].scope_segments == []
        assert actual.decision.points[0].update_meaning_judgment is None
        assert actual.decision.points[1].semantic_support == "supported"
        assert replace(actual, decision=result.decision) == result
        return
    with pytest.raises(ProviderError) as raised:
        provider.verify(manifest, runtime_dir=tmp_path)
    assert len(calls) == 1
    error = raised.value
    assert error.failure_reason == "decision_schema"
    assert error.native_attempts == attempts
    assert error.attempt_results == (replace(result, decision=None, schema_valid=False),)
    assert error.attempt_results[0].total_tokens == 38
    assert error.attempt_results[0].duration_seconds == 42.25
    assert error.attempt_results[0].response_sha256 == hashlib.sha256(raw.encode()).hexdigest()


def test_normalization_freezes_original_request_and_copies_per_point_fields(tmp_path, monkeypatch):
    manifest, _ = fixture_manifest()
    original = copy.deepcopy(manifest)
    payload = native_payload(manifest)
    provider = cli.HostStructuredCliProvider(host_client="claude-code", executable="never-started")
    decision = NativeFinalScopeDecision.model_validate(payload)
    def run(transport_manifest, **kwargs):
        # Neither the caller's mutable object nor transport working copy may
        # substitute a different request after input/prompt binding.
        manifest["candidates"][0]["statement"] = "CALLER_MUTATED"
        transport_manifest["candidates"][0]["statement"] = "TRANSPORT_MUTATED"
        return ProviderResult(decision=decision, provider=provider.name, model=None, duration_seconds=1,
                              input_sha256="a" * 64, response_sha256="b" * 64, input_tokens=1,
                              output_tokens=1, total_tokens=2, event_count=1)
    monkeypatch.setattr(provider, "_run", run)
    result = provider.verify(manifest, runtime_dir=tmp_path)
    assert result.decision.points[0].update_meaning_judgment.successor_statements == [
        row["statement"] for row in original["candidates"][0]["update_context"]["successors"]]
    decision.points[0].scope_segments[0].text = "RESPONSE_MUTATED"
    assert result.decision.points[0].scope_segments[0].text == original["candidates"][0]["scope_text"]


@pytest.mark.parametrize("host", ["codex", "claude-code", "hermes", "opencode", "antigravity"])
def test_each_native_host_sends_and_parses_the_new_final_shape_once(tmp_path, monkeypatch, host):
    manifest, _ = fixture_manifest(outputs=['中文🚀 only "offline".'])
    payload = native_payload(manifest)
    raw = json.dumps(payload, ensure_ascii=False)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    executable = tmp_path / "bin" / "never-started.exe"
    executable.parent.mkdir()
    executable.with_name("python.exe").touch()  # Hermes' Windows preflight; never executed.
    provider = cli.HostStructuredCliProvider(host_client=host, executable=str(executable))
    calls, schemas = [], []
    monkeypatch.setattr(provider, "_run", provider._run_native_body)
    monkeypatch.setattr(cli, "_codex_background_overrides", lambda _cwd: [])
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("No process may start"))
    if host == "codex":
        class Server:
            def run(self, **kwargs):
                calls.append(kwargs)
                schemas.append(kwargs["schema"])
                return raw, dict(call_id="fixture-codex-call", status="completed", model_dispatched=True,
                                 usage=dict(input_tokens=31, output_tokens=7, total_tokens=38), event_count=1)
        provider._codex_server = Server()
    else:
        def communicate(invocation, execution_cwd, env, creationflags, prompt, started, heartbeat, stdout_file, stderr_file):
            calls.append(prompt)
            paths = list(runtime.rglob("decision.schema.json"))
            assert len(paths) == 1
            schemas.append(json.loads(paths[0].read_text(encoding="utf-8")))
            if host == "hermes":
                assert "Use this final-only shape" in prompt and "condition_spans" in prompt
                assert "owner-local successor statement" in prompt
                assert "paraphrase instead" not in prompt
                assert "standard JSON escaping" in prompt
            usage = dict(input_tokens=31, output_tokens=7, total_tokens=38)
            if invocation.output_path is not None:
                invocation.output_path.write_text(raw, encoding="utf-8")
            if host == "antigravity":
                stdout = "\n".join([json.dumps(dict(event="init", init=dict(tools=[], agent="harness-mem-worker"))),
                    json.dumps(dict(event="result", result=dict(status="SUCCESS", num_turns=1, structured_output=payload, usage=usage)))])
                stdout_file.write(stdout)
                stdout_file.flush()
                return stdout, "", 0
            return json.dumps(dict(structured_output=payload, usage=usage), ensure_ascii=False), "", 0
        monkeypatch.setattr(provider, "_communicate", communicate)
    result = provider.verify(manifest, runtime_dir=runtime)
    assert len(calls) == 1
    assert isinstance(result.decision, CandidateVerificationDecision)
    assert result.total_tokens == 38
    assert result.decision.points[0].update_meaning_judgment.successor_statements == ['中文🚀 only "offline".']
    proof = schemas[0]["$defs"]["NativeFinalUpdateMeaning"]["properties"]
    assert "condition_spans" in proof and "predecessor_conditions" not in proof


@pytest.mark.parametrize("contract", [DREAM_SOURCE_RECHECK_CONTRACT, "candidate-verification-v1"])
def test_native_final_shape_does_not_leak_into_other_host_verifications(tmp_path, monkeypatch, contract):
    provider = cli.HostStructuredCliProvider(host_client="codex", executable="never-started")
    seen = []
    decision = SourceClassificationDecision(points=[]) if contract == DREAM_SOURCE_RECHECK_CONTRACT else CandidateVerificationDecision(points=[])
    def run(_manifest, **kwargs):
        seen.append(kwargs)
        return ProviderResult(decision=decision, provider=provider.name, model=None, duration_seconds=1, input_sha256="a"*64,
                              response_sha256="b"*64, input_tokens=1, output_tokens=1, total_tokens=2, event_count=1)
    monkeypatch.setattr(provider, "_run", run)
    result = provider.verify(dict(contract_version=contract, candidates=[]), runtime_dir=tmp_path)
    assert seen[0]["decision_model"] is (SourceClassificationDecision if contract == DREAM_SOURCE_RECHECK_CONTRACT else CandidateVerificationDecision)
    assert isinstance(result.decision, CandidateVerificationDecision)
    assert "NativeFinalScopeDecision" not in seen[0]["prompt"]


def test_hermes_classification_exact_quoted_source_uses_escaping_not_paraphrase(tmp_path, monkeypatch):
    text = '中文🚀 "quoted" rule uses \\ paths.\nIts source scope stays exact.'
    payload = dict(points=[dict(candidate_index=0, semantic_support="supported", source_use="reusable_knowledge",
                               future_scope="durable", reason="Independently classify the entire quoted source scope.",
                               scope_segments=[segment(text)], claim_units=[])])
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    executable = tmp_path / "bin" / "never-started.exe"
    executable.parent.mkdir()
    executable.with_name("python.exe").touch()
    provider = cli.HostStructuredCliProvider(host_client="hermes", executable=str(executable))
    monkeypatch.setattr(provider, "_run", provider._run_native_body)
    monkeypatch.setattr(cli.subprocess, "Popen", lambda *_args, **_kwargs: pytest.fail("No process may start"))
    calls = []
    def communicate(invocation, execution_cwd, env, creationflags, prompt, started, heartbeat, stdout_file, stderr_file):
        calls.append(prompt)
        assert "standard JSON escaping" in prompt
        assert "Preserve scope_segments.text exactly" in prompt
        assert "paraphrase instead" not in prompt
        schema_path = next(runtime.rglob("decision.schema.json"))
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        assert "SourceClassificationPoint" in schema["$defs"]
        assert "NativeFinalScopePoint" not in schema["$defs"]
        return json.dumps(dict(structured_output=payload, usage=dict(input_tokens=31, output_tokens=7, total_tokens=38)), ensure_ascii=False), "", 0
    monkeypatch.setattr(provider, "_communicate", communicate)
    result = provider.verify(dict(contract_version=DREAM_SOURCE_RECHECK_CONTRACT,
                                  candidates=[dict(candidate_index=0, scope_text=text)]), runtime_dir=runtime)
    assert len(calls) == 1 and result.total_tokens == 38
    assert result.decision.points[0].scope_segments[0].text == text
    assert "paraphrase instead" in cli._hermes_output_contract(cli.AgentExtractionDecision)
