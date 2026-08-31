"""Isolated end-to-end proof for archived-session batch distillation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, cast

from harness_mem.autonomous.models import (
    AssimilationDecision,
    AutonomousDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.autonomous.worker import read_autonomous_receipt
from harness_mem.commands.archive_distill import run_archive_distill_batch
from harness_mem.read_knowledge import search_current_knowledge
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_structured_store import LocalStructuredStore


class _DeterministicArchiveProvider:
    name = "archive-outcome-probe"

    def verify(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        if heartbeat is not None:
            heartbeat()
        decision = CandidateVerificationDecision.model_validate(
            {
                "points": [
                    {
                        "candidate_index": item["candidate_index"],
                        "semantic_support": "supported",
                        "future_scope": "durable",
                        "reason": "The source directly states a reusable testing rule.",
                    }
                    for item in manifest["candidates"]
                ]
            }
        )
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model="deterministic",
            duration_seconds=0.01,
            input_sha256="e" * 64,
            response_sha256="f" * 64,
            input_tokens=50,
            output_tokens=20,
            total_tokens=70,
            event_count=1,
        )

    def decide(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        if heartbeat is not None:
            heartbeat()
        reference = manifest["zero_candidate_exchange_refs"][0]
        decision = AutonomousDecision.model_validate(
            {
                "semantic_review": {
                    "session_summary": "The user defined a durable related-test rule.",
                    "final_user_request": "Which tests should small changes run?",
                    "final_outcome": "Small changes should run related tests.",
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                    "zero_candidate_challenge": None,
                },
                "candidates": [
                    {
                        "kind": "memory",
                        "category": "testing",
                        "content": "Small changes should run related tests.",
                        "confidence": 0.99,
                        "tags": ["tests"],
                        "evidence_basis": "user_statement",
                        "verification_outcome": "verified",
                        "verification_refs": [
                            {
                                "kind": "user_statement",
                                "exchange_index": reference["exchange_index"],
                                "role": "user",
                                "content_sha256": reference["content_sha256"],
                            }
                        ],
                        "verification_reason_codes": [],
                    }
                ],
            }
        )
        return ProviderResult(
            decision=decision,
            provider=self.name,
            model="deterministic",
            duration_seconds=0.01,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=600,
            output_tokens=120,
            total_tokens=720,
            event_count=1,
        )

    def assimilate(self, manifest: dict[str, Any], *, runtime_dir: Path, heartbeat=None):
        del runtime_dir
        if heartbeat is not None:
            heartbeat()
        points = [
            {
                "candidate_id": candidate["candidate_id"],
                "disposition": "add",
                "matched_truth_handles": [],
                "canonical_title": "Related tests",
                "canonical_statement": candidate["statement"],
                "topic_path": ["testing"],
                "reason": "The verified fixture establishes a durable project rule.",
            }
            for candidate in manifest["verified_candidates"]
        ]
        return ProviderResult(
            decision=AssimilationDecision.model_validate({"points": points}),
            provider=self.name,
            model="deterministic",
            duration_seconds=0.01,
            input_sha256="c" * 64,
            response_sha256="d" * 64,
            input_tokens=100,
            output_tokens=50,
            total_tokens=150,
            event_count=1,
        )


def _write_archive(archive_dir: Path, project_root: Path, session_id: str) -> Path:
    archive_dir.mkdir(parents=True)
    source = archive_dir / f"rollout-{session_id}.jsonl"
    records = [
        {
            "type": "session_meta",
            "payload": {
                "id": session_id,
                "cwd": str(project_root),
                "timestamp": "2026-08-13T00:00:00Z",
            },
        },
        {
            "type": "event_msg",
            "payload": {
                "turn_id": "turn-1",
                "type": "user_message",
                "message": "Small changes should always run related tests.",
            },
        },
        {
            "type": "response_item",
            "payload": {
                "turn_id": "turn-1",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "Understood."}],
            },
        },
    ]
    source.write_text(
        "\n".join(json.dumps(item) for item in records) + "\n",
        encoding="utf-8",
    )
    old = time.time() - 120
    source.touch()
    source.chmod(0o600)
    import os

    os.utime(source, (old, old))
    return source


def run_archive_distill_outcome_probe() -> dict[str, Any]:
    with TemporaryDirectory(prefix="harness-mem-archive-outcome-") as temporary:
        root = Path(temporary)
        control = root / "control"
        project = root / "project"
        archive = root / "archived_sessions"
        data = root / "data"
        notes = root / "notes"
        control.mkdir()
        project.mkdir()
        control.joinpath(".harness-mem.toml").write_text(
            "[archive_distill]\n"
            "enabled = true\n"
            "project_scope = \"all\"\n"
            "batch_size = 1\n"
            "daily_limit = 2\n"
            "require_answer_packet = true\n"
            "report_promotions = true\n",
            encoding="utf-8",
        )
        project.joinpath(".harness-mem.toml").write_text(
            "[distill]\n"
            "delete_source_after_complete = true\n\n"
            "[distill.autonomous]\n"
            "enabled = true\n",
            encoding="utf-8",
        )
        source = _write_archive(archive, project, "archive-probe")
        first = asyncio.run(
            run_archive_distill_batch(
                control_root=control,
                apply=True,
                archive_dir=archive,
                data_dir=data,
                provider=_DeterministicArchiveProvider(),
                notes_dir=notes,
                verify=True,
            )
        )
        second = asyncio.run(
            run_archive_distill_batch(
                control_root=control,
                apply=True,
                archive_dir=archive,
                data_dir=data,
                provider=_DeterministicArchiveProvider(),
                notes_dir=notes,
            )
        )
        outcome = first.get("outcomes", [{}])[0]
        autonomous_receipt = read_autonomous_receipt(
            data,
            project_name="project",
            project_root=project,
        ) or {}
        packet = dict(outcome.get("answer_packet") or {})
        note_path = Path(str((outcome.get("note") or {}).get("path") or ""))
        ledger_path = Path(str(first.get("ledger") or ""))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        backend = LocalMemoryBackend(data)
        asyncio.run(backend.init())
        try:
            structured_store = cast(LocalStructuredStore, backend.structured_store)
            completed_job = backend.transcript_store.get_distill_job(
                str(outcome.get("distill_job_id") or "")
            )
            knowledge_path = project / ".harness-mem" / "session-knowledge-base.md"
            if knowledge_path.is_file():
                knowledge_path.unlink()
            matches = asyncio.run(
                search_current_knowledge(
                    backend,
                    project_name="project",
                    project_root=project,
                    query="related tests",
                    limit=20,
                )
            )
            canonical_knowledge_count = len(
                [
                    payload
                    for payload in structured_store.list_record_payloads(
                        "knowledge_entries"
                    )
                    if payload.get("project_name") == "project"
                ]
            )
            knowledge_text = asyncio.run(
                backend.structured_store.knowledge_store.render_markdown("project")
            )
        finally:
            asyncio.run(backend.close())
        result = {
            "batch_completed": first.get("completed") == 1,
            "answer_packet_persisted": packet.get("answer_status") == "ANSWERED",
            "question_is_session_question": packet.get("question")
            == "Which tests should small changes run?",
            "promotion_visible": bool(
                packet.get("promoted_items")
                and packet["promoted_items"][0].get("fact")
                == "Small changes should run related tests."
            ),
            "note_materialized": note_path.is_file()
            and "Small changes should run related tests." in note_path.read_text(
                encoding="utf-8"
            ),
            "note_byte_hash_matches": note_path.is_file()
            and hashlib.sha256(note_path.read_bytes()).hexdigest()
            == str((outcome.get("note") or {}).get("sha256") or ""),
            "ledger_persisted": ledger.get("processed_session_ids")
            == ["archive-probe"]
            and ledger.get("attempted_session_ids") == ["archive-probe"],
            "terminal_index_persisted": Path(
                str(first.get("terminal_index") or "")
            ).is_file(),
            "replay_skipped": second.get("selected") == [],
            "truth_retrievable": any(
                item.statement == "Small changes should run related tests."
                for item in matches
            ),
            "semantic_verification_executed": bool(
                (autonomous_receipt.get("provider") or {}).get("verification")
            ),
            "sqlite_authority_persists_without_markdown": not knowledge_path.exists()
            and canonical_knowledge_count == 1,
            "markdown_projection_is_clean": "## testing" in knowledge_text
            and "Small changes should run related tests." in knowledge_text
            and all(
                marker not in knowledge_text
                for marker in (
                    "distill_job_id",
                    "candidate_id",
                    "verification_reason_codes",
                    "assimilation_disposition",
                    "稳定操作规则",
                )
            ),
            "markdown_deletion_does_not_change_retrieval": bool(matches),
            "safe_source_cleanup_reported": bool(
                completed_job
                and completed_job.source_cleanup_status in {
                    "deleted",
                    "retained",
                    "partial_failure",
                    "unsupported",
                }
            ),
            "safe_source_deleted": not source.exists(),
            "source_cleanup_status": (
                completed_job.source_cleanup_status if completed_job else None
            ),
            "run_verification_passed": (
                first.get("verification", {}).get("status") == "passed"
            ),
            "run_verification": first.get("verification"),
            "run_receipt_persisted": Path(
                str(first.get("run_receipt") or "")
            ).is_file(),
        }
        required = [
            value
            for key, value in result.items()
            if key not in {"source_cleanup_status", "run_verification"}
        ]
        result["verified"] = all(required)
        return result


def main() -> int:
    result = run_archive_distill_outcome_probe()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
