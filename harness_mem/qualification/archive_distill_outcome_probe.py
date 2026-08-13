"""Isolated end-to-end proof for archived-session batch distillation."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.autonomous.models import AutonomousDecision
from harness_mem.autonomous.provider import ProviderResult
from harness_mem.commands.archive_distill import run_archive_distill_batch
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


class _DeterministicArchiveProvider:
    name = "archive-outcome-probe"

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
            "batch_size = 1\n"
            "daily_limit = 2\n"
            "allowed_project_roots = [\"" + project.as_posix() + "\"]\n"
            "require_answer_packet = true\n"
            "report_promotions = true\n",
            encoding="utf-8",
        )
        project.joinpath(".harness-mem.toml").write_text(
            "[distill.autonomous]\nenabled = true\n",
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
        packet = dict(outcome.get("answer_packet") or {})
        note_path = Path(str((outcome.get("note") or {}).get("path") or ""))
        ledger_path = Path(str(first.get("ledger") or ""))
        ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
        backend = LocalMemoryBackend(data)
        asyncio.run(backend.init())
        try:
            completed_job = backend.transcript_store.get_distill_job(
                str(outcome.get("distill_job_id") or "")
            )
            matches = asyncio.run(
                backend.structured_store.search_memory_entries(
                    "related tests",
                    project_name="project",
                )
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
            "ledger_persisted": ledger.get("processed_session_ids")
            == ["archive-probe"],
            "replay_skipped": second.get("selected") == [],
            "truth_retrievable": any(
                item.content == "Small changes should run related tests."
                for item in matches
            ),
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
            "run_receipt_persisted": Path(
                str(first.get("run_receipt") or "")
            ).is_file(),
        }
        required = [value for key, value in result.items() if key != "source_cleanup_status"]
        result["verified"] = all(required)
        return result


def main() -> int:
    result = run_archive_distill_outcome_probe()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
