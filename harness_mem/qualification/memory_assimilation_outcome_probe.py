"""Isolated direct proof for post-verification multi-point memory assimilation."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import (
    AssimilationDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision as RuntimeAssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class _SequencedProvider:
    name = "memory-assimilation-probe"

    def __init__(self) -> None:
        self.extraction_calls = 0
        self.verification_calls = 0
        self.assimilation_calls = 0
        self.assimilation_manifest: dict[str, Any] | None = None
        self.verification_manifest: dict[str, Any] | None = None

    def decide(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        self.extraction_calls += 1
        if heartbeat is not None:
            heartbeat()
        refs = list(manifest.get("zero_candidate_exchange_refs") or [])
        if not refs:
            raise AssertionError("fixture must expose at least one user evidence window")

        def reference(index: int) -> dict[str, Any]:
            if not refs:
                return {
                    "exchange_index": max(index - 1, 0),
                    "role": "user",
                    "content_sha256": "0" * 64,
                    "kind": "user_statement",
                }
            source_ref = refs[index % len(refs)]
            return {
                "kind": "user_statement",
                "exchange_index": source_ref.get("exchange_index"),
                "content_sha256": source_ref.get("content_sha256"),
                "role": "user",
            }

        rule_trigger = _normalize_rule_trigger("When presenting a memory audit.")
        decision = AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "The session contains a new rule, an existing fact, a one-off request, and unfinished work.",
                    "final_user_request": "Improve memory presentation and retain only durable project knowledge.",
                    "final_outcome": "The durable points were classified independently.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                    "zero_candidate_challenge": None,
                },
                "candidates": [
                    _memory_candidate(reference(0), "New search projection", "Normal memory search excludes audit metadata."),
                    _memory_candidate(reference(1), "Existing search projection", "The legacy projection remains visible."),
                    _memory_candidate(reference(2), "Current list request", "Show every long-term memory now."),
                    {
                        **_evidence(reference(3)),
                        "kind": "rule",
                        "category": None,
                        "content": None,
                        "confidence": None,
                        "tags": [],
                    "pattern": "Provide an itemized list rather than aggregate counts.",
                    "trigger": rule_trigger,
                        "examples": [],
                        "source_entity": None,
                        "target_entity": None,
                        "relation_type": None,
                        "evidence": None,
                    },
                    _memory_candidate(reference(4), "Remaining rollout", "Run the remaining rollout after verification."),
                ],
            }
        )
        return _receipt(decision, provider=self.name, marker="extract")

    def assimilate(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        self.assimilation_calls += 1
        self.assimilation_manifest = manifest
        if heartbeat is not None:
            heartbeat()
        verified = list(manifest.get("verified_candidates", []))
        candidates = {
            str(item.get("candidate_id") or ""): (item.get("statement") or item.get("content") or "").strip()
            for item in verified
            if isinstance(item, dict) and str(item.get("candidate_id") or "")
        }
        current = manifest["current_truth"]
        assert len(current) == 1

        legacy_handle = current[0]["handle"]
        points: list[dict[str, Any]] = []
        for candidate_id in candidates:
            statement = candidates[candidate_id]
            if statement == "Normal memory search excludes audit metadata.":
                points.append(
                    {
                        "candidate_id": candidate_id,
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Memory search projection",
                        "canonical_statement": "Normal memory search excludes audit metadata.",
                        "topic_path": ["memory", "retrieval"],
                        "reason": "New canonical statement is needed for future retrieval.",
                    }
                )
            elif "The legacy projection remains visible." in statement:
                points.append(
                    {
                        "candidate_id": candidate_id,
                        "disposition": "confirm",
                        "matched_truth_handles": [legacy_handle],
                        "canonical_title": None,
                        "canonical_statement": None,
                        "topic_path": [],
                        "reason": "The current truth already represents this fact.",
                    }
                )
            elif "itemized list" in statement.lower():
                points.append(
                    {
                        "candidate_id": candidate_id,
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Memory audit presentation",
                        "canonical_statement": "When presenting a memory audit, provide an itemized list rather than aggregate counts.",
                        "topic_path": ["memory", "audit"],
                        "reason": "This is an explicit future preference with condition and behavior.",
                    }
                )
            elif "run the remaining rollout after verification" in statement.lower():
                points.append(
                    {
                        "candidate_id": candidate_id,
                        "disposition": "handoff",
                        "matched_truth_handles": [],
                        "canonical_title": None,
                        "canonical_statement": None,
                        "topic_path": [],
                        "reason": "The work remains unfinished and belongs to resumption state.",
                    }
                )
            else:
                raise AssertionError(f"unhandled candidate in probe manifest: {statement!r}")
        if not points:
            raise AssertionError("probe manifest contains no actionable verified candidates")
        decision = AssimilationDecision.model_validate({"points": points})
        return _receipt(decision, provider=self.name, marker="assimilate")

    def verify(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        self.verification_calls += 1
        self.verification_manifest = manifest
        if heartbeat is not None:
            heartbeat()
        points = []
        for item in manifest["candidates"]:
            statement = item.get("statement") or item.get("content") or ""
            session_only = statement == "Show every long-term memory now."
            points.append(
                {
                    "candidate_index": item["candidate_index"],
                    "semantic_support": "supported",
                    "future_scope": "session_only" if session_only else "durable",
                    "reason": (
                        "This is a one-off request for current output."
                        if session_only
                    else "The source supports a reusable project conclusion."
                    ),
                }
            )
        return _receipt(
            CandidateVerificationDecision.model_validate({"points": points}),
            provider=self.name,
            marker="verify",
        )


def _evidence(ref: dict[str, Any]) -> dict[str, Any]:
    return {
        "evidence_basis": "user_statement",
        "verification_outcome": "verified",
        "verification_reason_codes": [],
        "verification_refs": [
            {
                "kind": "user_statement",
                "exchange_index": ref["exchange_index"],
                "role": "user",
                "content_sha256": ref["content_sha256"],
            }
        ],
    }


def _memory_candidate(reference: dict[str, Any], title: str, statement: str) -> dict[str, Any]:
    del title
    return {
        **_evidence(reference),
        "kind": "memory",
        "category": "decision",
        "content": statement,
        "confidence": 0.99,
        "tags": ["memory"],
        "pattern": None,
        "trigger": None,
        "examples": None,
        "source_entity": None,
        "target_entity": None,
        "relation_type": None,
        "evidence": None,
    }


def _normalize_rule_trigger(trigger: str) -> str:
    normalized = str(trigger or "").strip()
    if normalized.lower().startswith("when "):
        normalized = normalized[5:].strip()
    return normalized


def _receipt(decision: Any, *, provider: str, marker: str) -> ProviderResult:
    return ProviderResult(
        decision=decision,
        provider=provider,
        model="deterministic",
        duration_seconds=0.01,
        input_sha256=(marker[0] * 64),
        response_sha256=(marker[-1] * 64),
        input_tokens=100,
        output_tokens=50,
        total_tokens=150,
        event_count=1,
        sandbox="no-tools",
    )


def run_memory_assimilation_outcome_probe() -> dict[str, Any]:
    with TemporaryDirectory(prefix="harness-mem-assimilation-outcome-") as temporary:
        root = Path(temporary)
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        try:
            project_name = "assimilation-probe"
            source_file = root / "README.md"
            source_file.write_text(
                "The legacy projection remains visible.\n", encoding="utf-8"
            )
            current = KnowledgeEntry(
                id="existing-search-projection",
                project_name=project_name,
                title="Existing search projection",
                statement="The legacy projection remains visible.",
                module_path=["memory", "retrieval"],
                verified_at=datetime.now(timezone.utc),
            )
            seed_candidate = KnowledgeCandidate(
                id="assimilation-probe-seed",
                project_name=project_name,
                candidate_type="memory",
                statement=current.statement,
            )
            seed_decision = RuntimeAssimilationDecision(
                id="assimilation-probe-seed-mutation",
                project_name=project_name,
                candidate_id=seed_candidate.id,
                disposition="add",
                canonical_truth_ids=[current.id],
                reason="Isolated outcome fixture seed.",
            )
            asyncio.run(
                backend.structured_store.knowledge_store.save_candidate(seed_candidate)
            )
            asyncio.run(
                backend.structured_store.knowledge_store.apply_truth_mutation(
                    candidate_before=seed_candidate,
                    candidate_after=seed_candidate.model_copy(
                        update={"status": "assimilated"}
                    ),
                    decision=seed_decision,
                    added_entries=[current],
                    predecessor_entries=[],
                    source_refs_by_entry={
                        current.id: [
                            ProjectKnowledgeSourceRef(
                                label="README.md",
                                target=source_file.as_uri(),
                                kind="repository",
                                digest="a" * 64,
                            )
                        ]
                    },
                )
            )
            asyncio.run(
                backend.structured_store.knowledge_store.cleanup_candidate(
                    seed_candidate.id
                )
            )
            transcript = "\n\n".join(
                [
                    "User: Add a reusable rule for clean memory search.\n\nAssistant: Recorded.",
                    "User: Confirm the existing search projection.\n\nAssistant: Recorded.",
                    "User: Show every long-term memory now.\n\nAssistant: Recorded.",
                    "User: In future memory audits, provide an itemized list.\n\nAssistant: Recorded.",
                    "User: Run the remaining rollout after verification.\n\nAssistant: Recorded.",
                ]
            )
            snapshot = asyncio.run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id="assimilation-session",
                        client="codex",
                        raw_content=transcript,
                        content_type="transcript",
                        timestamp=datetime.now(timezone.utc),
                        metadata={},
                    ),
                    project_name=project_name,
                    project_root=str(root),
                    client="codex",
                    session_id="assimilation-session",
                    source_kind="jsonl",
                    source_uri="file:///assimilation-session.jsonl",
                    source_text=transcript,
                )
            )
            provider = _SequencedProvider()
            result = run_autonomous_distill_batch(
                backend,
                project_name=project_name,
                project_root=root,
                config=MergedConfig(dream_auto_enabled=False),
                trigger_id="assimilation-session",
                client="codex",
                provider=provider,
                notes_dir=root / "notes",
                max_jobs=1,
                preferred_job_id=snapshot.distill_job_id,
            )
            replay_provider_calls = (
                provider.extraction_calls,
                provider.verification_calls,
                provider.assimilation_calls,
            )
            replay = run_autonomous_distill_batch(
                backend,
                project_name=project_name,
                project_root=root,
                config=MergedConfig(dream_auto_enabled=False),
                trigger_id="assimilation-session",
                client="codex",
                provider=provider,
                notes_dir=root / "notes",
                max_jobs=1,
                preferred_job_id=snapshot.distill_job_id,
            )
            job = backend.transcript_store.get_distill_job(str(snapshot.distill_job_id))
            legacy_memories = asyncio.run(
                backend.structured_store.list_memory_entries(project_name, limit=20)
            )
            legacy_rules = asyncio.run(
                backend.structured_store.list_confirmed_rules(project_name)
            )
            knowledge_entries = asyncio.run(
                backend.structured_store.knowledge_store.list_entries(project_name)
            )
            knowledge_candidates = asyncio.run(
                backend.structured_store.knowledge_store.list_candidates(project_name)
            )
            handoffs = asyncio.run(
                backend.structured_store.get_latest_handoffs(project_name, limit=20)
            )
            retrieved = asyncio.run(
                search_current_knowledge(
                    backend,
                    project_name=project_name,
                    project_root=root,
                    query="itemized list",
                    limit=10,
                )
            )
            packet = dict((job.promotion_summary if job else {}).get("answer_packet") or {})
            assimilation_manifest = provider.assimilation_manifest or {}
            result_fields = {
                "multi_point_independent": result.get("state") == "succeeded" and len(packet.get("point_results") or []) == 5,
                "add_retrievable": any(
                    item.statement == "Normal memory search excludes audit metadata."
                    for item in knowledge_entries
                ),
                "confirm_has_no_duplicate": len(knowledge_entries) == 3,
                "one_off_request_not_written": all(
                    item.statement != "Show every long-term memory now."
                    for item in knowledge_entries
                ),
                "one_off_request_excluded_from_assimilation": all(
                    item.get("statement") != "Show every long-term memory now."
                    for item in assimilation_manifest.get("verified_candidates") or []
                ),
                "handoff_job_bound": len(handoffs) == 1 and handoffs[0].context.get("distill_job_id") == snapshot.distill_job_id,
                "rule_materialized_and_normally_retrievable": any(
                    "itemized list" in item.statement for item in knowledge_entries
                ) and any("itemized list" in item.statement for item in retrieved),
                "new_session_does_not_write_legacy_truth": not legacy_memories and not legacy_rules,
                "terminal_processing_material_cleaned": not knowledge_candidates,
                "answer_packet_point_bound": {item.get("disposition") for item in packet.get("point_results") or []} == {"add", "confirm", "no_write", "handoff"},
                "assimilation_provider_isolated": bool(assimilation_manifest)
                and "transcript" not in assimilation_manifest
                and "chunks" not in assimilation_manifest,
                "replay_no_provider_recall": (
                    replay.get("outcomes") == []
                    and provider.extraction_calls == replay_provider_calls[0]
                    and provider.verification_calls == replay_provider_calls[1]
                    and provider.assimilation_calls == replay_provider_calls[2]
                ),
                "verification_provider_executed_once": provider.verification_calls == 1,
            }
            result_fields["verified"] = all(result_fields.values())
            return result_fields
        finally:
            asyncio.run(backend.close())


def main() -> int:
    result = run_memory_assimilation_outcome_probe()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
