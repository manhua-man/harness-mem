"""Deterministic runtime proof for partial distill and job-bound handoffs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import governance_handlers, tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def run_distill_outcome_probe() -> dict[str, Any]:
    """Run the real govern/finalize path against an isolated durable store."""

    with TemporaryDirectory(prefix="harness-mem-distill-outcome-") as temporary:
        root = Path(temporary)
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        previous_backend_provider = tool_handlers._backend_provider
        previous_observer_provider = tool_handlers._observer_data_dir_provider
        previous_cost_provider = tool_handlers._cost_surface_budgets_provider
        previous_logger = tool_handlers.logger
        tool_handlers.configure_tool_handler_dependencies(
            backend_provider=lambda: backend,
            observer_data_dir=lambda: backend.data_dir,
            cost_surface_budgets=lambda _project_name: None,
            logger_instance=logging.getLogger("harness_mem.distill_outcome_probe"),
        )
        try:
            session_id = "qualification-partial-handoff"
            snapshot = asyncio.run(
                persist_session_snapshot(
                    backend,
                    Observation(
                        session_id=session_id,
                        client="cursor",
                        raw_content="verified decision plus unfinished follow-up",
                        content_type="transcript",
                        metadata={},
                    ),
                    project_name="outcome-probe",
                    project_root=str(root),
                    client="cursor",
                    session_id=session_id,
                    source_kind="jsonl",
                    source_uri="file:///qualification-partial-handoff.jsonl",
                    source_text=(
                        "User: retain the verified decision.\n\n"
                        "Assistant: the decision is verified; follow-up remains.\n\n"
                    ),
                )
            )
            job_id = str(snapshot.distill_job_id or "")
            prepared = tool_handlers.tool_prepare_session_distill(
                project_name="outcome-probe",
                project_root=str(root),
                client="cursor",
                run_ingest=False,
                evidence_mode="semantic",
            )

            evidence_path = root / "verified-decision.txt"
            evidence_path.write_text(
                "The isolated outcome probe verifies one durable decision.",
                encoding="utf-8",
            )
            candidate = governance_handlers.tool_suggest_memory_entry(
                project_name="outcome-probe",
                category="decision",
                content=(
                    "The isolated outcome probe verifies one durable decision while "
                    "unrelated follow-up work remains."
                ),
                source=f"distill-job:{job_id}",
                confidence=0.99,
                distill_job_id=job_id,
                evidence_basis="repository",
                verification_outcome="verified",
                verification_refs=[
                    {
                        "kind": "repository",
                        "locator": evidence_path.name,
                        "content_sha256": hashlib.sha256(
                            evidence_path.read_bytes()
                        ).hexdigest(),
                    }
                ],
            )
            handoff = governance_handlers.tool_create_task_handoff(
                project_name="outcome-probe",
                task_id="finish-isolated-follow-up",
                summary="Finish the scoped follow-up from the qualification session.",
                status="in_progress",
                next_steps=["Complete the isolated follow-up."],
                distill_job_id=job_id,
            )
            finalized = tool_handlers.tool_finalize_session_distill(
                project_name="outcome-probe",
                job_id=job_id,
                semantic_review={
                    "session_summary": (
                        "A verified decision was completed while an unrelated "
                        "follow-up remained unfinished."
                    ),
                    "final_user_request": "Retain the decision and track follow-up.",
                    "final_outcome": (
                        "The decision was verified; an older approach was superseded."
                    ),
                    "last_turn_status": "unfinished",
                    "contradictions": [
                        "An older approach was superseded by the verified decision."
                    ],
                    "unfinished_work": ["Complete the isolated follow-up."],
                    "evidence_status": "partial",
                    "promotion_decision": "partial",
                },
            )

            stored_candidate = asyncio.run(
                backend.structured_store.get_memory_entry(candidate["entry_id"])
            )
            stored_handoff = asyncio.run(
                backend.structured_store.get_task_handoff(handoff["handoff_id"])
            )
            note = dict(finalized.get("note") or {})
            note_path = Path(str(note.get("path") or ""))
            latest_path = Path(str(note.get("latest_path") or ""))
            result = {
                "prepared_job_matches": prepared.get("distill_job_id") == job_id,
                "candidate_status": getattr(stored_candidate, "status", None),
                "partial_candidate_promoted": bool(
                    stored_candidate is not None
                    and stored_candidate.status == "auto_confirmed"
                    and finalized.get("completion", {}).get("disposition")
                    == "promoted"
                ),
                "handoff_persisted": stored_handoff is not None,
                "handoff_job_bound": bool(
                    stored_handoff is not None
                    and dict(stored_handoff.context or {}).get("distill_job_id")
                    == job_id
                    and handoff["handoff_id"] in finalized.get("handoff_ids", [])
                ),
                "dream_blocked_for_partial": "dream" not in finalized,
                "immutable_note_exists": note_path.is_file(),
                "latest_note_exists": latest_path.is_file(),
                "note_paths_distinct": note_path != latest_path,
            }
            result["verified"] = all(result.values())
            return result
        finally:
            if (
                previous_backend_provider is None
                or previous_observer_provider is None
                or previous_cost_provider is None
            ):
                tool_handlers.reset_tool_handler_dependencies()
            else:
                tool_handlers.configure_tool_handler_dependencies(
                    backend_provider=previous_backend_provider,
                    observer_data_dir=previous_observer_provider,
                    cost_surface_budgets=previous_cost_provider,
                    logger_instance=previous_logger,
                )
            asyncio.run(backend.close())


def main() -> int:
    result = run_distill_outcome_probe()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
