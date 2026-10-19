from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from harness_mem.autonomous.models import AgentExtractionDecision
from harness_mem.autonomous.provider import (
    _build_prompt,
    _build_verification_prompt,
    expand_agent_extraction_decision,
)
from harness_mem.autonomous.worker import (
    _build_candidate_verification_manifest,
    build_provider_manifest,
)


def _messages() -> list[tuple[str, str]]:
    """The same 28 fictional message bodies as the first repair source."""
    phrases = [
        "A cleanup rehearsal preserved original sources. It did not delete production records or authorize external access.",
        "The on-call engineer identified a missing label and filed a follow-up; this did not change the already signed operational contract.",
        "Old vendor defaults were discussed as alternatives. The user required explicit approval before replacing existing choices.",
        "A temporary test used sample rows only. Successful fixture execution must not be presented as a live rollout.",
        "A browser screenshot showed the staging timestamp. This did not establish the production time zone or delivery window.",
        "The team compared retry traces with the operator dashboard; diagnostic observations are not a policy decision.",
        "The proposed documentation grouped retention, exports, notifications and permissions for later review. No new setting was approved.",
        "The transcript includes plans, rejected options and measurements. Distinguish a current user decision from an assistant recommendation.",
    ]
    areas = [
        "reconciliation", "interface review", "incident follow-up",
        "access review", "release checklist", "data exports",
    ]
    choices = [
        0, 0, 1, 2, 3, 0, 4, 5, 4, 6, 2, 5, 3, 1,
        6, 1, 2, 2, 6, 7, 4, 4, 7, 4, 6, 1, 2, 2,
    ]
    messages = []
    for index, choice in enumerate(choices):
        body = (
            f"[000/{index:02}] {phrases[choice]} "
            f"Tracking area {areas[index % 6]}; incident sample {index}."
        )
        if index == 0:
            body = "# Native discussion 2026-04-01: Aster Harbor\nTopic: reconciliation\n" + body
        messages.append(("user" if index % 5 == 0 else "assistant", body))
    return messages


def _packet() -> dict[str, Any]:
    messages = _messages()
    exchanges = []
    for start in range(0, 28, 5):
        group = messages[start:start + 5]
        index = len(exchanges) + 1
        content = (
            f"## Exchange {index}\nUser: {group[0][1]}\n"
            f"Assistant outcome: {group[-1][1]}"
        )
        exchanges.append({
            "exchange_index": index,
            "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            "content": content,
            "preceding_assistant_messages": [body for _, body in group[1:-1]],
        })
    return {
        "semantic_evidence": {"output_exchange_count": 6},
        "semantic_decision_exchanges": exchanges,
    }


def _evidence(prompt: str) -> dict[str, Any]:
    return json.loads(prompt.split("<session_evidence>", 1)[1].split("</session_evidence>", 1)[0])


def test_worker_preserves_intermediate_assistants_and_original_bindings() -> None:
    packet = _packet()
    manifest = build_provider_manifest(packet)
    assert manifest["semantic_decision_exchanges"] == packet["semantic_decision_exchanges"]
    assert manifest["semantic_projection"]["exchange_count"] == 6


def test_complete_source_prompt_has_all_28_bodies_once_in_native_order() -> None:
    packet = _packet()
    prompt = _build_prompt(build_provider_manifest(packet))
    evidence = _evidence(prompt)
    text = "\n".join(item["content"] for item in evidence["exchanges"])
    positions = []
    for role, body in _messages():
        assert text.count(body) == 1, (role, body)
        positions.append(text.index(body))
        assert ("User: " if role == "user" else "Assistant") in text[:text.index(body)]
    assert positions == sorted(positions)
    assert not evidence["session_outline"]


@pytest.mark.parametrize("basis", ["user_statement", "transcript"])
def test_verification_preserves_full_source_and_extraction_references(
    basis: str, tmp_path: Path,
) -> None:
    packet = _packet()
    manifest = build_provider_manifest(packet)
    compact = AgentExtractionDecision.model_validate({
        "review": {
            "summary": "The source discusses approval before replacing choices.",
            "final_request": "Retain the approval requirement.",
            "actual_result": "The source was read, not independently verified yet.",
            "contradictions": [], "unfinished": [],
            "no_candidate_reason": None, "not_durable_signals": [],
        },
        "points": [{
            "kind": "memory",
            "statement": "Replacing existing choices requires explicit user approval.",
            "evidence_basis": basis,
            "exchange_indexes": list(range(1, 7)),
        }],
    })
    decision = expand_agent_extraction_decision(compact, manifest=manifest)
    candidate = decision.candidates[0]
    assert candidate.verification_outcome == "unverified"
    verification = _build_candidate_verification_manifest(
        packet=packet,
        validated_candidates=[(candidate, {
            "kind": "memory", "content": compact.points[0].statement,
        })],
        project_root=tmp_path,
    )
    prompt = _build_verification_prompt(verification)
    projected = json.loads(prompt.split("<verification_manifest>", 1)[1].split("</verification_manifest>", 1)[0])
    sources = projected["candidates"][0]["sources"]
    excerpts = {item["source_id"]: item["content"] for item in projected["source_excerpts"]}
    extraction = _evidence(_build_prompt(manifest))["exchanges"]
    text = "\n".join(excerpts[source["source_id"]] for source in sources)
    assert [source["exchange_index"] for source in sources] == list(range(1, 7))
    for source, original, extracted, ref in zip(
        sources, packet["semantic_decision_exchanges"], extraction,
        candidate.verification_refs,
    ):
        assert source["kind"] == basis == ref.kind
        assert source["content_sha256"] == original["content_sha256"] == ref.content_sha256
        assert excerpts[source["source_id"]] == extracted["content"]
    assert all(text.count(body) == 1 for _, body in _messages())
    assert [text.index(body) for _, body in _messages()] == sorted(text.index(body) for _, body in _messages())


def test_complete_windows_do_not_resend_the_outline() -> None:
    packet = _packet()
    packet["semantic_evidence"]["chunks"] = [{"content": "duplicated outline"}]
    manifest = build_provider_manifest(packet)
    assert manifest["semantic_projection"]["chunks"] == []
    packet["semantic_decision_exchanges"].pop()
    assert build_provider_manifest(packet)["semantic_projection"]["chunks"] == ["duplicated outline"]


def test_verifier_keeps_uncited_context_and_shares_exact_excerpts(tmp_path: Path) -> None:
    packet = _packet()
    candidates = []
    for statement in ("Cedar allows optional audit exports.", "Cedar has not decided an archive period."):
        compact = AgentExtractionDecision.model_validate({
            "review": {"summary": "A scoped export policy and a known unknown were discussed.",
                "final_request": "Retain the exact approved state.", "actual_result": "The decisions were recorded.",
                "contradictions": [], "unfinished": [], "no_candidate_reason": None, "not_durable_signals": []},
            "points": [{"kind": "memory", "statement": statement, "evidence_basis": "user_statement",
                        "exchange_indexes": [2]}],
        })
        candidate = expand_agent_extraction_decision(compact, manifest=build_provider_manifest(packet)).candidates[0]
        candidates.append((candidate, {"kind": "memory", "content": statement}))
    manifest = _build_candidate_verification_manifest(packet=packet, validated_candidates=candidates,
                                                      project_root=tmp_path)
    assert len(manifest["session_context"]) == 6
    assert all([source["exchange_index"] for source in item["sources"]] == [2] for item in manifest["candidates"])
    prompt = _build_verification_prompt(manifest)
    projected = json.loads(prompt.split("<verification_manifest>")[1].split("</verification_manifest>")[0])
    assert len(projected["source_excerpts"]) == 6
    assert projected["candidates"][0]["sources"][0]["source_id"] == projected["candidates"][1]["sources"][0]["source_id"]
    text = "\n".join(row["content"] for row in projected["source_excerpts"])
    for _, body in _messages():
        assert text.count(body) == 1
    # Exact original reference kinds/digests survive independently of context.
    assert all(row["sources"][0]["kind"] == "user_statement" for row in projected["candidates"])
    assert projected["candidates"][0]["sources"][0]["content_sha256"] == packet["semantic_decision_exchanges"][1]["content_sha256"]


def test_prompt_preserves_multiline_long_and_repeated_distinct_turns() -> None:
    middle = "Same assistant text\n" + "完整正文 " * 12000
    item = {
        "exchange_index": 1,
        "content": "## Exchange 1\nUser: first\nsecond\nAssistant outcome: final\nline",
        "preceding_assistant_messages": [middle, middle],
    }
    evidence = _evidence(_build_prompt({"semantic_decision_exchanges": [item]}))
    content = evidence["exchanges"][0]["content"]
    assert content == (
        "## Exchange 1\nUser: first\nsecond\nAssistant: " + middle
        + "\nAssistant: " + middle + "\nAssistant outcome: final\nline"
    )


@pytest.mark.parametrize("content", [
    "## Exchange 1\nUser: missing outcome",
    "## Exchange 1\nUser: quoted\nAssistant outcome: quoted\nAssistant outcome: real",
])
def test_ambiguous_role_boundary_fails_instead_of_reordering(content: str) -> None:
    with pytest.raises(ValueError, match="assistant outcome boundary"):
        _build_prompt({"semantic_decision_exchanges": [{
            "exchange_index": 1,
            "content": content,
            "preceding_assistant_messages": ["intermediate"],
        }]})
