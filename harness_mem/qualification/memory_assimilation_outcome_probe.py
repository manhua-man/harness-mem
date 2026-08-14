"""Isolated direct proof for post-verification multi-point memory assimilation."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.autonomous.models import AssimilationDecision, AutonomousDecision
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.commands.wake import build_wake_snapshot
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class _SequencedProvider:
    name = "memory-assimilation-probe"

    def __init__(self) -> None:
        self.extraction_calls = 0
        self.assimilation_calls = 0
        self.assimilation_manifest: dict[str, Any] | None = None

    def decide(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        self.extraction_calls += 1
        if heartbeat is not None:
            heartbeat()
        refs = list(manifest["zero_candidate_exchange_refs"])
        if not refs:
            raise AssertionError("fixture must expose at least one user evidence window")

        def reference(index: int) -> dict[str, Any]:
            return refs[index % len(refs)]
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
                        "trigger": "When presenting a memory audit.",
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
        candidates = {item["statement"]: item["candidate_id"] for item in manifest["verified_candidates"]}
        current = manifest["current_truth"]
        assert len(current) == 1
        decision = AssimilationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_id": candidates["Normal memory search excludes audit metadata."],
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Memory search projection",
                        "canonical_statement": "Normal memory search excludes audit metadata.",
                        "topic_path": ["memory", "retrieval"],
                        "reason": "New canonical statement is needed for future retrieval.",
                    },
                    {
                        "candidate_id": candidates["The legacy projection remains visible."],
                        "disposition": "confirm",
                        "matched_truth_handles": [current[0]["handle"]],
                        "canonical_title": None,
                        "canonical_statement": None,
                        "topic_path": [],
                        "reason": "The current truth already represents this fact.",
                    },
                    {
                        "candidate_id": candidates["Show every long-term memory now."],
                        "disposition": "no_write",
                        "matched_truth_handles": [],
                        "canonical_title": None,
                        "canonical_statement": None,
                        "topic_path": [],
                        "reason": "This is only a request for the current output.",
                    },
                    {
                        "candidate_id": _candidate_id_by_prefix(candidates, "When When presenting"),
                        "disposition": "add",
                        "matched_truth_handles": [],
                        "canonical_title": "Memory audit presentation",
                        "canonical_statement": "When presenting a memory audit, provide an itemized list rather than aggregate counts.",
                        "topic_path": ["memory", "audit"],
                        "reason": "This is an explicit future preference with condition and behavior.",
                    },
                    {
                        "candidate_id": candidates["Run the remaining rollout after verification."],
                        "disposition": "handoff",
                        "matched_truth_handles": [],
                        "canonical_title": None,
                        "canonical_statement": "Run the remaining rollout after verification.",
                        "topic_path": [],
                        "reason": "The work remains unfinished and belongs to resumption state.",
                    },
                ]
            }
        )
        return _receipt(decision, provider=self.name, marker="assimilate")


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
        "assimilation_disposition": "add",
        "assimilation_reason": "Initial extraction hint only.",
        "canonical_title": None,
        "topic_path": [],
    }


def _memory_candidate(reference: dict[str, Any], title: str, statement: str) -> dict[str, Any]:
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
        "canonical_title": title,
    }


def _candidate_id_by_prefix(candidates: dict[str, str], prefix: str) -> str:
    values = [value for statement, value in candidates.items() if statement.startswith(prefix)]
    if len(values) != 1:
        raise AssertionError(f"expected one candidate for {prefix!r}, got {len(values)}")
    return values[0]


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
            current = MemoryEntry(
                id="existing-search-projection",
                project_name=project_name,
                category="decision",
                content="The legacy projection remains visible.",
                source="fixture",
                status="auto_confirmed",
            )
            asyncio.run(backend.structured_store.save_memory_entry(current))
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
            memories = asyncio.run(
                backend.structured_store.list_memory_entries(project_name, limit=20)
            )
            rules = asyncio.run(backend.structured_store.list_confirmed_rules(project_name))
            handoffs = asyncio.run(
                backend.structured_store.get_latest_handoffs(project_name, limit=20)
            )
            wake = asyncio.run(build_wake_snapshot(backend, project_name))
            packet = dict((job.promotion_summary if job else {}).get("answer_packet") or {})
            assimilation_manifest = provider.assimilation_manifest or {}
            result_fields = {
                "multi_point_independent": result.get("state") == "succeeded" and len(packet.get("point_results") or []) == 5,
                "add_retrievable": any(item.content == "Normal memory search excludes audit metadata." for item in memories),
                "confirm_has_no_duplicate": len(memories) == 2,
                "one_off_request_not_written": all(item.content != "Show every long-term memory now." for item in memories),
                "handoff_job_bound": len(handoffs) == 1 and handoffs[0].context.get("distill_job_id") == snapshot.distill_job_id,
                "rule_materialized_and_wake_readable": len(rules) == 1 and any("itemized list" in json.dumps(section) for section in wake["wake_sections"]),
                "answer_packet_point_bound": {item.get("disposition") for item in packet.get("point_results") or []} == {"add", "confirm", "no_write", "handoff"},
                "assimilation_provider_isolated": bool(assimilation_manifest)
                and "transcript" not in assimilation_manifest
                and "chunks" not in assimilation_manifest,
                "replay_no_provider_recall": replay.get("outcomes") == [] and provider.extraction_calls == 1 and provider.assimilation_calls == 1,
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
