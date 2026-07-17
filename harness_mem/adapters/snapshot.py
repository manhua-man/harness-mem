"""Shared lossless session snapshot persistence for transcript adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.capture_policy import (
    decide_capture,
    redact_private_bytes,
    redact_private_text,
)
from harness_mem.config.merge import MergedConfig, load_merged_config
from harness_mem.transcript_chunking import (
    chunk_transcript_text,
    sha256_bytes,
    sha256_text,
    transcript_bytes_revision,
    transcript_source_id,
)


@dataclass(frozen=True)
class TranscriptSyncResult:
    """Outcome of synchronizing one native host session revision."""

    action: str
    source: TranscriptSource | None
    observation_id: str | None
    distill_job_id: str | None
    reason: str | None = None

    @property
    def changed(self) -> bool:
        return self.action in {"ingested", "updated"}


async def persist_session_snapshot(
    backend: MemoryBackend,
    observation: Observation,
    *,
    project_name: str,
    project_root: str,
    client: str,
    session_id: str,
    source_kind: str,
    source_uri: str,
    source_text: str,
    raw_bytes: bytes | None = None,
    mtime_ns: int | None = None,
    sequence_count: int = 0,
    parser_version: str = "transcript-v1",
    reuse_logical_session: bool = False,
) -> TranscriptSyncResult:
    """Persist a complete source revision and upsert its search observation."""

    # Legacy/import callers may preserve a no-longer-mounted project root in
    # transcript metadata.  They keep safe defaults; live project calls load
    # the merged user/project policy from the existing root.
    config = (
        load_merged_config(project_root)
        if Path(project_root).is_absolute() and Path(project_root).is_dir()
        else MergedConfig()
    )
    capture_decision = decide_capture(
        config,
        client=client,
        session_id=session_id,
        source_uri=source_uri,
    )
    if not capture_decision.admitted:
        return TranscriptSyncResult(
            action="ignored",
            source=None,
            observation_id=None,
            distill_job_id=None,
            reason=capture_decision.reason,
        )

    private_span_count = 0
    if config.capture_private_tags:
        source_text, text_redactions = redact_private_text(source_text)
        native_input = raw_bytes if raw_bytes is not None else source_text.encode("utf-8")
        native_bytes, byte_redactions = redact_private_bytes(native_input)
        private_span_count = max(text_redactions, byte_redactions)
        # The adapter's searchable rendering is also evidence and must not keep
        # private content that the immutable ledger rejected.
        observation.raw_content, observation_redactions = redact_private_text(
            observation.raw_content
        )
        private_span_count = max(private_span_count, observation_redactions)
    else:
        native_bytes = raw_bytes if raw_bytes is not None else source_text.encode("utf-8")

    requested_source_uri = source_uri
    source_id = transcript_source_id(
        client=client,
        project_name=project_name,
        session_id=session_id,
        source_uri=source_uri,
    )
    revision = transcript_bytes_revision(native_bytes)
    raw_digest = sha256_bytes(native_bytes)
    normalized_digest = sha256_text(source_text)
    existing_source = backend.transcript_store.find_source(
        project_name=project_name,
        client=client,
        session_id=session_id,
        source_uri=source_uri,
    )
    if existing_source is None and reuse_logical_session:
        logical_matches = [
            source
            for source in backend.transcript_store.list_sources(
                project_name=project_name,
                client=client,
            )
            if source.session_id == session_id
        ]
        if len(logical_matches) == 1:
            existing_source = logical_matches[0]
            source_id = existing_source.id
            source_uri = existing_source.source_uri
    if existing_source is None:
        existing_source = _find_moved_source(
            backend,
            project_name=project_name,
            client=client,
            session_id=session_id,
            native_bytes=native_bytes,
        )
        if existing_source is not None:
            source_id = existing_source.id
            # Keep the first verified locator as the canonical key. Current and
            # historical locations remain auditable in native_source_aliases.
            source_uri = existing_source.source_uri
    action = (
        "ingested"
        if existing_source is None
        else "unchanged"
        if existing_source.source_revision == revision
        else "updated"
    )
    source = TranscriptSource(
        id=source_id,
        project_name=project_name,
        project_root=project_root,
        client=client,
        session_id=session_id,
        source_kind=source_kind,
        source_uri=source_uri,
        source_revision=revision,
        raw_sha256=raw_digest,
        normalized_sha256=normalized_digest,
        raw_size_bytes=len(native_bytes),
        normalized_size_bytes=len(source_text.encode("utf-8")),
        mtime_ns=mtime_ns,
        parser_version=parser_version,
        status="syncing",
        coverage="unknown",
        sequence_count=sequence_count,
        metadata={
            **(dict(existing_source.metadata) if existing_source is not None else {}),
            "native_timestamp": observation.timestamp.isoformat()
            if observation.timestamp
            else None,
            "native_source_uri": requested_source_uri,
            "native_source_aliases": sorted(
                {
                    *(
                        existing_source.metadata.get("native_source_aliases", [])
                        if existing_source is not None
                        else []
                    ),
                    requested_source_uri,
                }
            ),
            "capture_private_spans_removed": private_span_count,
            "capture_policy": "project_merged_v1",
        },
        created_at=(
            existing_source.created_at
            if existing_source is not None
            else datetime.now(timezone.utc)
        ),
    )
    chunks = chunk_transcript_text(
        source_text,
        source_id=source_id,
        project_name=project_name,
        client=client,
        session_id=session_id,
        source_revision=revision,
    )

    observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
    stored_observation = await backend.verbatim_store.get(observation_id)
    observation_is_current = bool(
        stored_observation
        and stored_observation.metadata.get("source_revision") == revision
    )
    if action != "unchanged":
        backend.transcript_store.save_snapshot(source, chunks, raw_bytes=native_bytes)
    else:
        assert existing_source is not None
        if (
            existing_source.status == "missing"
            or requested_source_uri != existing_source.metadata.get("native_source_uri")
        ):
            source.status = "synced" if existing_source.status == "missing" else existing_source.status
            source.coverage = existing_source.coverage
            source.chunk_count = existing_source.chunk_count
            source.synced_at = (
                datetime.now(timezone.utc)
                if existing_source.status == "missing"
                else existing_source.synced_at
            )
            if existing_source.status == "missing":
                source.metadata.pop("missing_since", None)
                source.metadata.pop("missing_reason", None)
                if source.synced_at is not None:
                    source.metadata["reappeared_at"] = source.synced_at.isoformat()
            backend.transcript_store.save_source(source)
        else:
            source = existing_source

    if not observation_is_current:
        observation.id = observation_id
        observation.metadata.update(
            {
                "project_name": project_name,
                "project_root": project_root,
                "transcript_source_id": source_id,
                "source_revision": revision,
                "source_uri": source_uri,
                "source_coverage": "complete",
                "source_chunk_count": len(chunks),
                "source_size_bytes": len(native_bytes),
                "source_content_sha256": raw_digest,
                "normalized_content_sha256": normalized_digest,
                "observation_kind": "derived_search_rendering",
            }
        )
        await backend.verbatim_store.save(observation)

    distill_job = backend.transcript_store.enqueue_distill_job(
        source.id,
        active_limit=config.distill_auto_target_backlog,
        recent_first=config.distill_auto_recent_first,
    )

    return TranscriptSyncResult(
        action=action,
        source=source,
        observation_id=observation_id,
        distill_job_id=distill_job.id,
    )


def _find_moved_source(
    backend: MemoryBackend,
    *,
    project_name: str,
    client: str,
    session_id: str,
    native_bytes: bytes,
) -> TranscriptSource | None:
    """Find one safely provable moved locator without merging same-id sessions.

    A session id alone is not a source identity: some hosts reuse it across
    containers. We therefore merge locators only when the newly read native
    bytes are exactly an old revision or append the old raw revision unchanged.
    """

    candidates = backend.transcript_store.list_sources_for_session(
        project_name=project_name,
        client=client,
        session_id=session_id,
    )
    matches: list[TranscriptSource] = []
    for candidate in candidates:
        try:
            previous = backend.transcript_store.reconstruct_raw(candidate.id)
        except (KeyError, ValueError):
            continue
        if native_bytes == previous or native_bytes.startswith(previous):
            matches.append(candidate)
    return matches[0] if len(matches) == 1 else None


__all__ = ["TranscriptSyncResult", "persist_session_snapshot"]
