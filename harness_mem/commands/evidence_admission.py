"""Evidence-envelope validation for the Dream candidate admission pass."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence, cast
from urllib.parse import parse_qs, unquote, urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.adapters.parser import (
    _render_cursor_content_items,
    extract_archived_text,
    is_codex_user_content_item,
    parse_codex_archive_jsonl_session,
    render_codex_conversation,
    sanitize_archived_user_text,
)
from harness_mem.adapters.projection_repair import repair_source_observation_projection
from harness_mem.core.schemas import EvidenceRef, KnowledgeSource
from harness_mem.core.schemas.source_report import SourceReport
from harness_mem.mcp.distill_projection import (
    _parse_exchanges,
    render_distill_exchange_windows,
)
from harness_mem.rust_core import scan_jsonl
from harness_mem.storage.local_memory_backend import LocalMemoryBackend

_SAFE_REASON = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")

AnswerGateStatus = Literal[
    "ANSWERED",
    "PARTIAL",
    "UNANSWERED",
    "CONTRADICTED",
    "STALE",
    "NOT_APPLICABLE",
]
ANSWER_GATE_STATUSES: tuple[AnswerGateStatus, ...] = (
    "ANSWERED",
    "PARTIAL",
    "UNANSWERED",
    "CONTRADICTED",
    "STALE",
    "NOT_APPLICABLE",
)


@dataclass(frozen=True)
class EvidenceValidation:
    """Validated result projected back onto one governed candidate."""

    evidence_basis: str | None
    verification_outcome: str | None
    reason_codes: tuple[str, ...]
    verified_at: datetime | None
    source_report: SourceReport | None = None


@dataclass(frozen=True)
class KnowledgeSourceReopen:
    """A source re-opened by trusted runtime for a bounded Dream/Review pass.

    ``content`` is held only in memory for the immediate semantic call. It is
    never copied into current knowledge, a normal retrieval response, or a
    Dream receipt.
    """

    source_kind: str
    verification_outcome: str
    reason_code: str
    content: str | None
    truncated: bool = False


def uses_evidence_admission(candidate: Any) -> bool:
    """Return whether this row belongs to the v0.9.5 admission contract."""

    return bool(
        getattr(candidate, "distill_job_id", None)
        or getattr(candidate, "evidence_basis", None)
        or getattr(candidate, "verification_outcome", None)
        or getattr(candidate, "verification_refs", None)
    )


async def validate_candidate_evidence(
    backend: LocalMemoryBackend,
    candidate: Any,
    *,
    project_root: str | Path | None = None,
    non_promoting_disposition: Literal["no_write", "reject"] | None = None,
) -> EvidenceValidation:
    """Validate sources; a non-promotion may close without asserting truth.

    Only the assimilation owner supplies ``non_promoting_disposition`` after
    checking an explicit, reasoned no_write/reject with no truth targets.
    Transcript integrity can then establish NOT_APPLICABLE, never ANSWERED.
    Ordinary admission and every knowledge-writing path keep the default gate.
    """

    if non_promoting_disposition not in {None, "no_write", "reject"}:
        raise ValueError("non-promoting evidence validation requires no_write or reject")

    basis = getattr(candidate, "evidence_basis", None)
    requested = getattr(candidate, "verification_outcome", None)
    refs = list(getattr(candidate, "verification_refs", None) or [])
    existing_reasons = _safe_reason_codes(
        getattr(candidate, "verification_reason_codes", None) or []
    )
    if not uses_evidence_admission(candidate):
        return EvidenceValidation(None, None, tuple(existing_reasons), None)
    if basis is None or requested is None:
        return EvidenceValidation(
            basis or "transcript",
            "unverified",
            tuple(dict.fromkeys([*existing_reasons, "evidence_envelope_missing"])),
            None,
        )
    matching = [ref for ref in refs if ref.kind == basis]
    if not matching or len(matching) != len(refs):
        return EvidenceValidation(
            basis,
            "unverified",
            tuple(dict.fromkeys([*existing_reasons, "evidence_ref_kind_mismatch"])),
            None,
        )

    source_report: SourceReport | None = None
    if "source_use_task_context" in existing_reasons and requested == "verified":
        # Reopening authentic source bytes cannot upgrade a task's lifetime.
        requested = "not_applicable"
    if basis == "source_report":
        outcome, reasons, source_report = _validate_source_report_refs(backend, candidate, matching)
        if outcome == "verified" and requested == "not_applicable":
            # Complete native role/source proof permits a deliberate no-write;
            # it must not turn session-only material into pending durable work.
            # No report descriptor or truth-writing authority is granted.
            outcome = "not_applicable"
            reasons.append("source_report_non_promoting")
            source_report = None
        elif outcome == "verified" and requested != "verified":
            outcome = "contradicted" if requested == "contradicted" else "unverified"
            reasons.append("source_report_not_requested_verified")
            source_report = None
    elif basis == "repository":
        outcome, reasons = _validate_repository_refs(
            backend,
            candidate,
            matching,
            project_root=project_root,
        )
    elif basis == "user_statement":
        outcome, reasons = await _validate_user_statement_refs(
            backend,
            candidate,
            matching,
        )
    else:
        outcome, reasons = _validate_transcript_refs(
            backend, candidate, matching,
            require_complete_source=non_promoting_disposition is not None,
        )

    if outcome == "verified":
        if "source_use_task_context" in existing_reasons and requested == "not_applicable":
            outcome = "not_applicable"
            reasons.append("session_only_not_durable")
        elif requested == "contradicted":
            outcome = "contradicted"
        elif basis == "transcript" and non_promoting_disposition is not None:
            outcome = "not_applicable"
            reasons.append("transcript_non_promoting_decision")
        elif requested == "unverified":
            # Reference integrity cannot upgrade a semantic claim.  A caller
            # that has already found incomplete support must remain blocked
            # even when the cited bytes and hashes are authentic.
            outcome = "unverified"
        elif basis == "user_statement" and requested == "not_applicable":
            outcome = "not_applicable"
        elif basis == "transcript":
            outcome = "unverified"
            reasons.append("transcript_cannot_verify_durable_truth")
        else:
            outcome = "verified"
    verified_timestamp: datetime | None = None
    if outcome in {"verified", "not_applicable"}:
        candidate_verified_at = getattr(candidate, "verified_at", None)
        if isinstance(candidate_verified_at, datetime):
            verified_timestamp = candidate_verified_at
        else:
            verified_timestamp = datetime.now(timezone.utc)

    return EvidenceValidation(
        basis,
        outcome,
        tuple(dict.fromkeys([*existing_reasons, *reasons])),
        verified_timestamp,
        source_report if outcome == "verified" else None,
    )


async def validate_knowledge_sources(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    sources: Sequence[KnowledgeSource],
    project_root: str | Path | None,
) -> EvidenceValidation:
    """Reopen the real sources attached to one current knowledge entry.

    Stored ``verified`` timestamps are historical receipts, not proof that a
    source is still current. Review and Dream call this function before they
    confirm or replace current knowledge.
    """

    validation, _reopened = await reopen_knowledge_sources(
        backend,
        project_name=project_name,
        sources=sources,
        project_root=project_root,
    )
    return validation


async def reopen_knowledge_sources(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    sources: Sequence[KnowledgeSource],
    project_root: str | Path | None,
) -> tuple[EvidenceValidation, tuple[KnowledgeSourceReopen, ...]]:
    """Validate and boundedly reopen current sources without persisting text.

    Dream and explicit raw-evidence reading reuse this source validation.
    Unsupported network/API locators remain
    fail-closed and return no content until their dedicated revalidator exists.
    """

    root = Path(project_root).expanduser() if project_root and str(project_root).strip() else None
    if root is not None and not root.is_absolute():
        return EvidenceValidation(None, "unverified", ("knowledge_source_root_invalid",), None), ()
    root = root.resolve(strict=False) if root is not None else None
    if not sources:
        return (
            EvidenceValidation(
                None,
                "unverified",
                ("knowledge_source_missing",),
                None,
            ),
            (),
        )
    reopened: list[KnowledgeSourceReopen] = []
    for source in sources:
        if source.project_name != project_name:
            return (
                EvidenceValidation(
                    source.source_kind,
                    "unverified",
                    ("knowledge_source_project_mismatch",),
                    None,
                ),
                tuple(reopened),
            )
        outcome, reason, content, truncated = await _reopen_knowledge_source(
            backend,
            source,
            project_root=root,
        )
        reopened.append(
            KnowledgeSourceReopen(
                source_kind=source.source_kind,
                verification_outcome=outcome,
                reason_code=reason,
                content=content,
                truncated=truncated,
            )
        )
        if outcome != "verified":
            return (
                EvidenceValidation(
                    source.source_kind,
                    outcome,
                    (reason,),
                    None,
                ),
                tuple(reopened),
            )
    return (
        EvidenceValidation(
            "mixed"
            if len({item.source_kind for item in sources}) > 1
            else sources[0].source_kind,
            "verified",
            ("knowledge_sources_current",),
            datetime.now(timezone.utc),
        ),
        tuple(reopened),
    )


async def reopen_dream_knowledge_sources(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    sources: Sequence[KnowledgeSource],
    project_root: str | Path,
) -> tuple[
    EvidenceValidation,
    tuple[KnowledgeSourceReopen, ...],
    tuple[KnowledgeSource, ...],
]:
    """Reopen a current local repository source for one Dream comparison.

    A digest mismatch normally means a previously verified claim is stale and
    therefore must fail closed.  Dream is the one maintenance path whose job
    is to compare that claim with today's local repository bytes.  It may pass
    the complete bytes to the host CLI provider, but only after validating
    the path remains within the same project.  The returned effective sources
    carry today's digests and must be used for the subsequent truth
    transaction; the historical source rows remain untouched until that
    transaction succeeds.

    Immutable transcript and user-statement references never receive this
    escape hatch.  A mismatch there remains fail-closed.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if not sources:
        return (
            EvidenceValidation(None, "unverified", ("knowledge_source_missing",), None),
            (),
            (),
        )
    reopened: list[KnowledgeSourceReopen] = []
    effective_sources: list[KnowledgeSource] = []
    changed = False
    for source in sources:
        if source.project_name != project_name:
            return (
                EvidenceValidation(
                    source.source_kind,
                    "unverified",
                    ("knowledge_source_project_mismatch",),
                    None,
                ),
                tuple(reopened),
                tuple(effective_sources),
            )
        current_digest: str | None = None
        if source.source_kind == "repository":
            outcome, reason, content, truncated, current_digest = _reopen_repository_source(
                source, project_root=root, complete=True,
            )
        else:
            outcome, reason, content, truncated = await _reopen_knowledge_source(
                backend, source, project_root=root,
            )
        if (
            outcome == "contradicted"
            and reason == "knowledge_source_digest_changed"
            and source.source_kind == "repository"
            and content is not None
            and current_digest is not None
        ):
            reopened.append(
                KnowledgeSourceReopen(
                    source_kind=source.source_kind,
                    verification_outcome="verified",
                    reason_code="knowledge_source_changed",
                    content=content,
                    truncated=truncated,
                )
            )
            effective_sources.append(
                source.model_copy(update={"content_sha256": current_digest})
            )
            changed = True
            continue
        reopened.append(
            KnowledgeSourceReopen(
                source_kind=source.source_kind,
                verification_outcome=outcome,
                reason_code=reason,
                content=content,
                truncated=truncated,
            )
        )
        if outcome != "verified":
            return (
                EvidenceValidation(source.source_kind, outcome, (reason,), None),
                tuple(reopened),
                tuple(effective_sources),
            )
        effective_sources.append(source)
    return (
        EvidenceValidation(
            "mixed" if len({item.source_kind for item in sources}) > 1 else sources[0].source_kind,
            "verified",
            ("knowledge_sources_changed",)
            if changed
            else ("knowledge_sources_current",),
            datetime.now(timezone.utc),
        ),
        tuple(reopened),
        tuple(effective_sources),
    )


def apply_validation(candidate: Any, validation: EvidenceValidation) -> None:
    """Apply one validation result to an in-memory candidate schema."""

    candidate.evidence_basis = validation.evidence_basis
    candidate.verification_outcome = validation.verification_outcome
    candidate.verification_reason_codes = list(validation.reason_codes)
    candidate.verified_at = validation.verified_at
    if hasattr(candidate, "source_report"):
        candidate.source_report = validation.source_report


def sanitize_evidence_refs(candidate: Any) -> None:
    """Remove reversible repository locators from retained durable truth."""

    candidate.verification_refs = [
        ref.sanitized() for ref in getattr(candidate, "verification_refs", None) or []
    ]
    candidate.verification_reason_codes = _safe_reason_codes(
        getattr(candidate, "verification_reason_codes", None) or []
    )


def evidence_summary_key(candidate: Any) -> str:
    """Stable compact counter key for finalize/status projections."""

    outcome = getattr(candidate, "verification_outcome", None)
    basis = getattr(candidate, "evidence_basis", None)
    if outcome == "contradicted":
        return "contradicted"
    if outcome == "unverified":
        return "unverified_blocked"
    if basis == "user_statement" and outcome in {"verified", "not_applicable"}:
        return "user_stated"
    if basis == "repository" and outcome == "verified":
        return "repository_verified"
    if basis == "source_report" and outcome in {"verified", "not_applicable"}:
        return "source_report"
    return "legacy_or_unknown"


def answer_gate_status(candidate: Any) -> AnswerGateStatus:
    """Project the validated evidence envelope onto the promotion question gate.

    This status is derived by the runtime after current-source validation.  It
    is deliberately not accepted as an Agent-supplied field: an Agent may
    propose evidence, but cannot declare its own question ``ANSWERED``.
    """

    basis = getattr(candidate, "evidence_basis", None)
    outcome = getattr(candidate, "verification_outcome", None)
    reasons = set(getattr(candidate, "verification_reason_codes", None) or [])
    refs = list(getattr(candidate, "verification_refs", None) or [])

    if outcome == "contradicted":
        if reasons.intersection(
            {
                "repository_digest_changed",
                "user_statement_digest_changed",
                "transcript_digest_changed",
                "source_revision_changed",
            }
        ):
            return "STALE"
        return "CONTRADICTED"
    if basis == "repository" and outcome == "verified":
        return "ANSWERED"
    if basis == "user_statement" and outcome == "verified":
        return "ANSWERED"
    if (basis == "source_report" and outcome == "verified"
            and isinstance(getattr(candidate, "source_report", None), SourceReport)):
        return "ANSWERED"
    if outcome == "not_applicable":
        return "NOT_APPLICABLE"
    if outcome == "unverified":
        return "PARTIAL" if refs else "UNANSWERED"
    return "UNANSWERED"


def _validate_repository_refs(
    backend: LocalMemoryBackend,
    candidate: Any,
    refs: list[EvidenceRef],
    *,
    project_root: str | Path | None = None,
) -> tuple[str, list[str]]:
    job = _candidate_job(backend, candidate)
    root_value = project_root or (job.project_root if job is not None else None)
    if not root_value:
        return "unverified", ["repository_project_root_unavailable"]
    root = Path(root_value).expanduser().resolve(strict=False)
    for ref in refs:
        content_sha256 = str(ref.content_sha256 or "").lower()
        if not ref.locator or not _SHA256.fullmatch(content_sha256):
            return "unverified", ["repository_ref_incomplete"]
        expected_locator_sha256 = hashlib.sha256(
            ref.locator.encode("utf-8")
        ).hexdigest()
        if ref.locator_sha256 != expected_locator_sha256:
            return "unverified", ["repository_locator_digest_mismatch"]
        locator = Path(ref.locator)
        if locator.is_absolute():
            return "unverified", ["repository_ref_not_relative"]
        path = (root / locator).resolve(strict=False)
        if not _is_relative_to(path, root) or path == root:
            return "unverified", ["repository_ref_outside_project"]
        if not path.is_file():
            return "unverified", ["repository_ref_missing"]
        try:
            digest = _sha256_file(path)
        except OSError:
            return "unverified", ["repository_ref_unreadable"]
        if digest != content_sha256:
            return "contradicted", ["repository_digest_changed"]
    return "verified", ["repository_refs_current"]


async def _reopen_knowledge_source(
    backend: LocalMemoryBackend,
    source: KnowledgeSource,
    *,
    project_root: Path | None,
) -> tuple[str, str, str | None, bool]:
    if source.source_kind == "repository":
        outcome, reason, content, truncated, _digest = _reopen_repository_source(
            source, project_root=project_root, complete=False,
        )
        return outcome, reason, content, truncated
    parsed = urlparse(source.locator)
    digest = str(source.content_sha256 or "").lower()
    if not _SHA256.fullmatch(digest):
        return "unverified", "knowledge_source_digest_missing", None, False
    if parsed.scheme != "file":
        # Network/API revalidation requires a separately governed fetcher.
        # Until that exists, Review/Dream must fail closed.
        return "unverified", "knowledge_source_scheme_unsupported", None, False
    path = _file_uri_path(parsed)
    transcript_db = Path(backend.transcript_store.db_path).resolve(strict=False)
    if path != transcript_db:
        return "unverified", "knowledge_source_transcript_store_mismatch", None, False
    query = parse_qs(parsed.fragment, keep_blank_values=False)
    source_id = _single_query_value(query, "source_id")
    source_revision = _single_query_value(query, "source_revision")
    if not source_id or not source_revision:
        return "unverified", "knowledge_source_locator_incomplete", None, False
    revision = backend.transcript_store.get_revision(source_id, source_revision)
    if revision is None:
        return "unverified", "knowledge_source_revision_missing", None, False
    if revision.project_name != source.project_name:
        return "unverified", "knowledge_source_project_mismatch", None, False
    if source.source_kind == "source_report":
        return _reopen_source_report(backend, source, query, digest)
    if source.source_kind == "user_statement":
        exchange = _query_int(query, "exchange")
        if exchange is None:
            return "unverified", "knowledge_source_exchange_missing", None, False
        observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
        observation = await backend.verbatim_store.get(observation_id)
        if (
            observation is None
            or observation.metadata.get("source_revision") != source_revision
        ):
            # Observation is a derived search projection. Older cleanup runs
            # may have removed it while the immutable transcript revision is
            # still intact, so rebuild it in memory from that authoritative
            # revision instead of treating the knowledge source as lost.
            from harness_mem.adapters.projection_repair import (
                repair_source_observation_projection,
            )

            observation = repair_source_observation_projection(
                backend,
                source_id=source_id,
                source_revision=source_revision,
            )
            if observation is None:
                return (
                    "unverified",
                    "knowledge_source_observation_missing",
                    None,
                    False,
                )
        windows = render_distill_exchange_windows(observation.raw_content, [exchange])
        if not windows or "User:" not in str(windows[0].get("content") or ""):
            return "unverified", "knowledge_source_exchange_missing", None, False
        if str(windows[0].get("content_sha256") or "").lower() != digest:
            return "contradicted", "knowledge_source_digest_changed", None, False
        content, truncated = _bounded_source_content(
            str(windows[0].get("content") or "")
        )
        return (
            "verified",
            "knowledge_source_current",
            content,
            truncated,
        )
    if source.source_kind == "transcript":
        chunk_index = _query_int(query, "chunk")
        if chunk_index is None:
            return "unverified", "knowledge_source_chunk_missing", None, False
        chunks = {
            chunk.chunk_index: chunk
            for chunk in backend.transcript_store.list_chunks(
                source_id,
                source_revision=source_revision,
            )
        }
        chunk = chunks.get(chunk_index)
        if chunk is None:
            return "unverified", "knowledge_source_chunk_missing", None, False
        if chunk.content_sha256 != digest:
            return "contradicted", "knowledge_source_digest_changed", None, False
        content, truncated = _bounded_source_content(chunk.raw_content)
        return (
            "verified",
            "knowledge_source_current",
            content,
            truncated,
        )
    return "unverified", "knowledge_source_kind_unsupported", None, False


def _reopen_repository_source(
    source: KnowledgeSource, *, project_root: Path | None, complete: bool,
) -> tuple[str, str, str | None, bool, str | None]:
    """Bind Dream's complete UTF-8 body and effective digest to one byte snapshot.

    Other callers keep the existing bounded excerpt contract. Only Dream can
    use changed local bytes, after the same locator and project checks.
    """
    digest = str(source.content_sha256 or "").lower()
    if not _SHA256.fullmatch(digest):
        return "unverified", "knowledge_source_digest_missing", None, False, None
    parsed = urlparse(source.locator)
    if parsed.scheme != "file":
        return "unverified", "knowledge_source_scheme_unsupported", None, False, None
    path = _file_uri_path(parsed)
    if project_root is None or not project_root.is_dir():
        return "unverified", "repository_project_root_unavailable", None, False, None
    if not _is_relative_to(path, project_root) or path == project_root:
        return "unverified", "knowledge_source_outside_project", None, False, None
    if not path.is_file():
        return "unverified", "knowledge_source_missing", None, False, None
    try:
        if complete:
            raw = path.read_bytes()
            content = raw.decode("utf-8")
            if "\x00" in content:
                return "unverified", "knowledge_source_unreadable", None, False, None
            actual = hashlib.sha256(raw).hexdigest()
            truncated = False
        else:
            actual = _sha256_file(path)
            content, truncated = _read_bounded_source_content(path)
    except (OSError, UnicodeDecodeError):
        return "unverified", "knowledge_source_unreadable", None, False, None
    if actual != digest:
        return "contradicted", "knowledge_source_digest_changed", content, truncated, actual
    return "verified", "knowledge_source_current", content, truncated, actual


async def _validate_knowledge_source(
    backend: LocalMemoryBackend,
    source: KnowledgeSource,
    *,
    project_root: Path,
) -> tuple[str, str]:
    """Compatibility projection for callers that only need source integrity."""

    outcome, reason, _content, _truncated = await _reopen_knowledge_source(
        backend,
        source,
        project_root=project_root,
    )
    return outcome, reason


def _read_bounded_source_content(
    path: Path,
    *,
    limit: int = 16000,
) -> tuple[str, bool]:
    """Read one source excerpt without allocating the entire file body."""

    with path.open("r", encoding="utf-8") as handle:
        # Determine truncation from the raw bounded read, before whitespace
        # normalization.  Otherwise a `(limit + 1)`th whitespace character can
        # be stripped and make an incomplete source look complete to Dream.
        bounded = handle.read(limit + 1)
    truncated = len(bounded) > limit
    return _bounded_source_content(
        bounded[:limit],
        limit=limit,
        known_truncated=truncated,
    )


def _bounded_source_content(
    value: str,
    *,
    limit: int = 16000,
    known_truncated: bool = False,
) -> tuple[str, bool]:
    normalized = value.strip()
    if not known_truncated and len(normalized) <= limit:
        return normalized, False
    return normalized[:limit] + "\n[truncated by trusted runtime]", True


def _file_uri_path(parsed: Any) -> Path:
    path_text = unquote(parsed.path or "")
    if parsed.netloc and parsed.netloc not in {"", "localhost"}:
        path_text = f"//{parsed.netloc}{path_text}"
    if re.match(r"^/[A-Za-z]:/", path_text):
        path_text = path_text[1:]
    return Path(path_text).resolve(strict=False)


def _single_query_value(query: dict[str, list[str]], name: str) -> str | None:
    values = query.get(name) or []
    return values[0] if len(values) == 1 and values[0] else None


def _query_int(query: dict[str, list[str]], name: str) -> int | None:
    value = _single_query_value(query, name)
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _frozen_user_exchange_indexes(
    backend: LocalMemoryBackend,
    *,
    source_id: str,
    source_revision: str,
    rendering: str,
    allow_legacy_explicit: bool = False,
) -> set[int] | None:
    """Bind rendered user slots to authors in the immutable source, in memory.

    A structured source with injected role boundaries is ambiguous as a whole:
    reject it rather than align fabricated exchanges by their text or count.
    Legacy text cannot prove authors from role labels in its body.
    An explicit caller-owned role
    preserves the legacy contract for text/unsupported hosts, not an automatic
    author proof. It never bypasses supported structured-source validation.
    """
    revision = backend.transcript_store.get_revision(source_id, source_revision)
    if revision is None:
        return None
    try:
        raw = backend.transcript_store.reconstruct_raw(
            source_id, source_revision=source_revision,
        )
        text = raw.decode("utf-8-sig")
    except (KeyError, ValueError, UnicodeError):
        return None
    if hashlib.sha256(raw).hexdigest() != revision.raw_sha256:
        return None
    if revision.client == "cursor" and text.lstrip().startswith("{"):
        from harness_mem.adapters.cursor.sqlite_history import cursor_export_messages
        import json
        try:
            document = json.loads(text)
        except ValueError:
            document = None
        try:
            if isinstance(document, dict) and document.get("format") == "cursorDiskKV-v1":
                messages = cursor_export_messages(raw, revision.session_id)
                sqlite_users = [message["content"] for message in messages if message["role"] == "user"]
                for message in messages:
                    if message["role"] != "user":
                        _, quoted, _ = _parse_exchanges(f"Assistant: {message['content']}")
                        if any(exchange["user"] for exchange in quoted):
                            return set()
                _, exchanges, _ = _parse_exchanges(rendering)
                rendered = [user for exchange in exchanges for user in exchange["user"]]
                if sqlite_users != rendered:
                    return None
                return {index for index, exchange in enumerate(exchanges, 1) if exchange["user"]}
        except (ValueError, TypeError, UnicodeError):
            return None
    _header, exchanges, _summary = _parse_exchanges(rendering)
    rendered_user_indexes = {
        index for index, exchange in enumerate(exchanges, 1) if exchange["user"]
    }
    structured = text.lstrip().startswith(("{", "[")) or (
        revision.client in {"codex", "codex-archive", "cursor"}
        and "jsonl" in revision.parser_version
    )
    if not structured:
        # Codex deliberately captures permitted conversation, not host prompts
        # or tool logs. Its adapter binds native user texts to this immutable
        # rendering at capture time. Never infer authors from role labels alone.
        if revision.client in {"codex", "codex-archive"} and revision.parser_version in {
            "codex-conversation-v2", "codex-conversation-v3", "codex-archive-conversation-v2",
        }:
            captured = revision.metadata.get("authored_user_text_sha256")
            if captured is not None:
                rendered_users = [user for exchange in exchanges for user in exchange["user"]]
                if (
                    not isinstance(captured, list)
                    or any(not isinstance(digest, str) or not _SHA256.fullmatch(digest)
                           for digest in captured)
                    or revision.metadata.get("authored_rendering_sha256")
                    != hashlib.sha256(rendering.encode("utf-8")).hexdigest()
                    or captured != [hashlib.sha256(user.encode("utf-8")).hexdigest()
                                    for user in rendered_users]
                ):
                    return None
                return rendered_user_indexes
        if allow_legacy_explicit:
            return rendered_user_indexes
        return None

    if revision.client not in {"codex", "codex-archive", "cursor"}:
        return rendered_user_indexes if allow_legacy_explicit else None
    scanned = scan_jsonl(text)
    if scanned.errors or not scanned.records:
        return None
    users: list[str] = []
    for record in scanned.records:
        payload = record.get("payload", record)
        if not isinstance(payload, dict):
            return None
        message = payload.get("message", payload)
        role_values = [record.get("role"), payload.get("role")]
        if isinstance(message, dict):
            role_values.append(message.get("role"))
        if any(value is not None and not isinstance(value, str) for value in role_values):
            return None
        roles = {value for value in role_values if isinstance(value, str)}
        record_type = record.get("type")
        payload_type = payload.get("type")
        if record_type is not None and not isinstance(record_type, str):
            return None
        if payload_type is not None and not isinstance(payload_type, str):
            return None
        if revision.client != "cursor":
            event_role = None
            if record_type == "event_msg" and isinstance(payload_type, str):
                event_role = {
                    "user_message": "user", "agent_message": "assistant",
                }.get(payload_type)
            if event_role:
                roles.add(event_role)
            elif record_type in {"user", "assistant", "tool"}:
                roles.add(record_type)
        if len(roles) > 1:
            return None
        if roles == {"user"}:
            if revision.client == "cursor" and record.get("role") != "user":
                return None
            if revision.client != "cursor" and "payload" not in record and (
                record_type != "user" and "content" not in record
            ):
                return None
            if "payload" in record and not (
                revision.client != "cursor" and (
                    record_type == "response_item" and payload_type == "message"
                    or record_type == "event_msg" and payload_type == "user_message"
                )
            ):
                return None
            content = message.get("content") if isinstance(message, dict) else message
            if revision.client != "cursor" and isinstance(content, list) and any(
                not is_codex_user_content_item(item)
                for item in content
            ):
                return None
            user = (
                _render_cursor_content_items(content)
                if revision.client == "cursor"
                else sanitize_archived_user_text(extract_archived_text(content))
            )
            if user:
                users.append(user)
            continue
        # Inspect all non-user string leaves, including tool outputs/arguments.
        # Use the exchange owner's parser so heading removal and passive tools
        # cannot conceal a User boundary from this author check.
        pending: list[Any] = [record]
        while pending:
            value = pending.pop()
            if isinstance(value, dict):
                pending.extend(value.values())
            elif isinstance(value, list):
                pending.extend(value)
            elif isinstance(value, str):
                _header, quoted, _summary = _parse_exchanges(f"Assistant: {value}")
                if any(exchange["user"] for exchange in quoted):
                    return set()
    if revision.client != "cursor" and any(
        record.get("type") in {"event_msg", "response_item"}
        for record in scanned.records
    ):
        _metadata, turns = parse_codex_archive_jsonl_session(
            Path("frozen.jsonl"), content=text,
        )
        # Reference windows fold duplicate native events. Author comparison must
        # use that same normalization, after checking every native record above.
        _, native_exchanges, _ = _parse_exchanges(render_codex_conversation(turns))
        users = [user for exchange in native_exchanges for user in exchange["user"]]
    rendered_users = [user for exchange in exchanges for user in exchange["user"]]
    if users != rendered_users:
        return None
    return rendered_user_indexes


def _source_report_context(backend: LocalMemoryBackend, *, project_name: str,
                           source_id: str, source_revision: str) -> tuple[Any, str, bytes]:
    """Reconstruct all immutable bytes and chunks before using any report ref."""
    ledger = backend.transcript_store
    source = ledger.get_source(source_id)
    revision = ledger.get_revision(source_id, source_revision)
    if source is None or revision is None:
        raise ValueError("source_report_source_missing")
    if (source.id != source_id or revision.source_id != source_id
            or revision.source_revision != source_revision
            or source.project_name != project_name or revision.project_name != project_name
            or source.session_id != revision.session_id or source.client != revision.client
            or source.project_root != revision.project_root
            or revision.coverage != "complete"):
        raise ValueError("source_report_source_scope_mismatch")
    # A bounded historical report belongs to its retained immutable revision.
    # Appending to the same session changes today's pointer/digests, not what
    # its earlier speaker said. Only the current revision shares those fields.
    if source.source_revision == source_revision and (
            source.raw_sha256 != revision.raw_sha256
            or source.normalized_sha256 != revision.normalized_sha256
            or source.chunk_count != revision.chunk_count
            or source.coverage != "complete" or source.status != "synced"):
        raise ValueError("source_report_source_scope_mismatch")
    raw = ledger.reconstruct_raw(source_id, source_revision=source_revision)
    rendering = ledger.reconstruct(source_id, source_revision=source_revision)
    if (hashlib.sha256(raw).hexdigest() != revision.raw_sha256
            or len(raw) != revision.raw_size_bytes
            or not source_revision.startswith(f"sha256:{revision.raw_sha256}")
            or hashlib.sha256(rendering.encode("utf-8")).hexdigest() != revision.normalized_sha256
            or len(rendering.encode("utf-8")) != revision.normalized_size_bytes):
        raise ValueError("source_report_source_digest_changed")
    chunks = ledger.list_chunks(source_id, source_revision=source_revision)
    if len(chunks) != revision.chunk_count or any(
        chunk.source_id != source_id or chunk.source_revision != source_revision
        or chunk.project_name != project_name or chunk.client != revision.client
        or chunk.session_id != revision.session_id
        for chunk in chunks
    ):
        raise ValueError("source_report_source_incomplete")
    if revision.client == "claude-code":
        from harness_mem.adapters.snapshot import _native_claude_rendering

        # The immutable Claude ledger holds JSONL; refs cite its canonical
        # conversation rendering. Derive that view only after full byte checks.
        if revision.parser_version != "claude-code-jsonl-v1":
            raise ValueError("source_report_speaker_unproved")
        native_rendering = _native_claude_rendering(raw, revision.session_id)
        if native_rendering is None:
            raise ValueError("source_report_speaker_unproved")
        rendering = native_rendering
    return revision, rendering, raw


def _source_report_author_indexes(revision: Any, rendering: str, raw: bytes,
                                  speaker: str) -> set[int] | None:
    """Prove the cited role, with no legacy text/explicit-role escape hatch."""
    from harness_mem.adapters.snapshot import _native_claude_rendering, _native_codex_authored_texts
    from harness_mem.mcp.distill_projection import _ENTRY_RE

    if revision.client not in {"codex", "codex-archive", "cursor", "claude-code"}:
        return None
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeError:
        return None
    exchanges = _parse_exchanges(rendering)[1]
    if revision.client == "claude-code":
        if revision.parser_version != "claude-code-jsonl-v1":
            return None
        native_rendering = _native_claude_rendering(raw, revision.session_id)
        if native_rendering is None:
            return None
    elif revision.client in {"codex", "codex-archive"}:
        native = _native_codex_authored_texts(raw)
        if native is not None:
            native_rendering = native[0]
        elif text.lstrip().startswith(("{", "[")):
            return None
        else:
            # New capture proof is emitted only after snapshot independently
            # parses native input. Old caller-owned authored-user flags alone
            # cannot certify either report speaker from a plain-text source.
            metadata = revision.metadata
            receipt = metadata.get("authored_source_report_native_sha256")
            if (revision.parser_version not in {
                    "codex-conversation-v2", "codex-conversation-v3", "codex-archive-conversation-v2"}
                    or not isinstance(receipt, str) or not _SHA256.fullmatch(receipt)
                    or receipt != metadata.get("native_input_sha256")
                    or metadata.get("authored_rendering_sha256")
                    != hashlib.sha256(rendering.encode("utf-8")).hexdigest()
                    or text != rendering):
                return None
            for role in ("user", "assistant"):
                captured = metadata.get(f"authored_{role}_text_sha256")
                expected = [hashlib.sha256(value.encode("utf-8")).hexdigest()
                            for exchange in exchanges for value in exchange[role]]
                if not isinstance(captured, list) or captured != expected:
                    return None
            return {index for index, exchange in enumerate(exchanges, 1) if exchange[speaker]}
    else:
        import json
        try:
            document = json.loads(text)
        except ValueError:
            document = None
        if isinstance(document, dict) and document.get("format") == "cursorDiskKV-v1":
            from harness_mem.adapters.cursor.sqlite_history import cursor_export_messages
            try:
                messages = cursor_export_messages(raw, revision.session_id)
            except (ValueError, TypeError, UnicodeError):
                return None
            rows = [(message["role"], message["content"]) for message in messages]
        else:
            scanned = scan_jsonl(text)
            if scanned.errors or not scanned.records:
                return None
            rows = []
            for record in scanned.records:
                if record.get("type") == "session_meta":
                    continue
                cursor_role = record.get("role")
                message = record.get("message", record)
                if cursor_role not in {"user", "assistant", "tool"} or not isinstance(message, dict):
                    return None
                if message.get("role", cursor_role) != cursor_role:
                    return None
                rows.append((cursor_role, _render_cursor_content_items(message.get("content"))))
        blocks = []
        for role, body in rows:
            if not isinstance(body, str):
                return None
            block = f"{role.title()}: {body}"
            if len(list(_ENTRY_RE.finditer(block))) != 1:
                return None
            if role in {"user", "assistant"} and body.strip():
                blocks.append(block)
        native_rendering = "\n\n".join(blocks)
    native_exchanges = _parse_exchanges(native_rendering)[1]
    if [(exchange["user"], exchange["assistant"]) for exchange in native_exchanges] != [
            (exchange["user"], exchange["assistant"]) for exchange in exchanges]:
        return None
    return {index for index, exchange in enumerate(exchanges, 1) if exchange[speaker]}


def _source_report_period(revision: Any, raw: bytes) -> str:
    from harness_mem.adapters.snapshot import _native_source_timestamp

    value = revision.metadata.get("native_timestamp")
    if isinstance(value, str) and value.strip():
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            # Historical captures may have stored Observation.timestamp (often
            # mtime/now) here. Structured sources must independently agree.
            if raw.lstrip().startswith(b"{"):
                return value if _native_source_timestamp(raw, revision.client) == value else "that session (date unknown)"
            if revision.metadata.get("authored_source_report_native_sha256"):
                return value
    return "that session (date unknown)"


def _validate_source_report_refs(backend: LocalMemoryBackend, candidate: Any,
                                 refs: list[EvidenceRef]) -> tuple[str, list[str], SourceReport | None]:
    job = _candidate_job(backend, candidate)
    if job is None:
        return "unverified", ["source_report_job_missing"], None
    try:
        revision, rendering, raw = _source_report_context(
            backend, project_name=candidate.project_name, source_id=job.source_id,
            source_revision=job.source_revision)
        if (job.session_id != revision.session_id or job.client != revision.client
                or job.project_root != revision.project_root):
            raise ValueError("source_report_job_scope_mismatch")
        roles = {ref.role for ref in refs}
        if len(roles) != 1 or not roles.issubset({"user", "assistant"}):
            raise ValueError("source_report_speaker_unproved")
        speaker = cast(Literal["user", "assistant"], next(iter(roles)))
        indexes = [ref.exchange_index for ref in refs if ref.exchange_index is not None]
        if (len(indexes) != len(refs) or len(indexes) != len(set(indexes))
                or any(ref.chunk_index is not None or ref.locator is not None
                       or ref.locator_sha256 is not None for ref in refs)):
            raise ValueError("source_report_ref_incomplete")
        proved = _source_report_author_indexes(revision, rendering, raw, str(speaker))
        if proved is None or any(index not in proved for index in indexes):
            raise ValueError("source_report_speaker_unproved")
        for ref in refs:
            assert ref.exchange_index is not None
            windows = render_distill_exchange_windows(rendering, [ref.exchange_index])
            if not windows or str(ref.content_sha256 or "").lower() != windows[0]["content_sha256"]:
                raise ValueError("source_report_exchange_digest_changed")
        statement = getattr(candidate, "statement", None)
        if not isinstance(statement, str) or not statement.strip():
            raise ValueError("source_report_statement_missing")
        report = SourceReport(speaker=speaker, period=_source_report_period(revision, raw),
            session_id=job.session_id, source_id=job.source_id, source_revision=job.source_revision,
            exchange_indexes=indexes, text=statement)
        previous = getattr(candidate, "source_report", None)
        if previous is not None and SourceReport.model_validate(previous) != report:
            raise ValueError("source_report_descriptor_mismatch")
    except (KeyError, ValueError, OSError) as exc:
        reason = str(exc)
        if not _SAFE_REASON.fullmatch(reason):
            reason = "source_report_source_incomplete"
        return "unverified", [reason], None
    return "verified", ["source_report_native_refs_current"], report


def source_report_speaker_excerpt(
    backend: LocalMemoryBackend, *, project_name: str, job_id: str, ref: Any,
) -> str | None:
    """Reopen the actual speaker's prose for semantic support, not whole-turn assent.

    This only proves whose source text is supplied. The existing semantic
    verification owner must still judge whether it entails the paraphrase.
    """
    job = backend.transcript_store.get_distill_job(job_id)
    if (job is None or job.project_name != project_name or ref.kind != "source_report"
            or ref.role not in {"user", "assistant"} or ref.exchange_index is None):
        return None
    try:
        revision, rendering, raw = _source_report_context(
            backend, project_name=project_name, source_id=job.source_id,
            source_revision=job.source_revision,
        )
        if (job.session_id != revision.session_id or job.client != revision.client
                or job.project_root != revision.project_root):
            return None
        proved = _source_report_author_indexes(revision, rendering, raw, ref.role)
        if proved is None or ref.exchange_index not in proved:
            return None
        windows = render_distill_exchange_windows(rendering, [ref.exchange_index])
        if not windows or str(ref.content_sha256 or "").lower() != windows[0]["content_sha256"]:
            return None
        return "\n\n".join(_parse_exchanges(rendering)[1][ref.exchange_index - 1][ref.role])
    except (KeyError, ValueError, OSError):
        return None


def _reopen_source_report(backend: LocalMemoryBackend, source: KnowledgeSource,
                           query: dict[str, list[str]], digest: str) -> tuple[str, str, str | None, bool]:
    if set(query) != {"source_id", "source_revision", "exchange", "role"}:
        return "unverified", "source_report_locator_incomplete", None, False
    speaker = _single_query_value(query, "role")
    exchange = _query_int(query, "exchange")
    source_id = _single_query_value(query, "source_id")
    source_revision = _single_query_value(query, "source_revision")
    if speaker is None or speaker not in {"user", "assistant"} or exchange is None or not source_id or not source_revision:
        return "unverified", "source_report_speaker_unproved", None, False
    try:
        revision, rendering, raw = _source_report_context(
            backend, project_name=source.project_name, source_id=source_id, source_revision=source_revision)
        proved = _source_report_author_indexes(revision, rendering, raw, speaker)
        if proved is None or exchange not in proved:
            return "unverified", "source_report_speaker_unproved", None, False
        windows = render_distill_exchange_windows(rendering, [exchange])
        if not windows or windows[0]["content_sha256"] != digest:
            return "contradicted", "knowledge_source_digest_changed", None, False
        spoken = _parse_exchanges(rendering)[1][exchange - 1][speaker]
        report = SourceReport(speaker=cast(Literal["user", "assistant"], speaker), period=_source_report_period(revision, raw),
            session_id=revision.session_id, source_id=revision.source_id,
            source_revision=revision.source_revision, exchange_indexes=[exchange],
            text=" ".join(" ".join(spoken).split()))
    except (KeyError, ValueError, OSError):
        return "unverified", "source_report_source_incomplete", None, False
    content, truncated = _bounded_source_content(report.render_statement())
    return "verified", "source_report_native_refs_current", content, truncated


async def _validate_user_statement_refs(
    backend: LocalMemoryBackend,
    candidate: Any,
    refs: list[EvidenceRef],
) -> tuple[str, list[str]]:
    job = _candidate_job(backend, candidate)
    if job is None:
        return "unverified", ["user_statement_job_missing"]
    observation_id = str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))
    observation = await backend.verbatim_store.get(observation_id)
    if observation is None or observation.metadata.get("source_revision") != job.source_revision:
        return "unverified", ["user_statement_source_unavailable"]
    revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    if revision is not None and revision.client in {"codex", "codex-archive"} and "jsonl" in revision.parser_version:
        # Native legacy observations can predate the current parser. Rebuild
        # only the derived view; the immutable source and old receipts stay put.
        repaired = repair_source_observation_projection(
            backend,
            source_id=job.source_id, source_revision=job.source_revision,
        )
        if repaired is not None and repaired.raw_content and _frozen_user_exchange_indexes(
            backend, source_id=job.source_id, source_revision=job.source_revision,
            rendering=repaired.raw_content, allow_legacy_explicit=False,
        ):
            observation = repaired
    if (
        observation is None
        or observation.metadata.get("source_revision") != job.source_revision
    ):
        return "unverified", ["user_statement_source_unavailable"]
    author_indexes: dict[bool, set[int] | None] = {}
    for ref in refs:
        if (
            ref.exchange_index is None
            or not _SHA256.fullmatch(str(ref.content_sha256 or "").lower())
            or ref.role not in {None, "user"}
        ):
            return "unverified", ["user_statement_ref_incomplete"]
        windows = render_distill_exchange_windows(
            observation.raw_content,
            [ref.exchange_index],
        )
        if not windows:
            return "unverified", ["user_statement_exchange_missing"]
        window = windows[0]
        legacy_explicit = ref.role == "user"
        if legacy_explicit not in author_indexes:
            author_indexes[legacy_explicit] = _frozen_user_exchange_indexes(
                backend, source_id=job.source_id, source_revision=job.source_revision,
                rendering=observation.raw_content,
                allow_legacy_explicit=legacy_explicit,
            )
        user_indexes = author_indexes[legacy_explicit]
        if user_indexes is None:
            return "unverified", ["user_statement_author_unavailable"]
        if ref.exchange_index not in user_indexes:
            return "unverified", ["user_statement_role_mismatch"]
        if str(window.get("content_sha256") or "") != str(
            ref.content_sha256
        ).lower():
            return "contradicted", ["user_statement_digest_changed"]
    return "verified", ["user_statement_refs_current"]


def _validate_transcript_refs(
    backend: LocalMemoryBackend,
    candidate: Any,
    refs: list[EvidenceRef],
    *,
    require_complete_source: bool = False,
) -> tuple[str, list[str]]:
    job = _candidate_job(backend, candidate)
    if job is None:
        return "unverified", ["transcript_job_missing"]
    chunks = {
        chunk.chunk_index: chunk
        for chunk in backend.transcript_store.list_chunks(
            job.source_id,
            source_revision=job.source_revision,
        )
    }
    rendering: str | None = None
    for ref in refs:
        if (
            (ref.chunk_index is None) == (ref.exchange_index is None)
            or not _SHA256.fullmatch(str(ref.content_sha256 or "").lower())
        ):
            return "unverified", ["transcript_ref_incomplete"]
        if ref.chunk_index is not None:
            chunk = chunks.get(ref.chunk_index)
            if chunk is None:
                return "unverified", ["transcript_chunk_missing"]
            actual_digest = chunk.content_sha256
        else:
            if ref.exchange_index is None:
                return "unverified", ["transcript_ref_incomplete"]
            if rendering is None:
                try:
                    rendering = backend.transcript_store.reconstruct(
                        job.source_id, source_revision=job.source_revision,
                    )
                except (KeyError, ValueError):
                    return "unverified", ["transcript_source_incomplete"]
                projection = repair_source_observation_projection(
                    backend, source_id=job.source_id, source_revision=job.source_revision,
                )
                if projection is not None:
                    rendering = projection.raw_content
            windows = render_distill_exchange_windows(rendering, [ref.exchange_index])
            if not windows:
                return "unverified", ["transcript_exchange_missing"]
            actual_digest = str(windows[0].get("content_sha256") or "")
        if actual_digest != str(ref.content_sha256).lower():
            return "contradicted", ["transcript_digest_changed"]
    if require_complete_source:
        # A valid cited chunk alone must not close work whose immutable source
        # or another chunk disappeared. Reuse the ledger's full hash checks.
        try:
            backend.transcript_store.reconstruct(
                job.source_id, source_revision=job.source_revision,
            )
            backend.transcript_store.reconstruct_raw(
                job.source_id, source_revision=job.source_revision,
            )
        except (KeyError, ValueError):
            return "unverified", ["transcript_source_incomplete"]
    return "verified", ["transcript_refs_current"]


def _candidate_job(backend: LocalMemoryBackend, candidate: Any) -> Any | None:
    job_id = str(getattr(candidate, "distill_job_id", None) or "")
    if not job_id:
        return None
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None or job.project_name != getattr(candidate, "project_name", None):
        return None
    return job


def _safe_reason_codes(values: list[Any]) -> list[str]:
    return [
        value
        for value in dict.fromkeys(str(item) for item in values)
        if _SAFE_REASON.fullmatch(value)
    ]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = [
    "ANSWER_GATE_STATUSES",
    "AnswerGateStatus",
    "EvidenceValidation",
    "KnowledgeSourceReopen",
    "answer_gate_status",
    "apply_validation",
    "evidence_summary_key",
    "sanitize_evidence_refs",
    "source_report_speaker_excerpt",
    "reopen_knowledge_sources",
    "reopen_dream_knowledge_sources",
    "uses_evidence_admission",
    "validate_candidate_evidence",
    "validate_knowledge_sources",
]
