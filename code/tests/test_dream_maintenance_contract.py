from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
from pathlib import Path
import threading
from types import SimpleNamespace
from typing import Any

import pytest

import harness_mem.commands.dream as dream_module
import harness_mem.commands.maintenance as maintenance_module
import harness_mem.mcp.tool_handlers as tool_handlers
from harness_mem.commands.dream import (
    DreamSchedulerDecision,
    dream_auto_tick,
    dream_once,
    dream_status_snapshot,
    latest_dream_ledger,
)
from harness_mem.commands.dream_assimilation import (
    DreamAssimilationCandidate,
    prepare_dream_assimilation,
    build_dream_maintenance_plan,
    apply_dream_assimilation,
)
from harness_mem.autonomous.models import (
    AssimilationDecision as ProviderAssimilationDecision,
    CandidateVerificationDecision,
)
from harness_mem.autonomous.provider import ProviderError, ProviderResult
from harness_mem.commands.maintenance import run_post_turn_maintenance
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEntry,
)
from harness_mem.core.schemas.project_knowledge_base import ProjectKnowledgeSourceRef
from harness_mem.core.schemas.reflection_job import ReflectionJob
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.embedding import embeddings_disabled
from harness_mem.retrieval_signals import record_retrieval_signal
from harness_mem.storage.reflection_job_store import ReflectionJobStore
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.sqlite_index import SQLiteIndex


def _run(coro):
    return asyncio.run(coro)


async def _new_backend(data_dir: Path) -> LocalMemoryBackend:
    backend = LocalMemoryBackend(data_dir)
    await backend.init()
    return backend


@pytest.fixture()
def backend(tmp_path, monkeypatch):
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")
    backend = _run(_new_backend(tmp_path))
    try:
        yield backend
    finally:
        _run(backend.close())


def _publish_current_knowledge(
    backend: LocalMemoryBackend,
    *entries: KnowledgeEntry,
    source_text: str | None = None,
) -> tuple[Path, list[KnowledgeEntry]]:
    """Publish the fixture through the same SQLite mutation as production."""

    project_root = backend.data_dir / "demo-project"
    project_root.mkdir(parents=True, exist_ok=True)
    source_path = project_root / "source.md"
    source_path.write_text(
        source_text if source_text is not None else "\n".join(entry.statement for entry in entries),
        encoding="utf-8",
    )
    source = ProjectKnowledgeSourceRef(
        label="Dream contract fixture",
        target=source_path.as_uri(),
        kind="repository",
        digest=hashlib.sha256(source_path.read_bytes()).hexdigest(),
    )
    store = backend.structured_store.knowledge_store
    candidate = KnowledgeCandidate(
        id="dream-fixture-candidate-" + "-".join(entry.id for entry in entries),
        project_name="demo",
        candidate_type="memory",
        statement="Dream current-knowledge fixture.",
    )
    decision = AssimilationDecision(
        id="dream-fixture-mutation-" + "-".join(entry.id for entry in entries),
        project_name="demo",
        candidate_id=candidate.id,
        disposition="add",
        canonical_truth_ids=[entry.id for entry in entries],
        reason="Test fixture.",
    )
    _run(store.save_candidate(candidate))
    _run(
        store.apply_current_change(
            candidate_before=candidate,
            candidate_after=candidate.model_copy(update={"status": "assimilated"}),
            decision=decision,
            added_entries=list(entries),
            predecessor_entries=[],
            source_refs_by_entry={entry.id: [source] for entry in entries},
        )
    )
    # Test fixtures model a completed assimilation job.  Its candidate and
    # associated evidence are job-scoped processing material, so production
    # finalization removes them before Dream sees the current knowledge.
    _run(store.cleanup_candidate(candidate.id))
    return project_root, _run(
        store.list_entries("demo", project_root=project_root)
    )


class _DreamVerificationProvider:
    name = "test-dream-provider"

    def __init__(self, *, support: str = "supported", scope: str = "durable"):
        self.support = support
        self.scope = scope
        self.manifests: list[dict[str, Any]] = []
        self.assimilation_manifests: list[dict[str, Any]] = []

    def verify(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir, heartbeat
        self.manifests.append(manifest)
        points = [
            {
                "candidate_index": int(candidate["candidate_index"]),
                "semantic_support": self.support,
                "future_scope": self.scope,
                "source_use": "standing_decision" if self.scope == "durable" else "task_context",
                "reason": "Current source was checked against the actual title and statement.",
                "scope_segments": [{
                    "text": candidate["scope_text"],
                    "source_use": "standing_decision" if self.scope == "durable" else "task_context",
                    "future_scope": self.scope, "standalone": True,
                    "content_role": "claim", "source_support": self.support,
                }],
            }
            for candidate in manifest["candidates"]
        ]
        return ProviderResult(
            decision=CandidateVerificationDecision.model_validate(
                {"points": points}
            ),
            provider=self.name,
            model="test-model",
            duration_seconds=0.01,
            input_sha256="a" * 64,
            response_sha256="b" * 64,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            event_count=1,
        )

    def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
        del runtime_dir, heartbeat
        self.assimilation_manifests.append(manifest)
        points = []
        candidates = list(manifest["verified_candidates"])
        survivor_handle = str(candidates[0].get("own_truth_handle", ""))
        for index, candidate in enumerate(candidates):
            if manifest.get("maintenance_candidates"):
                points.append({"candidate_id": candidate["candidate_id"], "disposition": "no_write",
                               "reason": "This fixture proposes no corrected replacement for the original row."})
                continue
            support = str(candidate["semantic_support"])
            own_handle = str(candidate["own_truth_handle"])
            if support == "contradicted":
                disposition = "reject"
                handles = [own_handle]
            elif manifest["dream_signal"] == "duplicate" and index:
                disposition = "reject"
                handles = [survivor_handle]
            else:
                disposition = "confirm"
                handles = [own_handle]
            points.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "disposition": disposition,
                    "matched_truth_handles": handles,
                    "canonical_title": None,
                    "canonical_statement": None,
                    "topic_path": [],
                    "knowledge_items": [],
                    "reason": "Dream comparison selected this source-backed outcome.",
                }
            )
        return ProviderResult(
            decision=ProviderAssimilationDecision.model_validate({"points": points}),
            provider=self.name,
            model="test-model",
            duration_seconds=0.01,
            input_sha256="c" * 64,
            response_sha256="d" * 64,
            input_tokens=1,
            output_tokens=1,
            total_tokens=2,
            event_count=1,
        )


def test_dream_background_requires_project_autonomous_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _DreamVerificationProvider()
    from harness_mem.autonomous.executors import registry as executor_registry

    monkeypatch.setattr(
        executor_registry,
        "build_semantic_executor",
        lambda _config, _client: selected,
    )

    assert (
        dream_module._dream_provider_from_config(
            MergedConfig(distill_autonomous_enabled=False)
        )
        is None
    )
    assert (
        dream_module._dream_provider_from_config(
            MergedConfig(distill_autonomous_enabled=True),
            host_client="codex",
        )
        is selected
    )


def test_dream_does_not_select_claude_when_host_is_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from harness_mem.autonomous.executors import registry as executor_registry
    from harness_mem.commands import support

    monkeypatch.setattr(support, "detect_runtime_client", lambda: None)
    monkeypatch.setattr(
        executor_registry,
        "build_semantic_executor",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("unknown host must not construct a CLI executor")
        ),
    )

    assert (
        dream_module._dream_provider_from_config(
            MergedConfig(distill_autonomous_enabled=True)
        )
        is None
    )


def test_hook_dream_passes_its_selected_cli_to_session_distill(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _DreamVerificationProvider()
    # This test replaces both worker and Dream with in-process fakes. Native
    # production readiness is separately covered and remains fail-closed.
    monkeypatch.setattr(dream_module, "background_status", lambda *_args, **_kwargs:
        SimpleNamespace(ready=True, on=True, reason="ok", selected_cli="fake"))
    captured: dict[str, Any] = {}
    monkeypatch.setattr("harness_mem.hook_background.background_generation_from_env", lambda: "later-stop-generation")

    from harness_mem.autonomous.executors import registry as executor_registry

    monkeypatch.setattr(
        executor_registry,
        "build_semantic_executor",
        lambda _config, _client: selected,
    )

    def fake_worker(_backend, **kwargs):
        captured.update(kwargs)
        return {"success": True, "state": "succeeded", "outcomes": [], "receipt": {
            "last_verified_completion": {"job_id": "job-42", "session_id": "session-42",
                "trigger_id": "session-42", "dispatch_generation": "original-paid-generation"}}}

    async def fake_dream_run(*_args, **kwargs):
        captured["dream_host"] = kwargs["host_client"]
        captured["dream_scope"] = kwargs["maintenance_scope"]
        now = datetime.now(timezone.utc)
        return DreamRun(
            project_name="demo",
            started_at=now,
            completed_at=now,
            status="completed",
            trigger_source="ide_hook",
            reflection_job_id=kwargs["reflection_job_id"],
        )

    from harness_mem.autonomous import worker as autonomous_worker

    monkeypatch.setattr(autonomous_worker, "run_autonomous_distill_batch", fake_worker)
    monkeypatch.setattr(dream_module, "_run_dream_with_progress_timeout", fake_dream_run)

    result = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(
                distill_autonomous_enabled=True,
            ),
            source="ide_hook",
            trigger_id="session-42",
            trigger_job_id="job-42",
            host_client="codex",
        )
    )

    assert result["success"] is True, result
    assert result["session_distill"]["job_id"] == "job-42"
    assert captured["provider"] is None
    assert captured["preferred_job_id"] == "job-42"
    assert captured["client"] == "codex"
    assert captured["dream_host"] == "codex"
    assert captured["dream_scope"]["trigger_id"] == "session-42"
    assert captured["dispatch_generation"] == "later-stop-generation"
    assert captured["dream_scope"]["dispatch_generation"] == "original-paid-generation"


def test_hook_dream_uses_job_host_when_project_selects_another_cli(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected = _DreamVerificationProvider()
    # This test replaces both worker and Dream with in-process fakes. Native
    # production readiness is separately covered and remains fail-closed.
    monkeypatch.setattr(dream_module, "background_status", lambda *_args, **_kwargs:
        SimpleNamespace(ready=True, on=True, reason="ok", selected_cli="fake"))
    captured: dict[str, Any] = {}

    from harness_mem.autonomous.executors import registry as executor_registry
    from harness_mem.autonomous import worker as autonomous_worker
    from harness_mem.commands import support

    monkeypatch.setattr(support, "detect_runtime_client", lambda: None)
    job = SessionDistillJob(
        id="job-43", idempotency_key="job-43", client="cursor", session_id="session-43",
        project_name="demo", project_root=str(tmp_path), source_id="source-43", source_revision="revision-43",
    )
    monkeypatch.setattr(
        backend.transcript_store,
        "get_distill_job",
        lambda job_id: job if job_id == job.id else None,
    )
    monkeypatch.setattr(
        "harness_mem.autonomous.executors.host_cli._resolve_executable",
        lambda client: "hermes-bin" if client == "hermes" else "",
    )
    monkeypatch.setattr(
        executor_registry,
        "build_semantic_executor",
        lambda _config, _client: selected,
    )

    def fake_worker(_backend, **kwargs):
        captured.update(kwargs)
        return {"success": True, "state": "succeeded", "outcomes": []}

    async def fake_dream_run(*_args, **kwargs):
        now = datetime.now(timezone.utc)
        return DreamRun(
            project_name="demo",
            started_at=now,
            completed_at=now,
            status="completed",
            trigger_source="ide_hook",
            reflection_job_id=kwargs["reflection_job_id"],
        )

    monkeypatch.setattr(autonomous_worker, "run_autonomous_distill_batch", fake_worker)
    monkeypatch.setattr(dream_module, "_run_dream_with_progress_timeout", fake_dream_run)

    result = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(
                distill_autonomous_enabled=True,
                distill_autonomous_cli="hermes",
            ),
            source="ide_hook",
            trigger_id="session-43",
            trigger_job_id="job-43",
        )
    )

    assert result["success"] is True
    assert captured["client"] == "cursor"
    assert captured["provider"] is None


def test_dream_does_not_read_legacy_candidate_stores(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fail_legacy_read(*_args, **_kwargs):
        raise AssertionError("Dream must not read legacy candidate stores")

    for method_name in (
        "list_merge_suggestion_candidates",
        "list_stale_truth_suggestion_candidates",
        "list_supersede_candidates",
    ):
        monkeypatch.setattr(
            backend.structured_store,
            method_name,
            fail_legacy_read,
        )

    run = _run(dream_once(backend, project_name="demo", config=MergedConfig()))

    assert run.items == []
    assert run.handling_summary == {
        "processed": 0,
        "applied": 0,
        "rejected": 0,
        "skipped": 0,
        "failed": 0,
    }
def test_dream_compares_and_deduplicates_source_backed_current_knowledge(
    backend,
) -> None:
    from test_dream_duplicate_consolidation import MergeProvider

    store = backend.structured_store.knowledge_store
    first = KnowledgeEntry(
        id="knowledge-first",
        project_name="demo",
        title="Preserve evidence",
        statement="Keep original evidence before normalization.",
        module_path=["ingestion"],
    )
    second = KnowledgeEntry(
        id="knowledge-second",
        project_name="demo",
        title="Keep source evidence",
        statement="Keep original evidence before normalization.",
        module_path=["ingestion"],
    )
    project_root, current = _publish_current_knowledge(backend, first, second)
    first, second = current
    provider = MergeProvider(make_output=lambda _subject: {
        "title": first.title,
        "statement": first.statement,
        "topic_path": first.module_path,
        "claim_kind": "design_requirement",
    })

    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=provider,
        )
    )

    assert run.resolution_status == "resolved", run.notes
    assert len(provider.finals) == 1
    survivor, = _run(store.list_entries("demo", project_root=project_root))
    assert survivor.id not in {first.id, second.id}
    assert (survivor.title, survivor.statement, survivor.module_path) == (
        first.title, first.statement, first.module_path,
    )
    assert _run(store.list_candidates("demo")) == []
    replacements = [item for item in run.items if item.result.get("truth_change") == "replace"]
    assert len(replacements) == 1
    assert "undo" not in replacements[0].to_dict()


def test_dream_archives_multi_entry_conflict_without_selecting_a_winner(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    first = KnowledgeEntry(
        id="knowledge-current-a",
        project_name="demo",
        title="Evidence retention",
        statement="Keep original evidence for seven days.",
        module_path=["ingestion"],
    )
    second = KnowledgeEntry(
        id="knowledge-current-b",
        project_name="demo",
        title="Evidence retention",
        statement="Keep original evidence for thirty days.",
        module_path=["ingestion"],
    )
    project_root, current = _publish_current_knowledge(backend, first, second)
    first, second = current

    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )

    conflict = next(
        item for item in run.items if item.source_kind == "knowledge_conflict"
    )
    assert conflict.final_action == "failed"
    assert run.status == "failed"
    assert _run(
        store.get_entry(first.id, project_name="demo", project_root=project_root)
    ) == first
    assert _run(
        store.get_entry(second.id, project_name="demo", project_root=project_root)
    ) == second


def test_dream_compares_source_backed_conflict_and_rejects_a_guess(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    first = KnowledgeEntry(
        id="knowledge-conflict-first",
        project_name="demo",
        title="Evidence retention",
        statement="Keep original evidence for seven days.",
        module_path=["ingestion"],
    )
    second = KnowledgeEntry(
        id="knowledge-conflict-second",
        project_name="demo",
        title="Evidence retention",
        statement="Keep original evidence for thirty days.",
        module_path=["ingestion"],
    )
    project_root, current = _publish_current_knowledge(backend, first, second)
    first, second = current

    class _ConflictProvider(_DreamVerificationProvider):
        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            result = super().verify(manifest, runtime_dir=runtime_dir, heartbeat=heartbeat)
            # Both source accounts exist, but the complete sources do not
            # settle which incompatible rule is currently applicable.
            for point in result.decision.points:
                point.future_scope = "unclear"
                point.source_use = "unclear"
                point.reason = "Both cited accounts exist; current applicability is unresolved."
                for part in point.scope_segments:
                    part.future_scope = "unclear"
                    part.source_use = "unclear"
            return result

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            del runtime_dir, heartbeat
            self.assimilation_manifests.append(manifest)
            return ProviderResult(
                decision=ProviderAssimilationDecision.model_validate(
                    {
                        "points": [
                            {
                                "candidate_id": candidate["candidate_id"],
                                "disposition": "conflict",
                                "matched_truth_handles": [],
                                "canonical_title": None,
                                "canonical_statement": None,
                                "topic_path": [],
                                "knowledge_items": [],
                                "reason": "Both current sources support distinct statements, so no winner is safe.",
                            }
                            for candidate in manifest["verified_candidates"]
                        ]
                    }
                ),
                provider=self.name,
                model="test-model",
                duration_seconds=0.01,
                input_sha256="1" * 64,
                response_sha256="2" * 64,
                input_tokens=1,
                output_tokens=1,
                total_tokens=2,
                event_count=1,
            )

    provider = _ConflictProvider()
    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=provider,
        )
    )

    assert {item.source_id for item in run.items} == {first.id, second.id}
    assert all(item.final_action == "rejected" for item in run.items)
    assert _run(
        store.get_entry(first.id, project_name="demo", project_root=project_root)
    ) == first
    assert _run(
        store.get_entry(second.id, project_name="demo", project_root=project_root)
    ) == second
    assert _run(store.list_candidates("demo")) == []
    assert len(provider.manifests) == 1
    assert provider.assimilation_manifests == []


def test_dream_archives_aged_claim_and_negative_feedback_without_profile(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-aged",
        project_name="demo",
        title="Retention period",
        statement="Keep original evidence for thirty days.",
        module_path=["ingestion"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, current = _publish_current_knowledge(backend, entry)
    entry = current[0]
    _run(
        record_retrieval_signal(
            backend,
            project_name="demo",
            signal_type="context_outcome",
            target_kind="knowledge_entry",
            target_id=entry.id,
            value=-1.0,
            context={"outcome": "misleading"},
        )
    )

    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )

    kinds = {item.source_kind for item in run.items}
    assert {"knowledge_stale", "knowledge_feedback"} <= kinds
    assert all(item.final_action == "failed" for item in run.items)
    assert run.status == "failed"
    assert _run(
        store.get_entry(entry.id, project_name="demo", project_root=project_root)
    ) == entry
    assert _run(store.list_candidates("demo")) == []


def test_dream_refreshes_one_reopenable_entry_with_restricted_provider(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-source-refresh",
        project_name="demo",
        title="Source refresh",
        statement="Current source-backed knowledge is rechecked before refresh.",
        module_path=["governance"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, current = _publish_current_knowledge(backend, entry)
    entry = current[0]

    provider = _DreamVerificationProvider()
    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=provider,
        )
    )

    refreshed = _run(store.get_entry(entry.id, project_name="demo"))
    assert run.items[0].final_action == "applied"
    assert run.items[0].result["truth_change"] == "verification_refreshed"
    assert refreshed is not None
    assert refreshed.statement == entry.statement
    assert refreshed.verified_at is not None and refreshed.verified_at > entry.verified_at
    assert _run(store.list_candidates("demo")) == []
    assert provider.manifests[0]["candidates"][0]["sources"][0]["content"] == entry.statement
    assert "file:" not in str(provider.manifests[0])


def test_dream_deletes_one_entry_only_when_current_source_contradicts(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-source-contradicted",
        project_name="demo",
        title="Contradicted source",
        statement="Current source-backed knowledge can be retired after contradiction.",
        module_path=["governance"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, current = _publish_current_knowledge(backend, entry)
    entry = current[0]

    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=_DreamVerificationProvider(support="contradicted"),
        )
    )

    assert run.items[0].final_action == "applied"
    assert run.items[0].result["truth_change"] == "deleted"
    assert _run(store.get_entry(entry.id, project_name="demo")) is None
    assert _run(store.list_sources(entry.id)) == []
    assert "undo" not in run.items[0].to_dict()


def test_dream_refines_changed_local_source_through_assimilation(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A changed repository source is compared, rechecked, and atomically replaced."""

    store = backend.structured_store.knowledge_store
    old_statement = "The retention window is seven days."
    new_statement = "The retention window is thirty days."
    entry = KnowledgeEntry(
        id="knowledge-retention-window",
        project_name="demo",
        title="Retention window",
        statement=old_statement,
        module_path=["retention"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, _current = _publish_current_knowledge(
        backend,
        entry,
        source_text=old_statement,
    )
    source_path = project_root / "source.md"
    source_path.write_text(new_statement, encoding="utf-8")

    from harness_mem.commands.separated_assimilation import target_version
    predecessor_version = target_version({
        "title": entry.title,
        "statement": old_statement,
        "topic_path": list(entry.module_path),
        "source_report": None,
    })

    class _RefiningProvider(_DreamVerificationProvider):
        def __init__(self) -> None:
            super().__init__(support="contradicted")
            self.phases = []

        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            from dataclasses import replace

            result = super().verify(manifest, runtime_dir=runtime_dir, heartbeat=heartbeat)
            candidate = manifest["candidates"][0]
            if manifest["contract_version"] == "final-knowledge-scope-v1":
                self.phases.append("final")
                context = candidate["update_context"]
                assert candidate["statement"] == new_statement
                assert candidate["sources"][0]["content"] == new_statement
                assert context["predecessors"][0]["statement"] == old_statement
                assert context["predecessors"][0]["version"] == predecessor_version
                meaning = {
                    "relationship": "preserves_applicable_meaning", "predecessor_conditions": [],
                    "predecessor_statements": [old_statement], "predecessor_versions": [predecessor_version],
                    "successor_statements": [new_statement], "undecided_state": None,
                    "basis": "The reopened source explicitly corrects seven days to thirty days.",
                }
                return replace(result, decision=CandidateVerificationDecision.model_validate({"points": [{
                    "candidate_index": 0, "semantic_support": "supported", "future_scope": "durable",
                    "source_use": "standing_decision", "reason": "The final corrected title and statement match current source.",
                    "scope_segments": [{"text": candidate["scope_text"], "source_use": "standing_decision",
                        "future_scope": "durable", "standalone": True, "content_role": "claim", "source_support": "supported"}],
                    "update_meaning_judgment": meaning,
                }]}))
            self.phases.append("source")
            assert candidate["statement"] == old_statement
            assert candidate["sources"][0]["content"] == new_statement
            snapshot = candidate["target_snapshot"]
            assert snapshot["statement"] == old_statement
            assert snapshot["version"] == predecessor_version
            assert result.decision.points[0].semantic_support == "contradicted"
            assert result.decision.points[0].replacement_items == []
            self.source_result = result
            return result

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            from dataclasses import replace
            self.phases.append("proposal")
            self.assimilation_manifests.append(manifest)
            candidate = manifest["verified_candidates"][0]
            assert candidate["semantic_support"] == "contradicted"
            return replace(self.source_result, decision=ProviderAssimilationDecision.model_validate({"points": [{
                "candidate_id": candidate["candidate_id"], "disposition": "refine",
                "matched_truth_handles": [manifest["current_truth"][0]["handle"]],
                "knowledge_items": [{"title": "Retention window", "statement": new_statement,
                    "topic_path": ["retention"], "claim_kind": "implementation_fact"}],
                "reason": "Propose the exact current-source correction without a final semantic verdict.",
            }]}))

    provider = _RefiningProvider()
    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=provider,
        )
    )

    current = _run(store.list_entries("demo", project_root=project_root))
    assert [item.statement for item in current] == [new_statement]
    assert _run(store.get_entry(entry.id, project_name="demo")) is None
    assert run.items[0].final_action == "applied"
    assert run.items[0].result["truth_change"] == "refine"
    assert len(provider.manifests) == 2
    assert provider.manifests[0]["candidates"][0]["sources"][0]["content"] == new_statement
    assert len(provider.assimilation_manifests) == 1
    assert provider.phases == ["source", "proposal", "final"]
    current_sources = _run(store.list_sources(current[0].id))
    assert current_sources[0].content_sha256 == hashlib.sha256(
        new_statement.encode("utf-8")
    ).hexdigest()
    assert _run(store.list_candidates("demo")) == []


def _prepared_multi_target_replacement(backend):
    from harness_mem.autonomous.models import CandidateVerificationPoint, UpdateMeaningJudgment
    from harness_mem.commands.separated_assimilation import target_version

    first = KnowledgeEntry(id="dream-old-one", project_name="demo", title="Old Alpha rule",
        statement="Alpha cache stays local while the sample is signed.", module_path=["rules"])
    second = KnowledgeEntry(id="dream-old-two", project_name="demo", title="Old Beta decision",
        statement="Beta rollout remains undecided.", module_path=["rules"])
    root, current = _publish_current_knowledge(backend, first, second)
    by_id = {row.id: row for row in current}
    current = [by_id[first.id], by_id[second.id]]
    items = [
        {"title": "Signed Alpha cache", "statement": first.statement,
         "topic_path": ["rules"], "claim_kind": "implementation_fact"},
        {"title": "Undecided Beta rollout", "statement": second.statement,
         "topic_path": ["rules"], "claim_kind": "design_requirement"},
    ]
    meaning = UpdateMeaningJudgment(relationship="preserves_applicable_meaning",
        predecessor_conditions=["while the sample is signed"],
        undecided_state=second.statement, successor_statements=[item["statement"] for item in items],
        predecessor_statements=[row.statement for row in current],
        predecessor_versions=[target_version({"title": row.title, "statement": row.statement,
            "topic_path": list(row.module_path), "source_report": None}) for row in current],
        basis="Both exact old rows, their condition and undecided state remain in the two outputs.")
    candidates = []
    for index, row in enumerate(current):
        segment = {"text": row.title + "\n" + row.statement, "source_use": "standing_decision",
            "future_scope": "durable", "standalone": True, "content_role": "claim", "source_support": "supported"}
        proposal = {"candidate_index": index, "semantic_support": "supported", "future_scope": "durable",
            "source_use": "standing_decision", "reason": "The complete current source and proposed output were checked.",
            "scope_segments": [segment]}
        if index == 0:
            proposal.update(replacement_items=items, replacement_target_ids=[entry.id for entry in current],
                update_meaning_judgment=meaning.model_dump(mode="json"),
                output_verifications=[{"semantic_support": "supported", "future_scope": "durable",
                    "source_use": "standing_decision", "reason": "This exact final title and body keep the whole replacement meaning.",
                    "scope_segments": [{**segment, "text": item["title"] + "\n" + item["statement"]}],
                    "update_meaning_judgment": meaning.model_dump(mode="json")} for item in items])
        point = CandidateVerificationPoint.model_validate(proposal)
        candidates.append(DreamAssimilationCandidate(candidate_id=f"candidate-{index}", entry=row,
            sources=tuple(_run(backend.structured_store.knowledge_store.list_sources(row.id))),
            semantic_support="supported", future_scope="durable", verification_reason=point.reason,
            source_excerpts=(), scope_verification=point))
    # The owner is deliberately after the other target: execution must reorder it.
    prepared = prepare_dream_assimilation(project_name="demo", project_root=root,
        run_id="dream-multi-target", signal_kind="stale", candidates=list(reversed(candidates)))
    return root, current, items, prepared


def test_dream_replace_can_target_multiple_current_rows(backend) -> None:
    from harness_mem.read_knowledge import search_current_knowledge

    root, current, items, prepared = _prepared_multi_target_replacement(backend)
    plan = build_dream_maintenance_plan(prepared)
    assert plan[0]["candidate_id"] == "candidate-0"
    assert plan[0]["matched_truth_ids"] == [row.id for row in current]
    assert len(plan) == len(current) == 2
    outcomes = _run(apply_dream_assimilation(backend, prepared=prepared, plan=plan))
    assert len(outcomes) == 2
    assert all(outcome["status"] == "applied" for outcome in outcomes), outcomes
    assert sum(outcome.get("truth_change") == "covered_by_replacement" for outcome in outcomes) == 1
    store = backend.structured_store.knowledge_store
    rows = _run(store.list_entries("demo"))
    assert len(rows) == 2
    assert {row.statement for row in rows} == {item["statement"] for item in items}
    assert not {row.id for row in current}.intersection(row.id for row in rows)
    expected = {row.id: row.to_dict() for row in rows}
    _run(backend.close())
    fresh = _run(_new_backend(backend.data_dir))
    try:
        assert {row.id: row.to_dict() for row in _run(fresh.structured_store.knowledge_store.list_entries("demo"))} == expected
        for query, title in (("Alpha cache", "Signed Alpha cache"), ("Beta rollout", "Undecided Beta rollout")):
            found = _run(search_current_knowledge(fresh, project_name="demo", query=query, limit=20))
            assert title in {row.title for row in found}
            assert not {row.id for row in current}.intersection(row.id for row in found)
    finally:
        _run(fresh.close())


def test_v9_joint_replacement_uses_separate_proposal_and_final_verification(backend):
    from dataclasses import replace
    from harness_mem.autonomous.models import UpdateMeaningJudgment

    old = [KnowledgeEntry(id="joint-alpha", project_name="demo", title="Legacy policy",
                         statement="Alpha cache stays local while the sample is signed.", module_path=["rules"]),
           KnowledgeEntry(id="joint-beta", project_name="demo", title="Legacy policy",
                         statement="Beta rollout remains undecided.", module_path=["rules"])]
    root, current = _publish_current_knowledge(backend, *old)
    outputs = [{"title": "Signed Alpha cache", "statement": old[0].statement,
                "topic_path": ["rules"], "claim_kind": "implementation_fact"},
               {"title": "Undecided Beta rollout", "statement": old[1].statement,
                "topic_path": ["rules"], "claim_kind": "design_requirement"}]

    class JointProvider(_DreamVerificationProvider):
        def __init__(self):
            super().__init__(support="supported")
            self.phases = []

        def verify(self, manifest, *, runtime_dir, heartbeat=None):
            result = super().verify(manifest, runtime_dir=runtime_dir, heartbeat=heartbeat)
            final = manifest["contract_version"] == "final-knowledge-scope-v1"
            self.phases.append("final" if final else "source")
            if not final:
                self.source_result = result
                # Whole-row support is partial; its complete durable body can
                # still become proposed output after correcting the title.
                return replace(result, decision=CandidateVerificationDecision.model_validate({"points": [
                    {**point.model_dump(mode="json"), "semantic_support": "partial", "scope_segments": [{
                        **point.scope_segments[0].model_dump(mode="json"), "source_support": "supported"}]}
                    for point in result.decision.points]}))
            points = []
            for row in manifest["candidates"]:
                context = row["update_context"]
                meaning = UpdateMeaningJudgment(relationship="preserves_applicable_meaning",
                    predecessor_conditions=["while the sample is signed"], undecided_state=old[1].statement,
                    predecessor_statements=[item["statement"] for item in context["predecessors"]],
                    predecessor_versions=[item["version"] for item in context["predecessors"]],
                    successor_statements=[item["statement"] for item in context["successors"]],
                    basis="Both corrected topics retain the signed condition and explicitly undecided state.")
                points.append({"candidate_index": row["candidate_index"], "semantic_support": "supported",
                    "future_scope": "durable", "source_use": "standing_decision",
                    "reason": "The exact final output and whole joint update match complete original sources.",
                    "scope_segments": [{"text": row["scope_text"], "source_use": "standing_decision",
                        "future_scope": "durable", "standalone": True, "content_role": "claim", "source_support": "supported"}],
                    "update_meaning_judgment": meaning.model_dump(mode="json")})
            return replace(result, decision=CandidateVerificationDecision.model_validate({"points": points}))

        def assimilate(self, manifest, *, runtime_dir, heartbeat=None):
            self.phases.append("proposal")
            self.assimilation_manifests.append(manifest)
            candidates = manifest["verified_candidates"]
            points = [{"candidate_id": candidates[0]["candidate_id"], "disposition": "replace",
                       "matched_truth_handles": [item["handle"] for item in manifest["current_truth"]],
                       "knowledge_items": outputs, "reason": "Propose one joint replacement preserving both topics."}]
            points.extend({"candidate_id": item["candidate_id"], "disposition": "no_write",
                           "reason": "The owning proposal replaces this target in the same transaction."}
                          for item in candidates[1:])
            return replace(self.source_result, decision=ProviderAssimilationDecision.model_validate({"points": points}))

    provider = JointProvider()
    run = _run(dream_once(backend, project_name="demo", project_root=root, config=None,
                          source="agent", semantic_provider=provider))
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo"))
    assert {row.title for row in rows} == {item["title"] for item in outputs}
    assert not {row.id for row in current}.intersection(row.id for row in rows)
    assert provider.phases == ["source", "proposal", "final"]
    assert any(item.result.get("truth_change") == "replace" for item in run.items)
    assert any(item.result.get("truth_change") == "covered_by_replacement" for item in run.items)
    assert run.continuation["unresolved_scope"] == {}
    assert run.resolution_status == "resolved"


def test_dream_multi_target_cas_failure_writes_no_partial_outputs(backend, monkeypatch):
    root, current, _items, prepared = _prepared_multi_target_replacement(backend)
    plan = build_dream_maintenance_plan(prepared)
    structured = backend.structured_store
    original_commit = structured.apply_canonical_payload_transaction
    competing = current[1].model_copy(update={"title": "Concurrent Beta title correction"})
    intercepted = []

    def race(*, idempotency_key, mutations):
        if idempotency_key.startswith("knowledge-change:") and not intercepted:
            intercepted.append(idempotency_key)
            original_commit(idempotency_key="fixture-concurrent-target-update", mutations=[{
                "operation": "upsert", "collection": "knowledge_entries", "entity_id": competing.id,
                "project_name": "demo", "payload": competing.to_dict(),
                "expected_sha256": structured.record_payload_sha256("knowledge_entries", competing.id, project_name="demo"),
            }])
        return original_commit(idempotency_key=idempotency_key, mutations=mutations)

    monkeypatch.setattr(structured, "apply_canonical_payload_transaction", race)
    outcomes = _run(apply_dream_assimilation(backend, prepared=prepared, plan=plan))
    assert len(intercepted) == 1
    assert len(outcomes) == 2 and all(row["status"] != "applied" for row in outcomes), outcomes
    rows = _run(structured.knowledge_store.list_entries("demo"))
    assert {row.id: row.to_dict() for row in rows} == {
        current[0].id: current[0].to_dict(), competing.id: competing.to_dict()}


def test_dream_overlapping_multi_target_proposals_keep_all_current_rows(backend):
    from dataclasses import replace

    _root, current, _items, prepared = _prepared_multi_target_replacement(backend)
    owner = next(row for row in prepared.candidates if row.candidate_id == "candidate-0")
    competing = next(row for row in prepared.candidates if row.candidate_id == "candidate-1")
    competing = replace(competing, scope_verification=owner.scope_verification.model_copy(
        update={"candidate_index": 1}))
    prepared = replace(prepared, candidates=(owner, competing))
    plan = build_dream_maintenance_plan(prepared)
    assert len(plan) == 2 and all(point["disposition"] == "no_write" for point in plan)
    outcomes = _run(apply_dream_assimilation(backend, prepared=prepared, plan=plan))
    assert len(outcomes) == 2 and all(row["status"] != "applied" for row in outcomes)
    rows = _run(backend.structured_store.knowledge_store.list_entries("demo"))
    assert {row.id: row.to_dict() for row in rows} == {row.id: row.to_dict() for row in current}

def test_dream_never_retires_knowledge_from_a_truncated_source_excerpt(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-truncated-source",
        project_name="demo",
        title="Bounded source",
        statement="A truncated source is never enough to retire current knowledge.",
        module_path=["governance"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, current = _publish_current_knowledge(
        backend,
        entry,
        # The first byte after the bounded excerpt is whitespace.  The source
        # continues after it, so trimming that byte must not make Dream treat
        # this as a complete source and permit retirement.
        source_text=("x" * 16000) + " " + "current source continues here",
    )
    entry = current[0]

    from dataclasses import replace
    real_reopen = dream_module.reopen_dream_knowledge_sources

    async def bounded_reopen(*args, **kwargs):
        validation, reopened, effective = await real_reopen(*args, **kwargs)
        assert reopened and len(reopened[0].content) > 16000
        return validation, tuple(replace(item, content=item.content[:16000], truncated=True)
                                 for item in reopened), effective

    monkeypatch.setattr(dream_module, "reopen_dream_knowledge_sources", bounded_reopen)
    provider = _DreamVerificationProvider(support="contradicted")
    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
            semantic_provider=provider,
        )
    )

    assert run.items[0].final_action == "skipped"
    assert run.items[0].result["source_status"] == "truncated"
    assert provider.manifests == []
    assert _run(store.get_entry(entry.id, project_name="demo")) == entry


def test_dream_provider_failure_closes_the_processing_ledger_run(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = KnowledgeEntry(
        id="knowledge-provider-failure",
        project_name="demo",
        title="Provider failure",
        statement="Provider errors leave a terminal Dream receipt.",
        module_path=["governance"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, _current = _publish_current_knowledge(backend, entry)

    class _FailingProvider:
        name = "failing-dream-provider"

        def verify(self, *_args, **_kwargs):
            raise ProviderError("simulated provider failure", kind="transient")

    with pytest.raises(ProviderError, match="simulated provider failure"):
        _run(
            dream_once(
                backend,
                project_name="demo",
                project_root=project_root,
                config=None,
                source="agent",
                semantic_provider=_FailingProvider(),
            )
        )

    run = _run(backend.structured_store.list_dream_runs("demo", limit=1))[0]
    assert run.status == "failed"
    assert run.completed_at is not None
    assert "dream failed: ProviderError" in (run.notes or [])


def test_dream_provider_construction_failure_closes_the_processing_ledger_run(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = KnowledgeEntry(
        id="knowledge-provider-construction-failure",
        project_name="demo",
        title="Provider construction failure",
        statement="Provider construction errors leave a terminal Dream receipt.",
        module_path=["governance"],
        verified_at=datetime.now(timezone.utc) - timedelta(days=181),
    )
    project_root, _current = _publish_current_knowledge(backend, entry)

    def fail_provider_construction(_config: Any, _client: str) -> None:
        raise ProviderError("simulated provider construction failure", kind="transient")

    from harness_mem.autonomous.executors import registry as executor_registry

    monkeypatch.setattr(
        executor_registry,
        "build_semantic_executor",
        fail_provider_construction,
    )
    with pytest.raises(ProviderError, match="simulated provider construction failure"):
        _run(
            dream_once(
                backend,
                project_name="demo",
                project_root=project_root,
                config=MergedConfig(
                    distill_autonomous_enabled=True,
                ),
                source="agent",
                host_client="codex",
            )
        )

    run = _run(backend.structured_store.list_dream_runs("demo", limit=1))[0]
    assert run.status == "failed"
    assert run.completed_at is not None
    assert "dream failed: ProviderError" in (run.notes or [])


def test_dream_archives_latest_ignored_feedback_without_workspace_candidate(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-ignored",
        project_name="demo",
        title="Ignored retrieval",
        statement="Ignored current knowledge is rechecked before any truth change.",
        module_path=["retrieval"],
    )
    project_root, current = _publish_current_knowledge(backend, entry)
    entry = current[0]
    _run(
        record_retrieval_signal(
            backend,
            project_name="demo",
            signal_type="context_outcome",
            target_kind="knowledge_entry",
            target_id=entry.id,
            value=0.0,
            context={"outcome": "ignored"},
        )
    )

    run = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )

    feedback = next(item for item in run.items if item.source_kind == "knowledge_feedback")
    assert feedback.final_action == "failed"
    assert run.status == "failed"
    assert _run(store.get_entry(entry.id, project_name="demo")) == entry
    assert _run(store.list_candidates("demo")) == []
    _run(
        record_retrieval_signal(
            backend,
            project_name="demo",
            signal_type="context_outcome",
            target_kind="knowledge_entry",
            target_id=entry.id,
            value=-1.0,
            context={"outcome": "misleading"},
        )
    )
    second = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )
    second_feedback = next(
        item for item in second.items if item.source_kind == "knowledge_feedback"
    )
    assert second_feedback.source_id == entry.id


@pytest.mark.parametrize(
    ("negative_value", "negative_outcome"),
    [(0.0, "ignored"), (-1.0, "misleading")],
)
def test_dream_positive_feedback_does_not_create_a_pending_recheck(
    backend,
    monkeypatch: pytest.MonkeyPatch,
    negative_value: float,
    negative_outcome: str,
) -> None:
    store = backend.structured_store.knowledge_store
    entry = KnowledgeEntry(
        id="knowledge-feedback-recovered",
        project_name="demo",
        title="Recovered retrieval",
        statement="A later useful outcome supersedes an older negative signal.",
        module_path=["retrieval"],
    )
    project_root, current = _publish_current_knowledge(backend, entry)
    entry = current[0]

    _run(
        record_retrieval_signal(
            backend,
            project_name="demo",
            signal_type="context_outcome",
            target_kind="knowledge_entry",
            target_id=entry.id,
            value=negative_value,
            context={"outcome": negative_outcome},
        )
    )
    first = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )
    archived = next(
        item for item in first.items if item.source_kind == "knowledge_feedback"
    )
    assert archived.final_action == "failed"
    assert first.status == "failed"
    assert _run(store.list_candidates("demo")) == []

    _run(
        record_retrieval_signal(
            backend,
            project_name="demo",
            signal_type="context_outcome",
            target_kind="knowledge_entry",
            target_id=entry.id,
            value=1.0,
            context={"outcome": "used"},
        )
    )
    second = _run(
        dream_once(
            backend,
            project_name="demo",
            project_root=project_root,
            config=None,
            source="agent",
        )
    )

    assert not [item for item in second.items if item.source_kind == "knowledge_feedback"]
    assert _run(store.list_candidates("demo")) == []


def test_dream_auto_tick_persists_skipped_receipt_separately_from_runs(
    backend,
    tmp_path: Path,
) -> None:
    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_enabled=False),
            source="ide_hook",
            trigger_id="turn-42",
        )
    )

    assert payload["status"] == "skipped"
    assert payload["reason"] == "dream.auto.enabled is false"
    assert payload["tick_receipt"] == {"state": "recorded"}

    second_payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_enabled=False),
            source="ide_hook",
            trigger_id="turn-43",
        )
    )
    assert second_payload["tick_receipt"] == {"state": "recorded"}

    ledger = _run(latest_dream_ledger(backend, project_name="demo"))
    assert ledger["run"] is None
    assert [item["trigger_id"] for item in ledger["recent_ticks"]] == [
        "turn-42",
        "turn-43",
    ]
    assert ledger["last_tick"] == ledger["recent_ticks"][-1]
    assert ledger["last_tick"] == {
        "timestamp": ledger["last_tick"]["timestamp"],
        "status": "skipped",
        "reason": "dream.auto.enabled is false",
        "source": "ide_hook",
        "trigger_id": "turn-43",
        "job_id": None,
        "run_id": None,
        "last_run_id": None,
        "next_eligible_at": None,
        "receipt_state": "recorded",
    }

    status = _run(
        dream_status_snapshot(
            backend,
            project_name="demo",
            config=MergedConfig(dream_auto_enabled=False),
        )
    )
    assert status["last_tick_status"] == "skipped"
    assert status["last_tick_reason"] == "dream.auto.enabled is false"
    assert status["last_run_id"] is None


def test_reflection_job_claim_is_atomic_across_independent_connections(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "reflection-jobs.sqlite"
    indexes = [SQLiteIndex(db_path), SQLiteIndex(db_path)]
    for index in indexes:
        index.init_db()
    stores = [ReflectionJobStore(index) for index in indexes]
    barrier = threading.Barrier(2)
    stale_before = datetime.now(timezone.utc) - timedelta(minutes=5)

    def claim(slot: int):
        job = ReflectionJob(
            project_name="demo",
            project_root=str(tmp_path),
            kind="dream",
            phase="metabolism",
            status="processing",
            source="ide_hook",
        )
        barrier.wait()
        return stores[slot].save_if_no_active_processing(
            job,
            stale_before=stale_before,
        )

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(claim, (0, 1)))
        assert sum(result is None for result in results) == 1
        assert sum(result is not None for result in results) == 1
        assert len(stores[0].list(project_name="demo", status="processing")) == 1
    finally:
        for index in indexes:
            index.close()


def test_dream_rechecks_eligibility_after_winning_durable_claim(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    decisions = iter(
        (
            DreamSchedulerDecision(True, "eligible for dream run"),
            DreamSchedulerDecision(
                False,
                "no new project activity since the last dream run",
                last_run_id="other-run",
            ),
        )
    )

    async def fake_decision(*_args, **_kwargs):
        return next(decisions)

    async def fail_run(*_args, **_kwargs):
        raise AssertionError("stale eligibility must not start a second Dream")

    monkeypatch.setattr(dream_module, "dream_scheduler_decision", fake_decision)
    monkeypatch.setattr(dream_module, "_run_dream_with_progress_timeout", fail_run)

    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            source="ide_hook",
        )
    )

    assert payload["status"] == "skipped"
    assert payload["last_run_id"] == "other-run"
    jobs = backend.reflection_job_store.list(project_name="demo", kind="dream")
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert jobs[0].phase == "done"


def test_idle_scheduler_reports_activity_based_next_eligible_time(
    backend,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    latest_activity = now - timedelta(minutes=5)

    async def fake_latest_activity(*_args, **_kwargs):
        return latest_activity

    monkeypatch.setattr(dream_module, "_now", lambda: now)
    monkeypatch.setattr(
        dream_module,
        "_latest_project_activity",
        fake_latest_activity,
    )

    decision = _run(
        dream_module.dream_scheduler_decision(
            backend,
            project_name="demo",
            config=MergedConfig(
                dream_auto_trigger="idle",
                dream_auto_idle_seconds=900,
            ),
        )
    )

    assert decision.eligible is False
    assert decision.next_eligible_at == latest_activity + timedelta(minutes=15)


def test_dream_wall_clock_timeout_fails_job_and_records_tick(
    backend,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def always_eligible(*_args, **_kwargs):
        return DreamSchedulerDecision(True, "eligible for dream run")

    async def blocked_dream(run_backend, **kwargs):
        await run_backend.structured_store.save_dream_run(
            DreamRun(
                project_name="demo",
                status="processing",
                reflection_job_id=kwargs["reflection_job_id"],
                trigger_source="ide_hook",
            )
        )
        await asyncio.Event().wait()

    monkeypatch.setattr(dream_module, "dream_scheduler_decision", always_eligible)
    monkeypatch.setattr(dream_module, "dream_once", blocked_dream)
    # The fake blocks before any native request; no 300-second provider window
    # exists here. Keep the original one-second outer-watchdog assertion.
    monkeypatch.setattr(dream_module, "_verification_runtime_seconds", lambda _provider: 0)

    payload = _run(
        dream_auto_tick(
            backend,
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(dream_auto_max_runtime_seconds=1),
            source="ide_hook",
            trigger_id="timeout-turn",
        )
    )

    assert payload["status"] == "failed"
    assert payload["error"] == "dream slice watchdog exceeded scheduling plus native decision runtime"
    assert payload["tick_receipt"] == {"state": "recorded"}
    jobs = backend.reflection_job_store.list(project_name="demo", kind="dream")
    assert len(jobs) == 1
    assert jobs[0].status == "failed"
    assert jobs[0].phase == "done"
    assert jobs[0].completed_at is not None
    runs = _run(backend.structured_store.list_dream_runs("demo", limit=10))
    assert len(runs) == 1
    assert runs[0].status == "failed"
    assert runs[0].completed_at is not None
    assert "dream slice watchdog exceeded" in " ".join(runs[0].notes or [])


def test_post_turn_stages_before_waking_dream_with_embeddings_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    class DistillJobs:
        @staticmethod
        def get_distill_job(_job_id: str):
            return None

    class Backend:
        data_dir = tmp_path
        transcript_store = DistillJobs()

    async def fake_dream_tick(_backend, **kwargs):
        assert embeddings_disabled() is True
        assert kwargs["trigger_id"] == "turn-99"
        assert kwargs["trigger_job_id"] is None
        observed.append("dream")
        return {
            "success": True,
            "status": "skipped",
            "reason": "scheduler gates have not elapsed",
            "tick_receipt": {"state": "recorded"},
        }

    def fake_prepare_session_distill(**_kwargs):
        assert embeddings_disabled() is True
        observed.append("ingest")
        return {
            "success": True,
            "observation_count": 0,
            "distill_job_id": None,
        }

    monkeypatch.setattr(maintenance_module, "dream_auto_tick", fake_dream_tick)
    monkeypatch.setattr(
        tool_handlers,
        "tool_prepare_session_distill",
        fake_prepare_session_distill,
    )

    payload = _run(
        run_post_turn_maintenance(
            Backend(),
            project_name="demo",
            project_root=str(tmp_path),
            config=MergedConfig(),
            trigger_id="turn-99",
        )
    )

    assert observed == ["ingest", "dream"]
    assert payload["dream_tick"]["status"] == "skipped"
    assert payload["summary"]["dream_tick_receipt_state"] == "recorded"
