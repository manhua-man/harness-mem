"""Residual audit transport preserves sealed positives and all admission gates."""

from copy import deepcopy
import hashlib
import json
import pytest
from harness_mem.autonomous.models import (
    NativeResidualSourceCoverageExtractionDecision,
    NativeSourceCoverageVerificationDecision,
)
from harness_mem.autonomous.provider import (
    _coverage_digest,
    _build_prompt,
    _build_verification_prompt,
    expand_agent_extraction_decision,
    expand_source_coverage_verification_decision,
    get_source_coverage_inventory,
    get_source_coverage_audit_binding,
    source_coverage_audit_has_unresolved,
    source_coverage_audit_binding_block,
)
from test_source_coverage_inventory_transport import fixture


def residual():
    manifest, original = fixture(zero=True)
    source = manifest["source_coverage"]["inventory_input"]
    windows = original["inventory"]
    repair = {
        "contract": "source-coverage-residual-audit-v1",
        "origin_run_id": "old-run",
        "origin_state_sha256": "a" * 64,
        "origin_windows": deepcopy(windows),
        "origin_audit": [
            {"w": i, "span_index": 0, "verdict": "unclear" if i == 0 else "supported"}
            for i in range(3)
        ],
        "pending_spans": [
            {"w": 0, "span_index": 0, "s": 0, "e": len(source["windows"][0]["text"])}
        ],
        "retained_spans": [
            {
                "w": i,
                "span_index": 0,
                "span": deepcopy(windows[i]["spans"][0]),
                "basis_sha256": "b" * 64,
            }
            for i in (1, 2)
        ],
        "original_context_binding": {
            key: source[key]
            for key in ["source_id", "source_revision", "context_sha256"]
        },
        "already_applied_truth_ids": ["current-0"],
    }
    repair["reuse_binding_sha256"] = _coverage_digest(repair)
    manifest["source_coverage"]["inventory_audit_repair"] = repair
    payload = {
        "extraction": {"review": original["review"], "points": []},
        "patches": [{"w": 0, "span_index": 0, "spans": deepcopy(windows[0]["spans"])}],
    }
    return manifest, payload


def verify_manifest(manifest, decision):
    value = deepcopy(manifest)
    value.update(contract_version="candidate-semantic-verification-v2", candidates=[])
    value["source_coverage"]["inventory"] = get_source_coverage_inventory(decision)
    return value


def test_residual_native_only_judges_pending_and_old_positive_votes_remain_bound():
    manifest, payload = residual()
    decision = expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
        manifest=manifest,
    )
    verification = verify_manifest(manifest, decision)
    native = NativeSourceCoverageVerificationDecision(
        points=[], audit=[{"w": 0, "span_index": 0, "verdict": "supported"}]
    )
    result = expand_source_coverage_verification_decision(native, manifest=verification)
    binding = get_source_coverage_audit_binding(result, verification)
    assert len(binding["audit"]) == 3 and not source_coverage_audit_has_unresolved(
        binding
    )
    assert len(binding["windows"]) == 3 and not binding["extracted_point_sha256"]
    assert "NativeResidualSourceCoverageExtractionDecision" in _build_prompt(manifest)
    assert "required_residual_audit_spans" in _build_verification_prompt(verification)


@pytest.mark.parametrize(
    "fault", ["missing", "duplicate", "outside", "gap", "overflow"]
)
def test_residual_rejects_incomplete_or_expanded_patches(fault):
    manifest, payload = residual()
    if fault == "missing":
        payload["patches"] = []
    elif fault == "duplicate":
        payload["patches"] *= 2
    elif fault == "outside":
        payload["patches"][0]["w"] = 1
    elif fault == "gap":
        payload["patches"][0]["spans"][0]["s"] = 1
    else:
        payload["patches"][0]["spans"][0]["e"] += 1
    with pytest.raises(ValueError, match="residual_patch"):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )


@pytest.mark.parametrize(
    "fault", ["basis", "context", "old_negative", "retained_extract"]
)
def test_residual_rejects_invalid_inheritance(fault):
    manifest, payload = residual()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    if fault == "basis":
        repair["origin_state_sha256"] = "c" * 64
    elif fault == "context":
        repair["original_context_binding"]["source_revision"] = "other"
    elif fault == "old_negative":
        repair["origin_audit"][1]["verdict"] = "unclear"
        repair["reuse_binding_sha256"] = _coverage_digest(
            {k: v for k, v in repair.items() if k != "reuse_binding_sha256"}
        )
    else:
        repair["origin_windows"][1]["spans"][0]["d"] = "extract"
        repair["reuse_binding_sha256"] = _coverage_digest(
            {k: v for k, v in repair.items() if k != "reuse_binding_sha256"}
        )
    with pytest.raises(ValueError, match="residual_"):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )


@pytest.mark.parametrize(
    "audit",
    [
        [],
        [{"w": 0, "span_index": 0, "verdict": "supported"}] * 2,
        [
            {"w": 0, "span_index": 0, "verdict": "supported"},
            {"w": 1, "span_index": 0, "verdict": "supported"},
        ],
    ],
)
def test_residual_requires_exact_new_native_audit_without_claiming_old_votes(audit):
    manifest, payload = residual()
    decision = expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
        manifest=manifest,
    )
    with pytest.raises(ValueError, match="residual_independent_audit"):
        expand_source_coverage_verification_decision(
            NativeSourceCoverageVerificationDecision(points=[], audit=audit),
            manifest=verify_manifest(manifest, decision),
        )


def test_zero_candidate_negative_residual_audit_stays_unresolved():
    manifest, payload = residual()
    decision = expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
        manifest=manifest,
    )
    verification = verify_manifest(manifest, decision)
    result = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision(
            points=[], audit=[{"w": 0, "span_index": 0, "verdict": "unclear"}]
        ),
        manifest=verification,
    )
    with pytest.raises(ValueError, match="audit_unresolved"):
        get_source_coverage_audit_binding(result, verification)


def committed_residual():
    manifest, payload = residual()
    scope = manifest["source_coverage"]
    source = scope["inventory_input"]
    repair = scope["inventory_audit_repair"]
    old = repair["origin_windows"][1]["spans"][0]
    old.update(d="extract", p=[0], c=[], r=[])
    repair["origin_candidate_ids"] = ["old-committed-point"]
    proof = {
        "w": 1,
        "span_index": 0,
        "s": old["s"],
        "e": old["e"],
        "original_point_indexes": [0],
        "candidate_ids": ["old-committed-point"],
        "truth_ids": ["current-0"],
        "truth_bindings": [
            {
                "id": "current-0",
                "current_index": 0,
                "scope_sha256": _coverage_digest(source["current"][0]),
                "payload_sha256": "d" * 64,
                "sources_sha256": "e" * 64,
            }
        ],
        "commit_bindings": [
            {
                "candidate_id": "old-committed-point",
                "decision_id": "old-commit",
                "truth_ids": ["current-0"],
                "truth_sha256": ["f" * 64],
            }
        ],
    }
    proof["basis_sha256"] = _coverage_digest(proof)
    repair["committed_point_spans"] = [proof]
    repair["retained_spans"][0]["span"] = {**old, "d": "covered", "p": [], "c": [0]}
    repair["reuse_binding_sha256"] = _coverage_digest(
        {key: value for key, value in repair.items() if key != "reuse_binding_sha256"}
    )
    return manifest, payload


def test_committed_point_ranges_become_protected_current_coverage_without_reextraction():
    manifest, payload = committed_residual()
    decision = expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
        manifest=manifest,
    )
    assert not decision.candidates
    span = get_source_coverage_inventory(decision)["windows"][1]["spans"][0]
    assert span["d"] == "covered" and span["c"] == [0] and not span["p"]
    verification = verify_manifest(manifest, decision)
    result = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision(
            points=[], audit=[{"w": 0, "span_index": 0, "verdict": "supported"}]
        ),
        manifest=verification,
    )
    assert len(get_source_coverage_audit_binding(result, verification)["audit"]) == 3


def test_native_cannot_patch_a_committed_point_into_a_duplicate_candidate():
    manifest, payload = committed_residual()
    payload["patches"].append(
        {
            "w": 1,
            "span_index": 0,
            "spans": [
                manifest["source_coverage"]["inventory_audit_repair"]["origin_windows"][
                    1
                ]["spans"][0]
            ],
        }
    )
    with pytest.raises(ValueError, match="residual_patch_changed"):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )


def test_native_cannot_add_an_unlinked_old_committed_point():
    manifest, payload = committed_residual()
    _manifest, original = fixture()
    point = deepcopy(original["points"][0])
    point["exchange_indexes"] = [2]
    payload["extraction"]["review"]["no_candidate_reason"] = None
    payload["extraction"]["points"] = [point]
    with pytest.raises(ValueError, match="inventory must link every extracted point"):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )


@pytest.mark.parametrize(
    "fault",
    ["old_point", "truth_scope", "commit", "not_supported", "pending", "extract"],
)
def test_committed_inheritance_rejects_changed_or_unproved_protection(fault):
    manifest, payload = committed_residual()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    proof = repair["committed_point_spans"][0]
    if fault == "old_point":
        proof["candidate_ids"] = ["other-candidate"]
    elif fault == "truth_scope":
        proof["truth_bindings"][0]["scope_sha256"] = "a" * 64
    elif fault == "commit":
        proof["commit_bindings"] = []
    elif fault == "not_supported":
        repair["origin_audit"][1]["verdict"] = "unclear"
    elif fault == "pending":
        repair["pending_spans"].append(
            {key: proof[key] for key in ("w", "span_index", "s", "e")}
        )
    else:
        repair["retained_spans"][0]["span"] = deepcopy(
            repair["origin_windows"][1]["spans"][0]
        )
    proof["basis_sha256"] = _coverage_digest(
        {key: value for key, value in proof.items() if key != "basis_sha256"}
    )
    repair["reuse_binding_sha256"] = _coverage_digest(
        {key: value for key, value in repair.items() if key != "reuse_binding_sha256"}
    )
    with pytest.raises(ValueError, match="residual_"):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )


def recovered_residual():
    manifest, payload = committed_residual()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    repair["task_scope"] = "original-cumulative-account"
    repair["original_context_binding"]["source_job_id"] = "source-job"
    row = repair["committed_point_spans"][0]
    row.update(writing_candidate_ids=["recovered-writer"], recovery_run_id="recovery-run")
    current = manifest["source_coverage"]["inventory_input"]["current"][0]
    semantic = _coverage_digest({key: current.get(key) for key in ("title", "statement", "topic_path", "source_report")})
    sources = [dict(source_id="canonical-source", knowledge_id="current-0", payload_sha256="a" * 64)]
    truth = dict(id="current-0", payload_sha256="b" * 64, scope_sha256=semantic, sources=sources)
    commit = dict(candidate_id="recovered-writer", original_candidate_id="old-committed-point", status="applied",
        decision_id="recovered-commit", point_sha256="c" * 64, truth_ids=["current-0"],
        truth_semantic_sha256=[semantic], truth_payload_sha256=[row["truth_bindings"][0]["payload_sha256"]],
        truth_bindings=[truth], transaction_sha256="d" * 64, sources=sources)
    point = dict(disposition="add", point_sha256=commit["point_sha256"], truth_ids=["current-0"], truth_bindings=[truth])
    resolved = dict(original_candidate_id="old-committed-point", writing_candidate_id="recovered-writer",
        handoff_id="original-handoff", original_binding=dict(original_candidate_id="old-committed-point",
            mode="retained_workspace", handoff_id="original-handoff"), writing_candidate_sha256="e" * 64,
        writing_evidence_sha256="f" * 64, point_proofs=[point], commit_bindings=[commit])
    repair["resolved_handoff_proof"] = dict(contract="explicit-source-handoff-recovery-v1",
        recovery_run_id="recovery-run", origin_run_id=repair["origin_run_id"], task_scope=repair["task_scope"],
        source_job_id="source-job", source_id=repair["original_context_binding"]["source_id"],
        source_revision=repair["original_context_binding"]["source_revision"], binding_sha256="1" * 64,
        payload_sha256="2" * 64, resolved=[resolved])
    row["commit_bindings"] = [commit]
    seal_recovery(manifest)
    return manifest, payload


def seal_recovery(manifest):
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    row = repair["committed_point_spans"][0]
    repair["resolved_handoff_proof_sha256"] = _coverage_digest(repair["resolved_handoff_proof"])
    row["recovery_proof_sha256"] = repair["resolved_handoff_proof_sha256"]
    row["basis_sha256"] = _coverage_digest({key: value for key, value in row.items() if key != "basis_sha256"})
    repair["reuse_binding_sha256"] = _coverage_digest({key: value for key, value in repair.items()
                                                      if key != "reuse_binding_sha256"})


def test_recovered_writing_candidate_commit_covers_original_point_without_reextracting():
    manifest, payload = recovered_residual()
    decision = expand_agent_extraction_decision(NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
                                                manifest=manifest)
    assert not decision.candidates
    span = get_source_coverage_inventory(decision)["windows"][1]["spans"][0]
    assert span["d"] == "covered" and not span["p"]
    verification = verify_manifest(manifest, decision)
    result = expand_source_coverage_verification_decision(NativeSourceCoverageVerificationDecision(
        points=[], audit=[dict(w=0, span_index=0, verdict="supported")]), manifest=verification)
    assert len(get_source_coverage_audit_binding(result, verification)["audit"]) == 3


@pytest.mark.parametrize("fault", ["proof_hash", "account", "origin", "source", "revision", "job", "run",
    "old_mapping", "writer", "handoff", "duplicate_resolved", "nonwrite", "missing_commit", "extra_commit",
    "point_pairing", "semantic", "payload", "transaction", "status", "source_proof", "downgrade"])
def test_recovered_protection_rejects_changed_scope_mapping_or_unproved_writes(fault):
    manifest, payload = recovered_residual()
    repair = manifest["source_coverage"]["inventory_audit_repair"]
    row = repair["committed_point_spans"][0]
    proof = repair["resolved_handoff_proof"]
    resolved = proof["resolved"][0]
    commit = resolved["commit_bindings"][0]
    if fault in {"account", "origin", "source", "revision", "job", "run"}:
        key = dict(account="task_scope", origin="origin_run_id", source="source_id", revision="source_revision",
                   job="source_job_id", run="recovery_run_id")[fault]
        proof[key] = "other"
    elif fault == "old_mapping":
        resolved["original_candidate_id"] = "other-original"
    elif fault == "writer":
        resolved["writing_candidate_id"] = "other-writer"
    elif fault == "handoff":
        resolved["original_binding"]["handoff_id"] = "other-handoff"
    elif fault == "duplicate_resolved":
        proof["resolved"] *= 2
    elif fault == "nonwrite":
        resolved["point_proofs"][0]["disposition"] = "no_write"
    elif fault == "missing_commit":
        resolved["commit_bindings"] = []
    elif fault == "extra_commit":
        resolved["commit_bindings"] = [commit, deepcopy(commit)]
    elif fault == "point_pairing":
        resolved["point_proofs"][0]["point_sha256"] = "4" * 64
    elif fault == "semantic":
        commit["truth_semantic_sha256"] = ["5" * 64]
    elif fault == "payload":
        commit["truth_payload_sha256"] = ["6" * 64]
    elif fault == "transaction":
        commit.pop("transaction_sha256")
    elif fault == "status":
        commit["status"] = "committing"
    elif fault == "source_proof":
        commit["truth_bindings"][0]["sources"][0]["knowledge_id"] = "foreign-truth"
    seal_recovery(manifest)
    if fault == "downgrade":
        for key in ("writing_candidate_ids", "recovery_run_id", "recovery_proof_sha256"):
            row.pop(key, None)
        row["basis_sha256"] = _coverage_digest({k: v for k, v in row.items() if k != "basis_sha256"})
        repair["reuse_binding_sha256"] = _coverage_digest({k: v for k, v in repair.items() if k != "reuse_binding_sha256"})
    if fault == "proof_hash":
        row["recovery_proof_sha256"] = "7" * 64
        row["basis_sha256"] = _coverage_digest({k: v for k, v in row.items() if k != "basis_sha256"})
        repair["reuse_binding_sha256"] = _coverage_digest({k: v for k, v in repair.items() if k != "reuse_binding_sha256"})
    with pytest.raises(ValueError, match="residual_"):
        expand_agent_extraction_decision(NativeResidualSourceCoverageExtractionDecision.model_validate(payload), manifest=manifest)


def later_correction():
    manifest, payload = residual()
    scope = manifest["source_coverage"]
    repair = scope["inventory_audit_repair"]
    source = scope["inventory_input"]
    repair["original_context_binding"].update(
        session_id="original-session",
        client="codex",
        project_name="demo",
        project_root_sha256="a" * 64,
    )
    text = "Withdraw the earlier local constraint for this repair."
    body = dict(
        role="user",
        context_scope="complete-authored-user-v1",
        project_name="demo",
        source_id=source["source_id"],
        source_revision="strict-later-revision",
        session_id="original-session",
        authored_exchanges=[
            {"exchange_index": row["exchange_index"], "messages": [row["text"]]}
            for row in source["windows"]
        ]
        + [{"exchange_index": 4, "messages": [text]}],
    )
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    packet = dict(
        contract="source-coverage-later-users-v1",
        content=content,
        context_sha256=hashlib.sha256(content.encode()).hexdigest(),
        original_context_sha256=source["context_sha256"],
        **{
            key: repair["original_context_binding"][key]
            for key in (
                "source_id",
                "session_id",
                "client",
                "project_name",
                "project_root_sha256",
            )
        },
        source_revision=body["source_revision"],
    )
    source["later_user_contexts"] = [packet]
    repair["later_user_contexts"] = [packet]
    repair["reuse_binding_sha256"] = _coverage_digest(
        {key: value for key, value in repair.items() if key != "reuse_binding_sha256"}
    )
    payload["patches"][0]["spans"] = [
        {
            "s": 0,
            "e": len(source["windows"][0]["text"]),
            "d": "superseded",
            "p": [],
            "c": [],
            "r": [
                {
                    "context_sha256": packet["context_sha256"],
                    "exchange_index": 4,
                    "message_index": 0,
                    "content_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "s": 0,
                    "e": len(text),
                }
            ],
        }
    ]
    return manifest, payload


def test_later_correction_is_separate_source_not_an_extension_of_old_window_indexes():
    manifest, payload = later_correction()
    decision = expand_agent_extraction_decision(
        NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
        manifest=manifest,
    )
    assert len(get_source_coverage_inventory(decision)["windows"]) == 3
    assert not decision.candidates
    verification = verify_manifest(manifest, decision)
    verified = expand_source_coverage_verification_decision(
        NativeSourceCoverageVerificationDecision(
            points=[], audit=[{"w": 0, "span_index": 0, "verdict": "supported"}]
        ),
        manifest=verification,
    )
    binding = get_source_coverage_audit_binding(verified, verification)
    assert not source_coverage_audit_has_unresolved(binding)
    assert source_coverage_audit_binding_block(binding, verification) is None
    assert "strict-later-revision" in _build_prompt(manifest)


@pytest.mark.parametrize(
    "fault",
    [
        "hash",
        "old_exchange",
        "text_hash",
        "range",
        "session",
        "prefix",
        "role",
        "binding",
    ],
)
def test_later_correction_rejects_unbound_changed_or_nonlater_evidence(fault):
    manifest, payload = later_correction()
    scope = manifest["source_coverage"]
    repair = scope["inventory_audit_repair"]
    packet = scope["inventory_input"]["later_user_contexts"][0]
    ref = payload["patches"][0]["spans"][0]["r"][0]
    if fault == "hash":
        packet["context_sha256"] = "e" * 64
    elif fault == "old_exchange":
        ref["exchange_index"] = 2
    elif fault == "text_hash":
        ref["content_sha256"] = "e" * 64
    elif fault == "range":
        ref["e"] += 1
    elif fault == "session":
        packet["session_id"] = "foreign-session"
    elif fault in {"prefix", "role"}:
        body = json.loads(packet["content"])
        if fault == "prefix":
            body["authored_exchanges"][0]["messages"][0] = "Changed old user text."
        else:
            body["role"] = "assistant"
        packet["content"] = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        packet["context_sha256"] = hashlib.sha256(
            packet["content"].encode()
        ).hexdigest()
        ref["context_sha256"] = packet["context_sha256"]
    else:
        repair["later_user_contexts"] = []
    repair["reuse_binding_sha256"] = _coverage_digest(
        {key: value for key, value in repair.items() if key != "reuse_binding_sha256"}
    )
    with pytest.raises(
        ValueError, match="source coverage correction|source_coverage_later_"
    ):
        expand_agent_extraction_decision(
            NativeResidualSourceCoverageExtractionDecision.model_validate(payload),
            manifest=manifest,
        )
