from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.wake import assemble_context_plan
from harness_mem.core.schemas import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
    ProjectKnowledgeSourceRef,
)
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.task_handoff import TaskHandoff
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_repo_version_truth_suppresses_stale_l1_and_l2_claims(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "0.8.24"\n',
        encoding="utf-8",
    )

    async def run() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            observation = Observation(
                session_id="anchor-session",
                client="codex",
                raw_content="repository anchor",
                content_type="transcript",
                timestamp=datetime.now(timezone.utc),
                metadata={"project_name": "demo"},
            )
            await persist_session_snapshot(
                backend,
                observation,
                project_name="demo",
                project_root=str(project),
                client="codex",
                session_id="anchor-session",
                source_kind="jsonl",
                source_uri="file:///anchor.jsonl",
                source_text="repository anchor",
            )
            stale_truth = KnowledgeEntry(
                id="stale-version-knowledge",
                project_name="demo",
                module_path=["release"],
                title="Stale release",
                statement="v3.2.0 is the current released version.",
            )
            current_truth = KnowledgeEntry(
                id="current-version-knowledge",
                project_name="demo",
                module_path=["release"],
                title="Current release",
                statement="Version 0.8.24 is the current release.",
            )
            candidate = KnowledgeCandidate(
                id="version-truth-candidate",
                project_name="demo",
                candidate_type="memory",
                statement="Version truth fixture.",
            )
            await backend.structured_store.knowledge_store.apply_current_change(
                candidate_before=candidate,
                candidate_after=candidate.model_copy(update={"status": "assimilated"}),
                decision=AssimilationDecision(
                    id="version-truth-decision",
                    project_name="demo",
                    candidate_id=candidate.id,
                    disposition="add",
                    canonical_truth_ids=[stale_truth.id, current_truth.id],
                    reason="Test fixture.",
                ),
                added_entries=[stale_truth, current_truth],
                predecessor_entries=[],
                source_refs_by_entry={
                    entry.id: [
                        ProjectKnowledgeSourceRef(
                            label="pyproject.toml",
                            target=(project / "pyproject.toml").resolve().as_uri(),
                            kind="repository",
                            digest="a" * 64,
                        )
                    ]
                    for entry in (stale_truth, current_truth)
                },
            )
            await backend.structured_store.save_task_handoff(
                TaskHandoff(
                    project_name="demo",
                    task_id="old-release",
                    summary="v3.2.0 was released and is the current version.",
                    status="in_progress",
                )
            )

            plan = await assemble_context_plan(backend, project_name="demo")
            l1 = [entry.summary for entry in plan.layer("L1").entries]
            l2 = [entry.summary for entry in plan.layer("L2").entries]
            assert current_truth.statement in l1
            assert stale_truth.statement not in l1
            assert not any("v3.2.0" in summary for summary in l2)
        finally:
            await backend.close()

    asyncio.run(run())
