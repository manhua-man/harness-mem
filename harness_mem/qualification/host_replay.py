"""Deterministic native-host replay used by release qualification.

This is not another runtime scheduler. It is an explicit offline harness that
drives the same adapter, governance, distill, Dream, and wake boundaries used
by an installed client, while persisting a content-free result artifact.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from harness_mem.adapters.protocol import SessionAdapter
from harness_mem.autonomous.models import (
    AssimilationDecision,
    AssimilationPoint,
    CanonicalKnowledgeItem,
)
from harness_mem.commands.dream import dream_once
from harness_mem.commands.separated_assimilation import (
    apply_separated_assimilation,
    create_separated_candidates,
    prepare_separated_assimilation,
    validate_separated_assimilation_decision,
)
from harness_mem.commands.wake import build_wake_injection
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

_SAFE_REASON_CODES = frozenset(
    {
        "native_session_not_found",
        "invalid_native_session_record",
        "native_session_not_ingested",
        "distill_chunks_not_claimed",
        "candidate_missing_from_distill_evidence",
        "candidate_suggestion_failed",
        "candidate_not_promoted",
        "promoted_candidate_missing_from_sqlite",
        "promoted_candidate_missing_from_render",
        "markdown_export_became_authority",
        "dream_postprocess_failed",
        "promoted_candidate_missing_from_wake",
    }
)


@dataclass(frozen=True)
class HostReplayStage:
    """One content-free qualification stage result."""

    name: str
    status: str
    reason_code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HostReplayArtifact:
    """Auditable result of one native adapter-to-wake replay."""

    run_id: str
    host: str
    project_name: str
    status: str
    created_at: str
    source_id: str | None
    source_revision: str | None
    session_id: str | None
    capabilities: dict[str, str]
    stages: tuple[HostReplayStage, ...]
    failure_stage: str | None = None
    failure_type: str | None = None
    failure_digest: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            **asdict(self),
            "stages": [asdict(stage) for stage in self.stages],
        }


async def run_host_replay(
    *,
    host: str,
    adapter: SessionAdapter,
    backend: LocalMemoryBackend,
    project_name: str,
    project_root: Path,
    candidate_content: str,
    repository_evidence: Path,
    artifact_dir: Path | None = None,
    capabilities: dict[str, str] | None = None,
) -> HostReplayArtifact:
    """Replay one real native fixture through distill, Dream, and wake.

    Candidate wording is deterministic because release CI has no semantic
    Agent. The candidate still enters the separated candidate and repository-
    evidence gates, then reaches Markdown truth only through the normal
    assimilation boundary; the harness never writes durable truth directly.
    """

    run_id = str(uuid4())
    created_at = datetime.now(timezone.utc).isoformat()
    stages: list[HostReplayStage] = []
    source_id: str | None = None
    source_revision: str | None = None
    session_id: str | None = None
    failure_stage: str | None = "capture"
    failure: Exception | None = None

    try:
        sessions = await asyncio.to_thread(
            adapter.list_sessions,
            project_name,
            min_size_kb=0,
            limit=10,
        )
        if not sessions:
            raise RuntimeError("native_session_not_found")
        selected = sessions[0]
        session_id = str(selected.get("session_id") or selected.get("name") or "")
        session_path = selected.get("path")
        if not session_id or not isinstance(session_path, Path):
            raise RuntimeError("invalid_native_session_record")
        stages.append(
            HostReplayStage(
                name="capture",
                status="passed",
                details={"sessions_found": len(sessions)},
            )
        )

        failure_stage = "ingest"
        sync_parameters = inspect.signature(adapter.sync_session).parameters
        if "project_root" in sync_parameters:
            sync = await adapter.sync_session(  # type: ignore[call-arg]
                session_path,
                session_id,
                project_name,
                project_root=project_root,
            )
        else:
            sync = await adapter.sync_session(session_path, session_id, project_name)
        if sync.source is None or sync.distill_job_id is None:
            raise RuntimeError(sync.reason or "native_session_not_ingested")
        source_id = sync.source.id
        source_revision = sync.source.source_revision
        stages.append(
            HostReplayStage(
                name="ingest",
                status="passed",
                details={
                    "action": sync.action,
                    "observation_id": sync.observation_id,
                    "distill_job_id": sync.distill_job_id,
                    "raw_size_bytes": sync.source.raw_size_bytes,
                },
            )
        )

        failure_stage = "distill"
        lease_owner = f"qualification:{run_id}"
        claims = backend.transcript_store.claim_distill_chunks(
            sync.distill_job_id,
            lease_owner=lease_owner,
            limit=10_000,
        )
        if not claims:
            raise RuntimeError("distill_chunks_not_claimed")
        grounded_candidate = _ground_candidate_in_claimed_chunks(
            claims,
            candidate_content,
        )
        for chunk, _checkpoint in claims:
            backend.transcript_store.checkpoint_distill_chunk(
                sync.distill_job_id,
                chunk.id,
                lease_owner=lease_owner,
                result={
                    "summary_sha256": chunk.content_sha256,
                    "qualification": True,
                },
            )
        stages.append(
            HostReplayStage(
                name="distill",
                status="passed",
                details={"chunks_checkpointed": len(claims)},
            )
        )

        failure_stage = "candidate"
        candidate_ids = await create_separated_candidates(
            backend,
            project_name=project_name,
            distill_job_id=sync.distill_job_id,
            candidate_arguments=[
                {
                    "kind": "memory",
                    "content": grounded_candidate,
                    "evidence_basis": "repository",
                    "verification_outcome": "verified",
                    "verification_refs": [
                        {
                            "kind": "repository",
                            "locator": repository_evidence.relative_to(
                                project_root
                            ).as_posix(),
                            "content_sha256": hashlib.sha256(
                                repository_evidence.read_bytes()
                            ).hexdigest(),
                        }
                    ],
                }
            ],
        )
        if len(candidate_ids) != 1:
            raise RuntimeError("candidate_suggestion_failed")
        candidate_id = candidate_ids[0]
        stages.append(
            HostReplayStage(
                name="candidate",
                status="passed",
                details={"candidate_id": candidate_id},
            )
        )

        failure_stage = "assimilation"
        prepared = await prepare_separated_assimilation(
            backend,
            project_name=project_name,
            project_root=str(project_root),
            candidate_ids=candidate_ids,
        )
        if prepared.eligible_candidate_ids != tuple(candidate_ids):
            raise RuntimeError("candidate_not_promoted")
        plan = validate_separated_assimilation_decision(
            prepared,
            AssimilationDecision(
                points=[
                    AssimilationPoint(
                        candidate_id=candidate_id,
                        disposition="add",
                        reason=(
                            "Repository evidence verifies this native replay "
                            "qualification fact."
                        ),
                        knowledge_items=[
                            CanonicalKnowledgeItem(
                                title="Native host replay qualification",
                                statement=grounded_candidate,
                                topic_path=["Native host integration"],
                                claim_kind="implementation_fact",
                            )
                        ],
                    )
                ]
            ),
        )
        assimilation = await apply_separated_assimilation(
            backend,
            project_name=project_name,
            project_root=str(project_root),
            candidate_ids=candidate_ids,
            plan=plan,
        )
        if assimilation.get("promoted") != 1:
            raise RuntimeError("candidate_not_promoted")
        knowledge_entries = await backend.structured_store.knowledge_store.list_entries(
            project_name
        )
        if not any(entry.statement == grounded_candidate for entry in knowledge_entries):
            raise RuntimeError("promoted_candidate_missing_from_sqlite")
        rendered = await backend.structured_store.knowledge_store.render_markdown(
            project_name
        )
        if grounded_candidate not in rendered:
            raise RuntimeError("promoted_candidate_missing_from_render")
        if (project_root / ".harness-mem" / "session-knowledge-base.md").exists():
            raise RuntimeError("markdown_export_became_authority")
        stages.append(
            HostReplayStage(
                name="assimilation",
                status="passed",
                details={
                    "promoted": assimilation.get("promoted"),
                    "knowledge_entries": len(knowledge_entries),
                    "render_sha256": hashlib.sha256(
                        rendered.encode("utf-8")
                    ).hexdigest(),
                },
            )
        )

        failure_stage = "dream"
        dream = await dream_once(
            backend,
            project_name=project_name,
            project_root=project_root,
            source="agent",
        )
        if dream.status != "completed":
            raise RuntimeError("dream_postprocess_failed")
        stages.append(
            HostReplayStage(
                name="dream",
                status="passed",
                details={
                    "dream_status": dream.status,
                    "dream_items": len(dream.items),
                },
            )
        )

        failure_stage = "wake"
        wake = await build_wake_injection(
            backend,
            project_name,
            apply_surface_side_effects=False,
        )
        if grounded_candidate not in wake:
            raise RuntimeError("promoted_candidate_missing_from_wake")
        stages.append(
            HostReplayStage(
                name="wake",
                status="passed",
                details={"wake_sha256": hashlib.sha256(wake.encode("utf-8")).hexdigest()},
            )
        )
        status = "passed"
        failure_stage = None
    except Exception as exc:  # qualification must preserve an ordinary failure row
        failure = exc
        stages.append(
            HostReplayStage(
                name=failure_stage or "capture",
                status="failed",
                reason_code=(
                    str(exc)
                    if str(exc) in _SAFE_REASON_CODES
                    else type(exc).__name__
                ),
            )
        )
        status = "failed"

    artifact = HostReplayArtifact(
        run_id=run_id,
        host=host,
        project_name=project_name,
        status=status,
        created_at=created_at,
        source_id=source_id,
        source_revision=source_revision,
        session_id=session_id,
        capabilities=dict(capabilities or {}),
        stages=tuple(stages),
        failure_stage=failure_stage if failure is not None else None,
        failure_type=type(failure).__name__ if failure is not None else None,
        failure_digest=(
            hashlib.sha256(str(failure).encode("utf-8")).hexdigest()
            if failure is not None
            else None
        ),
    )
    if artifact_dir is not None:
        artifact_dir.mkdir(parents=True, exist_ok=True)
        (artifact_dir / f"{host}-{run_id}.json").write_text(
            json.dumps(artifact.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
    return artifact


def _ground_candidate_in_claimed_chunks(
    claims: list[tuple[Any, Any]],
    expected_content: str,
) -> str:
    """Return candidate text only when the captured/distill evidence contains it."""

    for chunk, _checkpoint in claims:
        start = chunk.raw_content.find(expected_content)
        if start >= 0:
            return chunk.raw_content[start : start + len(expected_content)]
    raise RuntimeError("candidate_missing_from_distill_evidence")
