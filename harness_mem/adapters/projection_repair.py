"""Repair missing derived transcript projections from verified native sources."""

from __future__ import annotations

from tempfile import TemporaryDirectory
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from harness_mem.adapters import AdapterRegistry
from harness_mem.core.schemas.observation import Observation
from harness_mem.native_source_cleanup import path_from_local_file_uri
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.transcript_chunking import transcript_bytes_revision

_SHARED_SOURCE_KINDS = frozenset(
    {"sqlite-session-export", "antigravity-cli-session-export"}
)
_CODEX_CONVERSATION_PARSERS = frozenset(
    {"codex-conversation-v2", "codex-archive-conversation-v2"}
)


def repair_source_observation_projection(
    backend: LocalMemoryBackend,
    *,
    source_id: str,
    source_revision: str,
) -> Observation | None:
    """Rebuild one missing Observation projection from the byte-exact ledger.

    This is a bounded compatibility repair for old lossless jobs whose raw
    ledger is intact but whose derived Observation is absent or stale in
    canonical Storage v2. The projection remains in memory so a concurrent
    ingest cannot be overwritten by an older repair. Shared-container exports
    are excluded because their ledger bytes are deterministic row exports
    rather than a parseable native database.
    """

    source = backend.transcript_store.get_source(source_id)
    revision = backend.transcript_store.get_revision(source_id, source_revision)
    if source is None or revision is None:
        return None
    if revision.source_kind in _SHARED_SOURCE_KINDS:
        return None
    try:
        stored_bytes = backend.transcript_store.reconstruct_raw(
            source_id,
            source_revision=source_revision,
        )
    except (KeyError, ValueError):
        return None
    if transcript_bytes_revision(stored_bytes) != source_revision:
        return None

    if revision.parser_version in _CODEX_CONVERSATION_PARSERS:
        # New Codex snapshots intentionally keep only the permitted
        # user/assistant transcript in the ledger.  It is already the exact
        # search projection, so replaying it through the native JSONL parser
        # would fail (and would incorrectly require host-only context again).
        observation = Observation(
            session_id=revision.session_id,
            client=revision.client,
            raw_content=stored_bytes.decode("utf-8", errors="replace"),
            content_type="transcript",
        )
    else:
        locator = str(revision.metadata.get("native_source_uri") or revision.source_uri)
        try:
            source_path = path_from_local_file_uri(locator)
        except ValueError:
            return None
        try:
            with TemporaryDirectory(prefix="harness-mem-projection-") as temp_dir:
                replay_path = Path(temp_dir) / source_path.name
                replay_path.write_bytes(stored_bytes)
                adapter = AdapterRegistry.build(revision.client, None)
                observation = adapter.session_to_observation(
                    replay_path,
                    revision.session_id,
                    revision.project_name,
                )
        except (KeyError, OSError, ValueError):
            return None

    observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
    observation.id = observation_id
    observation.metadata.update(
        {
            "project_name": revision.project_name,
            "project_root": revision.project_root,
            "transcript_source_id": source.id,
            "source_revision": revision.source_revision,
            "source_uri": revision.source_uri,
            "source_coverage": "complete",
            "source_chunk_count": revision.chunk_count,
            "source_size_bytes": revision.raw_size_bytes,
            "source_content_sha256": revision.raw_sha256,
            "normalized_content_sha256": revision.normalized_sha256,
            "observation_kind": "derived_search_rendering",
            "projection_repair": (
                "verified_transcript_ledger"
                if source.source_revision == source_revision
                else "verified_historical_transcript_ledger"
            ),
        }
    )
    return observation


__all__ = ["repair_source_observation_projection"]
