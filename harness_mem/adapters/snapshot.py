"""Shared lossless session snapshot persistence for transcript adapters."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.interfaces.memory_backend import MemoryBackend
from harness_mem.core.schemas.observation import Observation
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.adapters.protocol import Issue
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
from harness_mem.native_source_cleanup import build_native_cleanup_descriptor

if TYPE_CHECKING:
    from harness_mem.adapters.source_inspection import InspectedSource


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


def _authored_capture_hashes(before: str, after: str, authored: list[str], *, private_tags: bool,
                            speaker: str = "user") -> list[str]:
    """Bind visible role markers to their original native message positions."""
    from harness_mem.capture_policy import PRIVATE_REDACTION, _PRIVATE_TEXT_RE
    from harness_mem.mcp.distill_projection import _ENTRY_RE, _TURN_HEADING_RE, _parse_exchanges

    expected = [text for text in authored if text.strip()]
    original = list(_ENTRY_RE.finditer(before))
    original_users: list[str] = []
    native_markers: list[int] = []
    for index, match in enumerate(original):
        if match.group(1) == speaker.title():
            end = original[index + 1].start() if index + 1 < len(original) else len(before)
            original_users.append(before[match.end():end].strip())
            native_markers.append(match.start(1))
    # Do not remove headings or fold duplicates before proving native roles.
    if original_users != expected:
        return []
    privacy_edits = [(m.start(), m.end(), len(PRIVATE_REDACTION))
                     for m in _PRIVATE_TEXT_RE.finditer(before)] if private_tags else []
    if after != (redact_private_text(before)[0] if private_tags else before):
        return []
    heading_edits = [(m.start(), m.end(), 0) for m in _TURN_HEADING_RE.finditer(after)]

    def surviving_position(position: int, edits: list[tuple[int, int, int]]) -> int | None:
        delta = 0
        for start, end, replacement_size in edits:
            if start <= position < end:
                return None
            if end <= position:
                delta += replacement_size - (end - start)
        return position + delta

    permitted = [(redact_private_text(text)[0] if private_tags else text).strip()
                 for text in expected]
    marker_bodies: dict[int, str] = {}
    for position, body in zip(native_markers, permitted):
        mapped = surviving_position(position, privacy_edits)
        if mapped is not None:
            mapped = surviving_position(mapped, heading_edits)
        if mapped is not None:
            marker_bodies[mapped] = body
    normalized = _TURN_HEADING_RE.sub("", after)
    visible = list(_ENTRY_RE.finditer(normalized))
    for index, match in enumerate(visible):
        if match.group(1) != speaker.title():
            continue
        end = visible[index + 1].start() if index + 1 < len(visible) else len(normalized)
        if marker_bodies.get(match.start(1)) != normalized[match.end():end].strip():
            return []
    captured_users = [user for exchange in _parse_exchanges(after)[1] for user in exchange[speaker]]
    return [sha256_text(user) for user in captured_users]


def _native_codex_authored_texts(native: bytes) -> tuple[str, list[str], list[str]] | None:
    """Prove both role arrays from structured native bytes, never prose labels."""
    from harness_mem.adapters.parser import parse_codex_archive_jsonl_session, render_codex_conversation
    from harness_mem.mcp.distill_projection import _ENTRY_RE, _parse_exchanges
    from harness_mem.rust_core import scan_jsonl

    issues: list[Issue] = []
    try:
        text = native.decode("utf-8-sig")
    except UnicodeError:
        return None
    if not text.lstrip().startswith("{"):
        return None
    scanned = scan_jsonl(text)
    if scanned.errors or not scanned.records:
        return None
    actor_types = {"user": "user", "assistant": "assistant", "tool": "tool",
                   "user_message": "user", "agent_message": "assistant",
                   "function_call_output": "tool"}
    for record in scanned.records:
        payload = record.get("payload", record)
        if not isinstance(payload, dict):
            return None
        role_values = [record.get("role"), payload.get("role")]
        # Both locations count: a permissive parser may ignore the outer
        # message when payload is present, but conflicting authors are unsafe.
        for container in (record, payload):
            message = container.get("message")
            if isinstance(message, dict):
                role_values.append(message.get("role"))
        if any(value is not None and not isinstance(value, str) for value in role_values):
            return None
        roles = {value for value in role_values if isinstance(value, str)}
        for value in (record.get("type"), payload.get("type")):
            if value is not None and not isinstance(value, str):
                return None
            if value in actor_types:
                roles.add(actor_types[value])
        if len(roles) > 1:
            return None
        # Native role labels embedded in tools/arguments/quoted bodies cannot
        # manufacture report authorship. Check bytes before projection drops
        # tools or folds duplicate records, including otherwise ignored fields.
        pending = [record]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str) and any(
                match.group(1) in {"User", "Assistant"} for match in _ENTRY_RE.finditer(value)
            ):
                return None
    meta, turns = parse_codex_archive_jsonl_session(Path("frozen.jsonl"), content=text, issues=issues)
    if meta.get("invalid_json_lines") or any(issue.get("level") == "error" for issue in issues):
        return None
    rendering = render_codex_conversation(turns)
    if not rendering:
        return None
    users = [str(turn.get("user") or "").strip() for turn in turns if str(turn.get("user") or "").strip()]
    assistants = [message for turn in turns if str(turn.get("user") or "").strip()
                  for message in dict.fromkeys(str(value or "").strip() for value in turn.get("assistant") or [])
                  if message]
    exchanges = _parse_exchanges(rendering)[1]
    for speaker, authored in (("user", users), ("assistant", assistants)):
        expected = [sha256_text(value) for exchange in exchanges for value in exchange[speaker]]
        if _authored_capture_hashes(rendering, rendering, authored, private_tags=False, speaker=speaker) != expected:
            return None
    return rendering, users, assistants


def _native_claude_rendering(native: bytes, session_id: str) -> str | None:
    """Rebuild Claude prose only from structurally proved native speakers."""
    from harness_mem.adapters.parser import parse_claude_jsonl_session, render_claude_conversation
    from harness_mem.mcp.distill_projection import _ENTRY_RE
    from harness_mem.rust_core import scan_jsonl

    try:
        text = native.decode("utf-8-sig")
    except UnicodeError:
        return None
    scanned = scan_jsonl(text)
    if scanned.errors or not scanned.records:
        return None
    for record in scanned.records:
        role = record.get("type")
        if role not in {"user", "assistant"}:
            continue
        message = record.get("message")
        if (not isinstance(message, dict) or message.get("role") != role
                or record.get("role", role) != role
                or record.get("sessionId", session_id) != session_id):
            return None
        body = message.get("content", "")
        if not isinstance(body, (str, list)) or (role == "assistant" and not isinstance(body, list)):
            return None
        for item in body if isinstance(body, list) else []:
            if not isinstance(item, dict):
                return None
            if item.get("type") == "text" and not isinstance(item.get("text", ""), str):
                return None
            if item.get("type") == "tool_use" and not isinstance(item.get("name", ""), str):
                return None
    turns = parse_claude_jsonl_session(Path("frozen.jsonl"), content=text, on_error="raise")
    if not turns:
        return None
    # Quoted prose must not manufacture an extra native role in the renderer.
    for turn in turns:
        bodies = [turn.get("user") or "", *(turn.get("assistant") or [])]
        if any(not isinstance(body, str) or _ENTRY_RE.search(body) for body in bodies):
            return None
        if any(_ENTRY_RE.search(tool["name"]) for tool in turn.get("tools") or []):
            return None
    return render_claude_conversation(turns, session_id)


def _native_source_timestamp(native: bytes, client: str) -> str | None:
    """Read a native timestamp without substituting observation/capture/mtime."""
    from harness_mem.rust_core import scan_jsonl

    if client not in {"codex", "codex-archive", "cursor", "claude-code"}:
        return None
    try:
        scanned = scan_jsonl(native.decode("utf-8-sig"))
    except UnicodeError:
        return None
    if scanned.errors:
        return None
    for record in scanned.records:
        payload = record.get("payload")
        values = ([payload.get("timestamp")] if record.get("type") == "session_meta" and isinstance(payload, dict) else [])
        values.append(record.get("timestamp"))
        for value in values:
            if not isinstance(value, str) or not value.strip():
                continue
            try:
                datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                continue
            return value
    return None


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
    native_input_bytes: bytes | None = None,
    mtime_ns: int | None = None,
    sequence_count: int = 0,
    parser_version: str = "transcript-v1",
    reuse_logical_session: bool = False,
    authored_user_texts: list[str] | None = None,
    authored_assistant_texts: list[str] | None = None,
    capture_config: MergedConfig | None = None,
    source_context_roots: list[str] | None = None,
    native_input_digest: str | None = None,
) -> TranscriptSyncResult:
    """Persist a complete source revision and upsert its search observation."""

    # Keep a content-free digest of the bytes that actually live in the host.
    # ``raw_sha256`` below may describe a redacted capture when private-tag
    # filtering is enabled, so it cannot safely be used as a compare-and-swap
    # guard before removing the native source.
    source_input = raw_bytes if raw_bytes is not None else source_text.encode("utf-8")
    native_input = native_input_bytes if native_input_bytes is not None else source_input
    native_input_sha256 = sha256_bytes(native_input)
    if native_input_digest is not None:
        if (len(native_input_digest) != 64
                or any(char not in "0123456789abcdef" for char in native_input_digest)):
            raise ValueError("native input digest must be SHA256")
        if native_input_bytes is not None and native_input_digest != native_input_sha256:
            raise ValueError("native input bytes and digest differ")
        native_input_sha256 = native_input_digest

    # Legacy/import callers may preserve a no-longer-mounted project root in
    # transcript metadata.  They keep safe defaults; live project calls load
    # the merged user/project policy from the existing root.
    config = capture_config or (
        load_merged_config(project_root)
        if Path(project_root).is_absolute() and Path(project_root).is_dir()
        else load_merged_config(None)
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

    original_source_text = source_text
    private_span_count = 0
    if config.capture_private_tags:
        source_text, text_redactions = redact_private_text(source_text)
        if (
            client in {"codex", "codex-archive"}
            and parser_version in {"codex-conversation-v2", "codex-conversation-v3", "codex-archive-conversation-v2"}
            and source_input == original_source_text.encode("utf-8")
        ):
            # This is the adapter's permitted prose, not an encoded envelope.
            # A literal field name mentioned by the user must not trigger decoding.
            native_bytes, byte_redactions = source_text.encode("utf-8"), text_redactions
        else:
            native_bytes, byte_redactions = redact_private_bytes(source_input)
        private_span_count = max(text_redactions, byte_redactions)
        # The adapter's searchable rendering is also evidence and must not keep
        # private content that the immutable ledger rejected.
        observation.raw_content, observation_redactions = redact_private_text(
            observation.raw_content
        )
        private_span_count = max(private_span_count, observation_redactions)
    else:
        native_bytes = source_input

    requested_source_uri = source_uri
    native_cleanup_descriptor = build_native_cleanup_descriptor(
        client=client,
        source_kind=source_kind,
        source_uri=requested_source_uri,
    )
    source_id = transcript_source_id(
        client=client,
        project_name=project_name,
        session_id=session_id,
        source_uri=source_uri,
    )
    revision = transcript_bytes_revision(native_bytes)
    tombstone_check = getattr(
        backend.transcript_store,
        "matches_hard_delete_tombstone",
        None,
    )
    if callable(tombstone_check) and tombstone_check(
        project_name=project_name,
        client=client,
        session_id=session_id,
        source_id=source_id,
        source_revision=revision,
    ):
        return TranscriptSyncResult(
            action="ignored",
            source=None,
            observation_id=None,
            distill_job_id=None,
            reason="hard_delete_tombstone",
        )
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
    native_authored = _native_codex_authored_texts(native_input) if client in {"codex", "codex-archive"} else None
    report_authorship = {}
    if native_authored is not None and native_authored[0] == original_source_text:
        _, native_users, native_assistants = native_authored
        if ((authored_user_texts is None or [text.strip() for text in authored_user_texts if text.strip()] == native_users)
                and (authored_assistant_texts is None or authored_assistant_texts == native_assistants)):
            report_authorship = {
                "authored_user_text_sha256": _authored_capture_hashes(
                    original_source_text, source_text, native_users, private_tags=config.capture_private_tags),
                "authored_assistant_text_sha256": _authored_capture_hashes(
                    original_source_text, source_text, native_assistants,
                    private_tags=config.capture_private_tags, speaker="assistant"),
                "authored_rendering_sha256": normalized_digest,
                "authored_source_report_native_sha256": sha256_bytes(native_input),
            }
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
            "native_timestamp": _native_source_timestamp(native_input, client),
            # Clear report-only proof on a new revision unless the native bytes
            # proved it again. Legacy caller-owned role fields are insufficient.
            "authored_assistant_text_sha256": None,
            "authored_source_report_native_sha256": None,
            "native_source_uri": requested_source_uri,
            "native_input_sha256": native_input_sha256,
            **(
                {"native_cleanup_descriptor": native_cleanup_descriptor}
                if native_cleanup_descriptor is not None
                else {}
            ),
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
            **({"source_context_roots": source_context_roots} if source_context_roots is not None else {}),
            **({
                "authored_user_text_sha256": _authored_capture_hashes(
                    original_source_text, source_text, authored_user_texts,
                    private_tags=config.capture_private_tags,
                ),
                "authored_rendering_sha256": normalized_digest,
            } if authored_user_texts is not None else {}),
            **report_authorship,
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
    )

    return TranscriptSyncResult(
        action=action,
        source=source,
        observation_id=observation_id,
        distill_job_id=distill_job.id,
    )


async def persist_inspected_session(
    backend: MemoryBackend, native: InspectedSource, *, project_name: str,
    project_root: str, capture_config: MergedConfig | None,
) -> TranscriptSyncResult:
    """Save a completely read selected session through the one snapshot owner.

    Host exporters still own decoding. This path never invents a workspace or
    calls a host-wide ingest, and private input bytes are hashed, not persisted.
    """
    if capture_config is None:
        raise ValueError("selected source capture policy is unavailable")
    if (native.readability != "readable" or native.captured_bytes is None
            or sha256_bytes(native.captured_bytes) != native.native_digest):
        raise ValueError("selected source has no verified complete capture")
    from harness_mem.commands.session_inventory import _dependency_stamps, _unchanged

    if not _unchanged(_dependency_stamps(native)):
        raise ValueError("selected source changed before capture")
    observation = native.adapter.session_to_observation(
        native.record["path"], native.session_id, project_name,
    )
    if not _unchanged(_dependency_stamps(native)):
        raise ValueError("selected source changed during observation projection")
    native_input = native.native_input_bytes
    if native.client == "codex" and native.native_input_digest is not None:
        # Inspection exposes only permitted dialogue. Reopen its already-read
        # native file privately at the snapshot boundary to prove speaker roles;
        # neither this input nor host-private records enter persisted capture.
        native_input = Path(native.record["path"]).read_bytes()
        if (sha256_bytes(native_input) != native.native_input_digest
                or not _unchanged(_dependency_stamps(native))):
            raise ValueError("selected native source changed before authorship proof")
    observation.metadata["source_context_roots"] = native.project_roots or []
    return await persist_session_snapshot(
        backend, observation, project_name=project_name, project_root=project_root,
        client=native.client, session_id=native.session_id,
        source_kind="native-session-export", source_uri=native.source_uri,
        source_text=native.text, raw_bytes=native.captured_bytes,
        native_input_bytes=native_input,
        native_input_digest=native.native_input_digest,
        authored_user_texts=native.authored_user_texts, capture_config=capture_config,
        source_context_roots=native.project_roots,
        parser_version="codex-conversation-v3" if native.client == "codex" else "native-inspected-source-v1",
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
