from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.qualification.host_replay import run_host_replay
from harness_mem.qualification.native_fixtures import (
    QUALIFICATION_HOSTS,
    build_native_fixture_adapter,
)
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from tests.support.host_contracts import HOST_NAMES


def test_qualification_host_matrix_matches_public_contract() -> None:
    assert tuple(QUALIFICATION_HOSTS) == HOST_NAMES


@pytest.mark.parametrize("host", HOST_NAMES)
def test_native_host_replay_reaches_dream_and_wake(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> None:
        project = tmp_path / "project with space" / host
        project.mkdir(parents=True)
        project_name = f"qualification-{host}"
        fact = f"{host} native replay preserves the qualified memory path"
        evidence = project / "qualification-evidence.txt"
        evidence.write_text(fact, encoding="utf-8")
        backend = LocalMemoryBackend(tmp_path / f"data-{host}")
        await backend.init()
        try:
            adapter = build_native_fixture_adapter(
                host,
                root=tmp_path / f"native-{host}",
                backend=backend,
                project=project,
                project_name=project_name,
                fact=fact,
            )
            capabilities = AdapterRegistry.capabilities(host)
            assert capabilities is not None
            artifact = await run_host_replay(
                host=host,
                adapter=adapter,
                backend=backend,
                project_name=project_name,
                project_root=project,
                candidate_content=fact,
                repository_evidence=evidence,
                artifact_dir=tmp_path / "artifacts",
                capabilities={
                    "capture_mode": capabilities.capture_mode,
                    "native_cleanup_mode": capabilities.native_cleanup_mode,
                },
            )

            assert artifact.status == "passed"
            assert [stage.name for stage in artifact.stages] == [
                "capture",
                "ingest",
                "distill",
                "candidate",
                "assimilation",
                "dream",
                "wake",
            ]
            assert all(stage.status == "passed" for stage in artifact.stages)
            knowledge_store = backend.structured_store.knowledge_store
            markdown = await knowledge_store.render_markdown(project_name)
            assert fact in markdown
            assert "distill_job_id" not in markdown
            assert "verification_reason_codes" not in markdown
            assert not (
                project / ".harness-mem" / "session-knowledge-base.md"
            ).exists()
            assert (
                await backend.structured_store.list_memory_entries(
                    project_name, limit=20
                )
            ) == []
            candidates = await knowledge_store.list_candidates(project_name)
            assert len(candidates) == 1
            assert candidates[0].status == "assimilated"
            candidate_evidence = await knowledge_store.list_evidence(
                candidates[0].id
            )
            assert len(candidate_evidence) == 1
            assert candidate_evidence[0].evidence_basis == "repository"
            assert candidate_evidence[0].verification_outcome == "verified"
            assert await knowledge_store.list_decisions(candidates[0].id) == []
            mutations = await knowledge_store.list_mutations(project_name)
            assert len(mutations) == 1
            assert mutations[0].disposition == "add"
            written = list((tmp_path / "artifacts").glob(f"{host}-*.json"))
            assert len(written) == 1
            artifact_text = written[0].read_text(encoding="utf-8")
            assert fact not in artifact_text
            assert json.loads(artifact_text)["status"] == "passed"
        finally:
            await backend.close()

    asyncio.run(exercise())
def test_opencode_replay_releases_native_database_handle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows release smoke must be able to remove the native fixture."""

    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> Path:
        project = tmp_path / "project-opencode-close"
        project.mkdir()
        fact = "opencode replay closes its read-only source handle"
        evidence = project / "qualification-evidence.txt"
        evidence.write_text(fact, encoding="utf-8")
        backend = LocalMemoryBackend(tmp_path / "data-opencode-close")
        await backend.init()
        database = tmp_path / "native-opencode-close" / "opencode.db"
        try:
            adapter = build_native_fixture_adapter(
                "opencode",
                root=database.parent,
                backend=backend,
                project=project,
                project_name="qualification-opencode",
                fact=fact,
            )
            artifact = await run_host_replay(
                host="opencode",
                adapter=adapter,
                backend=backend,
                project_name="qualification-opencode",
                project_root=project,
                candidate_content=fact,
                repository_evidence=evidence,
            )
            assert artifact.status == "passed"
        finally:
            await backend.close()
        return database

    database = asyncio.run(exercise())
    database.unlink()
    assert not database.exists()


def test_host_replay_persists_content_free_failure_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> None:
        project = tmp_path / "project"
        project.mkdir()
        evidence = project / "qualification-evidence.txt"
        evidence.write_text("failure fixture secret", encoding="utf-8")
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            adapter = ClaudeCodeAdapter(backend, sessions_dir=tmp_path / "missing")
            artifact = await run_host_replay(
                host="claude-code",
                adapter=adapter,
                backend=backend,
                project_name="missing-project",
                project_root=project,
                candidate_content="failure fixture secret",
                repository_evidence=evidence,
                artifact_dir=tmp_path / "artifacts",
            )
            assert artifact.status == "failed"
            assert artifact.failure_stage == "capture"
            assert artifact.failure_type == "RuntimeError"
            artifact_text = next((tmp_path / "artifacts").glob("*.json")).read_text(
                encoding="utf-8"
            )
            assert "failure fixture secret" not in artifact_text
            assert "native_session_not_found" in artifact_text
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_host_replay_does_not_swallow_process_control_exceptions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    class InterruptingAdapter:
        def list_sessions(self, *_args, **_kwargs):
            raise SystemExit(17)

    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "interrupt-data")
        await backend.init()
        try:
            with pytest.raises(SystemExit) as exc_info:
                await run_host_replay(
                    host="codex",
                    adapter=InterruptingAdapter(),  # type: ignore[arg-type]
                    backend=backend,
                    project_name="interrupt-project",
                    project_root=tmp_path,
                    candidate_content="unused",
                    repository_evidence=tmp_path / "unused.txt",
                    artifact_dir=tmp_path / "interrupt-artifacts",
                )
            assert exc_info.value.code == 17
            assert not (tmp_path / "interrupt-artifacts").exists()
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_host_replay_rejects_candidate_missing_from_captured_chunks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> None:
        project = tmp_path / "project-grounding"
        project.mkdir()
        evidence = project / "qualification-evidence.txt"
        evidence.write_text("repository proof", encoding="utf-8")
        backend = LocalMemoryBackend(tmp_path / "data-grounding")
        await backend.init()
        try:
            adapter = build_native_fixture_adapter(
                "codex",
                root=tmp_path / "native-grounding",
                backend=backend,
                project=project,
                project_name="qualification-grounding",
                fact="captured transcript fact",
            )
            artifact = await run_host_replay(
                host="codex",
                adapter=adapter,
                backend=backend,
                project_name="qualification-grounding",
                project_root=project,
                candidate_content="candidate absent from transcript",
                repository_evidence=evidence,
                artifact_dir=tmp_path / "artifacts-grounding",
            )

            assert artifact.status == "failed"
            assert artifact.failure_stage == "distill"
            assert artifact.stages[-1].reason_code == (
                "candidate_missing_from_distill_evidence"
            )
        finally:
            await backend.close()

    asyncio.run(exercise())


def test_host_replay_never_persists_identifier_shaped_exception_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> None:
        project = tmp_path / "project-private-error"
        project.mkdir()
        evidence = project / "qualification-evidence.txt"
        evidence.write_text("repository proof", encoding="utf-8")
        backend = LocalMemoryBackend(tmp_path / "data-private-error")
        await backend.init()
        try:
            adapter = ClaudeCodeAdapter(backend, sessions_dir=tmp_path / "missing")

            def fail_scan(*_args, **_kwargs):
                raise RuntimeError("PrivateToken123")

            monkeypatch.setattr(adapter, "list_sessions", fail_scan)
            artifact = await run_host_replay(
                host="claude-code",
                adapter=adapter,
                backend=backend,
                project_name="qualification-private-error",
                project_root=project,
                candidate_content="unused candidate",
                repository_evidence=evidence,
                artifact_dir=tmp_path / "artifacts-private-error",
            )

            artifact_text = next(
                (tmp_path / "artifacts-private-error").glob("*.json")
            ).read_text(encoding="utf-8")
            assert artifact.status == "failed"
            assert artifact.stages[-1].reason_code == "RuntimeError"
            assert "PrivateToken123" not in artifact_text
        finally:
            await backend.close()

    asyncio.run(exercise())
