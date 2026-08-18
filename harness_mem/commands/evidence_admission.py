"""Evidence-envelope validation for the Dream candidate admission pass."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Sequence
from urllib.parse import parse_qs, unquote, urlparse
from uuid import NAMESPACE_URL, uuid5

from harness_mem.core.schemas import EvidenceRef, KnowledgeSource
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
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
) -> EvidenceValidation:
    """Validate current project/source integrity without judging prose semantics."""

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

    if basis == "repository":
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
        outcome, reasons = _validate_transcript_refs(backend, candidate, matching)

    if outcome == "verified":
        if requested == "contradicted":
            outcome = "contradicted"
        elif basis == "user_statement" and requested == "not_applicable":
            outcome = "not_applicable"
        elif basis == "transcript":
            outcome = "unverified"
            reasons.append("transcript_cannot_verify_durable_truth")
        else:
            outcome = "verified"
    return EvidenceValidation(
        basis,
        outcome,
        tuple(dict.fromkeys([*existing_reasons, *reasons])),
        datetime.now(timezone.utc) if outcome in {"verified", "not_applicable"} else None,
    )


async def validate_knowledge_sources(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    sources: Sequence[KnowledgeSource],
    project_root: str | Path,
) -> EvidenceValidation:
    """Reopen the real sources attached to one current knowledge entry.

    Stored ``verified`` timestamps are historical receipts, not proof that a
    source is still current. Review and Dream call this function before they
    confirm or replace current knowledge.
    """

    root = Path(project_root).expanduser().resolve(strict=False)
    if not sources:
        return EvidenceValidation(
            None,
            "unverified",
            ("knowledge_source_missing",),
            None,
        )
    for source in sources:
        if source.project_name != project_name:
            return EvidenceValidation(
                source.source_kind,
                "unverified",
                ("knowledge_source_project_mismatch",),
                None,
            )
        outcome, reason = await _validate_knowledge_source(
            backend,
            source,
            project_root=root,
        )
        if outcome != "verified":
            return EvidenceValidation(
                source.source_kind,
                outcome,
                (reason,),
                None,
            )
    return EvidenceValidation(
        "mixed" if len({item.source_kind for item in sources}) > 1 else sources[0].source_kind,
        "verified",
        ("knowledge_sources_current",),
        datetime.now(timezone.utc),
    )


def apply_validation(candidate: Any, validation: EvidenceValidation) -> None:
    """Apply one validation result to an in-memory candidate schema."""

    candidate.evidence_basis = validation.evidence_basis
    candidate.verification_outcome = validation.verification_outcome
    candidate.verification_reason_codes = list(validation.reason_codes)
    candidate.verified_at = validation.verified_at


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


async def _validate_knowledge_source(
    backend: LocalMemoryBackend,
    source: KnowledgeSource,
    *,
    project_root: Path,
) -> tuple[str, str]:
    parsed = urlparse(source.locator)
    digest = str(source.content_sha256 or "").lower()
    if not _SHA256.fullmatch(digest):
        return "unverified", "knowledge_source_digest_missing"
    if parsed.scheme != "file":
        # Network/API revalidation requires a separately governed fetcher.
        # Until that exists, Review/Dream must fail closed.
        return "unverified", "knowledge_source_scheme_unsupported"
    path = _file_uri_path(parsed)
    if source.source_kind == "repository":
        if not _is_relative_to(path, project_root) or path == project_root:
            return "unverified", "knowledge_source_outside_project"
        if not path.is_file():
            return "unverified", "knowledge_source_missing"
        try:
            actual = _sha256_file(path)
        except OSError:
            return "unverified", "knowledge_source_unreadable"
        if actual != digest:
            return "contradicted", "knowledge_source_digest_changed"
        return "verified", "knowledge_source_current"

    transcript_db = Path(backend.transcript_store.db_path).resolve(strict=False)
    if path != transcript_db:
        return "unverified", "knowledge_source_transcript_store_mismatch"
    query = parse_qs(parsed.fragment, keep_blank_values=False)
    source_id = _single_query_value(query, "source_id")
    source_revision = _single_query_value(query, "source_revision")
    if not source_id or not source_revision:
        return "unverified", "knowledge_source_locator_incomplete"
    revision = backend.transcript_store.get_revision(source_id, source_revision)
    if revision is None:
        return "unverified", "knowledge_source_revision_missing"
    if source.source_kind == "user_statement":
        exchange = _query_int(query, "exchange")
        if exchange is None:
            return "unverified", "knowledge_source_exchange_missing"
        observation_id = str(uuid5(NAMESPACE_URL, f"{source_id}:observation"))
        observation = await backend.verbatim_store.get(observation_id)
        if (
            observation is None
            or observation.metadata.get("source_revision") != source_revision
        ):
            return "unverified", "knowledge_source_observation_missing"
        windows = render_distill_exchange_windows(observation.raw_content, [exchange])
        if not windows or "User:" not in str(windows[0].get("content") or ""):
            return "unverified", "knowledge_source_exchange_missing"
        if str(windows[0].get("content_sha256") or "").lower() != digest:
            return "contradicted", "knowledge_source_digest_changed"
        return "verified", "knowledge_source_current"
    if source.source_kind == "transcript":
        chunk_index = _query_int(query, "chunk")
        if chunk_index is None:
            return "unverified", "knowledge_source_chunk_missing"
        chunks = {
            chunk.chunk_index: chunk
            for chunk in backend.transcript_store.list_chunks(
                source_id,
                source_revision=source_revision,
            )
        }
        chunk = chunks.get(chunk_index)
        if chunk is None:
            return "unverified", "knowledge_source_chunk_missing"
        if chunk.content_sha256 != digest:
            return "contradicted", "knowledge_source_digest_changed"
        return "verified", "knowledge_source_current"
    return "unverified", "knowledge_source_kind_unsupported"


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
    if (
        observation is None
        or observation.metadata.get("source_revision") != job.source_revision
    ):
        return "unverified", ["user_statement_source_unavailable"]
    for ref in refs:
        if (
            ref.exchange_index is None
            or not _SHA256.fullmatch(str(ref.content_sha256 or "").lower())
            or ref.role != "user"
        ):
            return "unverified", ["user_statement_ref_incomplete"]
        windows = render_distill_exchange_windows(
            observation.raw_content,
            [ref.exchange_index],
        )
        if not windows:
            return "unverified", ["user_statement_exchange_missing"]
        window = windows[0]
        if "User:" not in str(window.get("content") or ""):
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
    for ref in refs:
        if ref.chunk_index is None or not _SHA256.fullmatch(
            str(ref.content_sha256 or "").lower()
        ):
            return "unverified", ["transcript_ref_incomplete"]
        chunk = chunks.get(ref.chunk_index)
        if chunk is None:
            return "unverified", ["transcript_chunk_missing"]
        if chunk.content_sha256 != str(ref.content_sha256).lower():
            return "contradicted", ["transcript_digest_changed"]
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
    "answer_gate_status",
    "apply_validation",
    "evidence_summary_key",
    "sanitize_evidence_refs",
    "uses_evidence_admission",
    "validate_candidate_evidence",
    "validate_knowledge_sources",
]
