from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.agent_runtime import active_backend
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.wake import build_wake_injection
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.memory_entry import MemoryEntry
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.mcp import tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.host_contracts import HOST_NAMES


@pytest.mark.parametrize(
    "client",
    HOST_NAMES,
)
def test_cross_host_transcript_distill_fact_wake_contract(
    tmp_path: Path,
    client: str,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    project = tmp_path / client
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.8.24"\n',
        encoding="utf-8",
    )

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / f"data-{client}")
        await backend.init()
        binding = active_backend.set(backend)
        try:
            fact = f"{client} uses the shared lossless distill contract"
            observation = Observation(
                session_id=f"session-{client}",
                client=client,
                raw_content=fact,
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "demo"},
            )
            snapshot = await persist_session_snapshot(
                backend,
                observation,
                project_name="demo",
                project_root=str(project),
                client=client,
                session_id=f"session-{client}",
                source_kind="native-transcript",
                source_uri=f"file:///{client}.jsonl",
                source_text=fact,
            )
            assert snapshot.distill_job_id is not None
            claims = backend.transcript_store.claim_distill_chunks(
                snapshot.distill_job_id,
                lease_owner="e2e-agent",
                limit=10,
            )
            for chunk, _checkpoint in claims:
                backend.transcript_store.checkpoint_distill_chunk(
                    snapshot.distill_job_id,
                    chunk.id,
                    lease_owner="e2e-agent",
                    result={"fact": fact, "evidence_strength": "direct"},
                )
            completed = backend.transcript_store.finalize_distill_job(
                snapshot.distill_job_id,
                semantic_review={
                    "final_user_request": "record shared contract",
                    "final_outcome": fact,
                    "last_turn_status": "answered",
                    "contradictions": [],
                    "unfinished_work": [],
                    "evidence_status": "answered",
                    "promotion_decision": "promote",
                },
            )
            assert completed.status == "completed"
            await backend.structured_store.save_memory_entry(
                MemoryEntry(
                    project_name="demo",
                    category="architecture",
                    content=fact,
                    source=str(snapshot.observation_id),
                    distill_job_id=snapshot.distill_job_id,
                    status="user_confirmed",
                )
            )
            current = KnowledgeEntry(
                id=f"current-{client}",
                project_name="demo",
                module_path=["Host integration"],
                title="Shared lossless contract",
                statement=fact,
                verified_at=datetime.now(timezone.utc),
            )
            candidate = KnowledgeCandidate(
                id=f"candidate-{client}",
                project_name="demo",
                candidate_type="memory",
                statement=fact,
            )
            decision = AssimilationDecision(
                id=f"mutation-{client}",
                project_name="demo",
                candidate_id=candidate.id,
                disposition="add",
                canonical_truth_ids=[current.id],
                reason="Cross-host current knowledge fixture.",
            )
            store = backend.structured_store.knowledge_store
            await store.save_candidate(candidate)
            await store.apply_current_change(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=decision,
                added_entries=[current],
                predecessor_entries=[],
                source_refs_by_entry={
                    current.id: [
                        ProjectKnowledgeSourceRef(
                            label="Transcript evidence",
                            target=f"session:{snapshot.source.id}",
                            kind="transcript",
                        )
                    ]
                },
            )
            await store.cleanup_candidate(candidate.id)
            wake = await build_wake_injection(
                backend,
                "demo",
                apply_surface_side_effects=False,
                current_task=fact,
            )
            assert "# Memory candidates" in wake
            assert "Shared lossless contract" in wake
            # The original query is echoed for cursor readback. The candidate
            # block itself must not contain the complete statement.
            assert fact not in wake.split("\n## ", 1)[1]
            assert "recent transcript evidence (not facts)" not in wake
            assert "⟨src:" not in wake
            assert await backend.structured_store.query_retrieval_signals("demo", signal_type="wake_surfaced") == []
            assert await backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit") == []
            query = json.loads(re.search(r"^query: (.+)$", wake, flags=re.MULTILINE).group(1))
            cursors = re.findall(r"^read_cursor: (.+)$", wake, flags=re.MULTILINE)
            assert query == fact
            assert len(cursors) == 1
            for cursor in cursors:
                full = await asyncio.to_thread(
                    tool_handlers.tool_search_memory, query=query, scope="all", detail="full",
                    cursor=cursor, _include_diagnostics=True,
                )
                assert full["detail"] == "full"
                assert full["memories"] == [{
                    "title": current.title, "statement": fact, "project_name": "demo",
                }]
                call = full["record_outcome_call"]
                assert call["arguments"]["source_ids"] == [current.id]
                recorded = await asyncio.to_thread(
                    tool_handlers.tool_record_context_outcome, **call["arguments"], outcome="used",
                )
                assert recorded["success"] is True
                assert recorded["truth_mutated"] is False
            hits = await backend.structured_store.query_retrieval_signals("demo", signal_type="search_hit")
            assert [hit.target_id for hit in hits] == [current.id]
            outcomes = await backend.structured_store.query_retrieval_signals("demo", signal_type="context_outcome")
            assert [outcome.target_id for outcome in outcomes] == [current.id]
        finally:
            active_backend.reset(binding)
            await backend.close()

    asyncio.run(run())
