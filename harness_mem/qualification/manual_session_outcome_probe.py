"""Isolated manual runtime proof; Agent semantic decisions are deterministic."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.autonomous.worker import run_autonomous_distill_batch
from harness_mem.config.merge import MergedConfig
from harness_mem.mcp import distill_handlers, governance_handlers, tool_handlers
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _review(packet: dict, *, promote: bool) -> dict:
    result: dict = {
        "session_summary": "Verified the current cache rule." if promote else "Exchanged greetings.",
        "final_user_request": "Check the cache policy." if promote else "Hello",
        "final_outcome": "Answered", "last_turn_status": "answered",
        "contradictions": [], "unfinished_work": [], "evidence_status": "answered",
        "promotion_decision": "promote" if promote else "no_promotion",
    }
    return result


def run_manual_session_outcome_probe() -> dict:
    with TemporaryDirectory(prefix="harness-mem-manual-outcome-") as temporary, ExitStack() as stack:
        root = Path(temporary)
        project, native, data = root / "project", root / "cursor", root / "data"
        project.mkdir()
        statement = "The cache retains only verified current entries."
        evidence = project / "policy.txt"
        evidence.write_text(statement, encoding="utf-8")
        sources = []
        preference = "Always include the complete itemized list in future memory audits."
        for name, message in (("decision", statement), ("greeting", "Hello"),
                              ("preference", preference), ("deferred", "Verify the proposed audit policy."),
                              ("no-write", preference)):
            path = native / "workspace" / "agent-transcripts" / name / f"{name}.jsonl"
            path.parent.mkdir(parents=True)
            path.write_text("\n".join(json.dumps(row) for row in [
                {"role": "user", "cwd": str(project), "message": {"content": [{"type": "text", "text": message}]}},
                {"role": "assistant", "message": {"content": [{"type": "text", "text": "Answered."}]}},
            ]), encoding="utf-8")
            sources.append(path)
        original = {path: path.read_bytes() for path in sources}
        backend = LocalMemoryBackend(data)
        asyncio.run(backend.init())
        stack.callback(lambda: asyncio.run(backend.close()))
        # Route only storage/discovery to synthetic paths. All processing, gates,
        # persistence, source retention and retrieval below are real runtime.
        stack.enter_context(patch.object(tool_handlers, "_backend_provider", lambda: backend))
        stack.enter_context(patch.object(tool_handlers, "_observer_data_dir_provider", lambda: data))
        stack.enter_context(patch.object(tool_handlers, "_cost_surface_budgets_provider", lambda _: None))
        stack.enter_context(patch("harness_mem.commands.session_inventory.load_merged_config", lambda *_: MergedConfig()))
        stack.enter_context(patch("harness_mem.commands.session_inventory.build_inspection_adapter",
                                  lambda _: CursorAdapter(None, projects_dir=native, sqlite_databases=())))
        stack.enter_context(patch("harness_mem.mcp.distill_handlers._session_notes_dir", lambda _: data / "notes"))
        inventory = tool_inspect_sessions(str(project), clients=["cursor"])
        assert inventory["success"], inventory
        selected = inventory["sessions"]
        packet = tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(project), batch_sessions=selected)
        assert packet["success"], packet
        batch_id = packet["batch_id"]
        first_job = packet["distill_job_id"]
        output_chars = len(json.dumps(inventory)) + len(json.dumps(packet))
        resumed = tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(project), batch_id=batch_id)
        same_job = resumed.get("distill_job_id") == first_job
        packet = resumed
        calls = 3  # inventory, prepare, resume
        finalize_chars = 0
        visible_completion = False
        no_write_completion = False
        author_derived_preference_saved = False
        deferred_work_visible = False
        runtime_summary_consistent = False
        no_write_result_consistent = False
        note_hashes_match = True
        background_isolation = True
        low_level_manual_isolation = True
        prior_projection_chars = 0
        output_chars += len(json.dumps(packet))
        for _ in selected:
            assert packet["success"], packet
            job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
            assert job is not None
            before_job = job.to_dict()
            before_knowledge = tool_handlers.tool_search_memory(query="", project_name="project")
            low_level_manual_isolation &= (
                backend.transcript_store.claim_distill_chunks(
                    job.id, lease_owner="background-probe", execution_source="autonomous_worker",
                ) == []
                and backend.transcript_store.claim_distill_review(
                    job.id, lease_owner="background-probe", execution_source="autonomous_worker",
                ) is None
            )

            class NoCalls:
                name = "fixture_cli"

                def __getattr__(self, name):
                    raise AssertionError(f"manual job reached background provider: {name}")

            background = run_autonomous_distill_batch(
                backend, project_name="project", project_root=project,
                config=MergedConfig(distill_autonomous_enabled=True),
                trigger_id=job.session_id, client="cursor", provider=NoCalls(),
                preferred_job_id=job.id,
            )
            after_job = backend.transcript_store.get_distill_job(job.id)
            background_isolation &= (
                background["outcomes"] == [] and after_job is not None
                and after_job.to_dict() == before_job
                and tool_handlers.tool_search_memory(query="", project_name="project") == before_knowledge
                and all(path.read_bytes() == content for path, content in original.items())
            )
            calls += 2  # Ordinary MCP inventory readbacks around background attempt.
            promote = job.session_id == "decision"
            if promote:
                suggested = governance_handlers.tool_govern_memory(action="suggest", arguments={
                    "kind": "memory", "project_name": "project", "category": "decision", "content": statement,
                    "source": f"distill-job:{job.id}", "confidence": 0.99, "distill_job_id": job.id,
                    "evidence_basis": "repository", "verification_outcome": "verified",
                    "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(evidence.read_bytes()).hexdigest()}],
                    "assimilation_disposition": "add", "assimilation_reason": "Verified current policy is useful for maintenance.",
                    "canonical_title": "Verified current cache", "topic_path": ["cache"],
                })
                assert suggested["success"], suggested
                calls += 1
                output_chars += len(json.dumps(suggested))
            semantic = _review(packet, promote=promote)
            if job.session_id in {"preference", "deferred", "no-write"}:
                observation = asyncio.run(backend.verbatim_store.get(str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))))
                assert observation is not None
                digest = render_distill_exchange_windows(observation.raw_content, [1])[0]["content_sha256"]
                suggested = governance_handlers.tool_govern_memory(action="suggest", arguments={
                    "kind": "rule", "project_name": "project", "distill_job_id": job.id,
                    "trigger": "conducting future memory audits", "pattern": preference,
                    "canonical_title": "Audit presentation", "topic_path": ["Collaboration"],
                    "evidence_basis": "user_statement", "verification_outcome": "verified",
                    "verification_refs": [{"kind": "user_statement", "exchange_index": 1,
                                           "content_sha256": None if job.session_id == "deferred" else digest}],
                    "assimilation_disposition": "no_write" if job.session_id == "no-write" else "add",
                    "assimilation_reason": "Explicit continuing preference.",
                })
                assert suggested["success"], suggested
                semantic = _review(packet, promote=True)
                semantic.update(session_summary="Organized the future audit preference.",
                                final_user_request=preference, final_outcome="已验证并记住全部偏好。")
                calls += 1
                output_chars += len(json.dumps(suggested))
            final = tool_handlers.tool_finalize_session_distill("project", job.id, semantic)
            assert final["success"], final
            completed_job = backend.transcript_store.get_distill_job(job.id)
            assert completed_job is not None
            promotion = completed_job.promotion_summary
            answer_packet = promotion["answer_packet"]
            summary = distill_handlers._session_summary_payload(completed_job)
            if promote:
                visible_completion = final.get("knowledge_changes") == [{
                    "change": "added", "module": ["cache"],
                    "title": "Verified current cache", "statement": statement,
                }]
            elif job.session_id == "greeting":
                no_write_completion = not final.get("knowledge_changes") and bool(final.get("not_written"))
            note_path = Path(final["note"]["path"])
            note_text = note_path.read_text(encoding="utf-8")
            note_hashes_match &= hashlib.sha256(note_path.read_bytes()).hexdigest() == final["note"]["sha256"]
            if job.session_id == "preference":
                author_derived_preference_saved = (
                    answer_packet["answer_status"] == "ANSWERED"
                    and bool(final["knowledge_changes"])
                    and preference in final["knowledge_changes"][0]["statement"]
                )
            elif job.session_id == "deferred":
                deferred_work_visible = final.get("organization_status") == "partial" and bool(final["unfinished_work"]) and any(
                    preference in item for item in final["unfinished_work"]
                )
                runtime_summary_consistent = (
                    completed_job.completion_disposition in {"deferred", "conflict"}
                    and "已验证并记住全部偏好" not in note_text
                    and "无需长期记忆" not in note_text
                    and summary["unfinished_work"] == final["unfinished_work"]
                )
            elif job.session_id == "no-write":
                no_write_result_consistent = (
                    answer_packet["answer_status"] == "ANSWERED"
                    and not final["knowledge_changes"]
                    and "已验证并记住全部偏好" not in note_text
                    and summary["final_outcome"] == "本次未新增或替换长期记忆。"
                )
            assert completed_job.retain_source
            assert all(path.read_bytes() == content for path, content in original.items())
            finalize_chars += len(json.dumps(final))
            # Replay the previous response projection on these same results:
            # its nested promotion repeated the top-level Answer Packet.
            prior_projection = {**final, "promotion": promotion, "answer_packet": answer_packet,
                                "session_summary": summary}
            prior_projection_chars += len(json.dumps(prior_projection))
            packet = tool_handlers.tool_prepare_session_distill(project_name="project", project_root=str(project), batch_id=batch_id)
            calls += 2
            output_chars += len(json.dumps(final)) + len(json.dumps(packet))
        # Close/reopen before independent ordinary MCP search and batch report.
        asyncio.run(backend.close())
        backend = LocalMemoryBackend(data)
        asyncio.run(backend.init())
        retrieved = tool_handlers.tool_search_memory(query="verified current cache", project_name="project")
        current_view = tool_handlers.tool_search_memory(query="", project_name="project", scope="project")
        preference_readback = tool_handlers.tool_search_memory(query="Audit presentation", project_name="project")
        report = tool_inspect_sessions(str(project), batch_id=batch_id)
        repeated = tool_handlers.tool_prepare_session_distill(
            project_name="project", project_root=str(project), batch_sessions=selected,
        )
        jobs = backend.transcript_store.list_distill_jobs(project_name="project")
        checks = {
            "background_isolation": background_isolation,
            "low_level_manual_isolation": low_level_manual_isolation,
            "batch_completed": report.get("status") == "completed" and report["progress"]["completed"] == 5,
            "same_job_resumed": same_job and len(jobs) == 5,
            "truth_retrievable_after_reopen": statement in json.dumps(retrieved),
            "readable_changes": len(report["knowledge_changes"]) == 2 and any(
                item["title"] == "Verified current cache" and item["statement"] == statement
                for item in report["knowledge_changes"]
            ),
            "no_write_reported": any(row["count"] == 1 for row in report["not_written"]),
            "visible_completion": visible_completion,
            "no_write_completion": no_write_completion,
            "current_knowledge_view": len(current_view.get("memories", [])) == 2 and any(
                item == {"module": ["cache"], "title": "Verified current cache", "statement": statement}
                for item in current_view.get("memories", [])
            ),
            "author_derived_preference_saved": author_derived_preference_saved and preference in json.dumps(preference_readback),
            "deferred_work_visible": deferred_work_visible and bool(report["unfinished_work"]),
            "unfinished_organization_is_partial": (
                report.get("organization_status") == "partial"
                and repeated.get("organization_status") == "partial"
            ),
            "runtime_summary_consistent": runtime_summary_consistent,
            "no_write_result_consistent": no_write_result_consistent,
            "new_batch_preserves_handoff": (repeated.get("status") == "completed"
                                           and repeated["unfinished_work"] == report["unfinished_work"]
                                           and bool(repeated["unfinished_work"])
                                           and repeated["knowledge_changes"] == []
                                           and repeated["not_written"] == []),
            "note_hashes_match": note_hashes_match,
            "sources_unchanged": all(path.read_bytes() == content for path, content in original.items()),
            "revision_bound_readback": all(job.promotion_summary.get("readback", {}).get("source_revision") == job.source_revision for job in jobs),
        }
        return {"verified": all(checks.values()), **checks, "semantic_mode": "deterministic_fixture_agent",
                "sample_calls": calls + 5, "sample_response_characters": output_chars + len(json.dumps(retrieved)) + len(json.dumps(report)) + len(json.dumps(current_view)) + len(json.dumps(preference_readback)) + len(json.dumps(repeated)),
                "same_result_projection_comparison": {"previous_finalize_characters": prior_projection_chars,
                                                      "current_finalize_characters": finalize_chars,
                                                      "duplicate_characters_removed": prior_projection_chars - finalize_chars}}


def main() -> int:
    result = run_manual_session_outcome_probe()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
