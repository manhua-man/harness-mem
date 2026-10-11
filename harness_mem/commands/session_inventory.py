"""Project-scoped read-only session inventory and complete source pagination."""

from __future__ import annotations

from collections import Counter
from contextlib import closing
from dataclasses import dataclass, field
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from harness_mem.adapters.source_inspection import (
    HOSTS, InspectedSource, build_inspection_adapter, inspect_native_source,
    list_native_records, normalized_root,
)
from harness_mem.capture_policy import decide_capture, redact_private_text
from harness_mem.config.merge import load_merged_config
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.storage.canonical_store import CanonicalStoreRuntime, canonical_store_path
from harness_mem.storage.transcript_store import TranscriptStore
from harness_mem.transcript_chunking import sha256_text, transcript_source_id


def session_reference(client: str, session_id: str, source_id: str, source_revision: str) -> dict[str, str]:
    identity = [client, session_id, source_id, source_revision]
    return dict(zip(("client", "session_id", "source_id", "source_revision"), identity),
                reference_id=sha256(json.dumps(identity).encode()).hexdigest())


def current_entries(data_dir: Path, project_name: str) -> dict[str, dict]:
    if not canonical_store_path(data_dir).is_file():
        return {}
    with closing(CanonicalStoreRuntime(data_dir, read_only=True)) as store:
        return {item["id"]: item for item in store.list_payloads("knowledge_entries", project_name=project_name)}


def completion_proven(job: SessionDistillJob, entries: dict[str, dict], *, superseded: set[str] | None = None) -> bool:
    """Conservative current proof, not a packet-exists or status-only shortcut."""
    if job.status != "completed" or job.completion_disposition is None:
        return False
    audit = job.structural_audit
    if (audit.get("coverage") != "complete" or audit.get("expected_chunks") != job.expected_chunk_count
            or audit.get("completed_chunks") != job.expected_chunk_count
            or job.completed_chunk_count != job.expected_chunk_count):
        return False
    summary = job.promotion_summary
    if summary.get("pending", 0) or summary.get("missing", 0):
        return False
    points = summary.get("points") or []
    if {p.get("candidate_id") for p in points} != set(job.output_candidate_ids):
        return False
    writes = [p for p in points if p.get("disposition") in {"add", "refine", "replace"}]
    if len(writes) != int(summary.get("promoted") or 0):
        return False
    for point in writes:
        ids = point.get("canonical_truth_ids") or []
        if not ids or any(value not in entries and value not in (superseded or set()) for value in ids):
            return False
        if any(value in entries for value in point.get("replaced_truth_ids") or []):
            return False
    # Legacy completion without readback remains needs_verification.
    receipt = summary.get("readback")
    if not isinstance(receipt, dict) or receipt.get("source_revision") != job.source_revision or receipt.get("verified") is not True:
        return False
    if points:
        return True
    challenge = job.semantic_review.get("zero_candidate_challenge") or {}
    terminal_challenge = (challenge.get("conclusion") == "no_durable_candidate"
                          and challenge.get("future_utility") in {"none", "session_only"})
    preserved_handoff = (challenge.get("conclusion") == "candidate_required"
                         and bool(receipt.get("handoff_ids"))
                         and bool(job.semantic_review.get("unfinished_work")))
    return bool(job.zero_candidate_challenge_version == "v1"
                and challenge.get("source_revision") == job.source_revision
                and challenge.get("evidence_fidelity") == "complete"
                and (terminal_challenge or preserved_handoff))


def completed_job_ids(jobs: list[SessionDistillJob], entries: dict[str, dict]) -> tuple[set[str], set[str]]:
    """Resolve only proven replacement chains ending in current knowledge.

    This is a projection of existing temporary job receipts, not stored history.
    A missing final entry or a cycle cannot certify any predecessor.
    """
    completed: set[str] = set()
    superseded: set[str] = set()
    while True:
        newly_proven = [job for job in jobs if job.id not in completed
                        and completion_proven(job, entries, superseded=superseded)]
        if not newly_proven:
            return completed, superseded
        for job in newly_proven:
            completed.add(job.id)
            for point in job.promotion_summary.get("points") or []:
                if point.get("disposition") in {"refine", "replace"}:
                    superseded.update(point.get("replaced_truth_ids") or [])


@dataclass
class SessionInventory:
    project_name: str
    project_root: str
    rows: list[dict] = field(default_factory=list)
    native: dict[str, InspectedSource] = field(default_factory=dict)
    issues: list[dict] = field(default_factory=list)

    def payload(self) -> dict:
        return {
            "success": True,
            "project_name": self.project_name,
            "project_root": self.project_root,
            "counts": {
                "sessions": len(self.rows),
                "ownership": dict(Counter(row["ownership"] for row in self.rows)),
                "readability": dict(Counter(row["readability"] for row in self.rows)),
                "processing": dict(Counter(row["processing"] for row in self.rows if row["ownership"] == "project")),
            },
            "sessions": self.rows,
            **({"issues": self.issues} if self.issues else {}),
        }


def collect_session_inventory(
    data_dir: Path, *, project_root: Path, project_name: str,
    clients: list[str] | None = None,
    adapter_factory: Callable[..., Any] | None = None,
) -> SessionInventory:
    if not project_root.is_absolute() or not project_root.is_dir():
        raise ValueError("project_root must be an existing absolute directory")
    selected = list(dict.fromkeys(HOSTS if clients is None else clients))
    if not selected or set(selected) - set(HOSTS):
        raise ValueError("clients must select supported hosts")
    config = load_merged_config(str(project_root))
    adapter_factory = adapter_factory or build_inspection_adapter
    result = SessionInventory(project_name, normalized_root(project_root))
    sources = []
    jobs: list[SessionDistillJob] = []
    if (data_dir / "transcript_ledger.sqlite").is_file():
        with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
            sources = [source for source in ledger.list_sources(project_name=project_name, limit=None)
                       if source.client in selected and normalized_root(source.project_root) == normalized_root(project_root)]
            jobs = [job for job in ledger.list_distill_jobs(project_name=project_name)
                    if normalized_root(job.project_root) == normalized_root(project_root)]
    entries = current_entries(data_dir, project_name)
    proven, _ = completed_job_ids(jobs, entries)
    seen_sources: set[str] = set()
    by_identity: dict[tuple[str, str, str], dict] = {}
    for client in selected:
        issues: list[dict[str, str]] = []
        try:
            adapter = adapter_factory(client)
            records = list_native_records(adapter, client, issues)
        except (OSError, ValueError, sqlite3.Error):
            result.issues.append({"client": client, "reason": "source_scan_failed"})
            continue
        for issue in issues:
            result.issues.append({"client": client, "reason": issue.get("code", "source_scan_failed")})
        for record in records:
            try:
                native = inspect_native_source(adapter, client, record, project_root=project_root, config=config)
            except (OSError, ValueError, TypeError, sqlite3.Error, UnicodeError):
                result.issues.append({"client": client, "session_id": record.get("session_id"), "reason": "source_unreadable"})
                result.rows.append({"client": client, "session_id": record.get("session_id"), "ownership": "unknown", "readability": "unreadable", "processing": "not_selected"})
                continue
            source_id = transcript_source_id(client=client, project_name=project_name, session_id=native.session_id, source_uri=native.source_uri)
            reference = session_reference(client, native.session_id, source_id, f"sha256:{native.native_digest}")
            matching = [source for source in sources if source.client == client and source.session_id == native.session_id
                        and (source.source_uri == native.source_uri or source.raw_sha256 == native.native_digest)]
            matching_jobs = [job for job in jobs for source in matching if job.source_id == source.id
                             and job.source_revision == source.source_revision
                             and source.raw_sha256 == native.native_digest]
            seen_sources.update(source.id for source in matching)
            job = max(matching_jobs, key=lambda value: value.updated_at) if matching_jobs else None
            processing = "pending"
            if native.ownership != "project":
                processing = "not_selected"
            elif native.readability in {"empty_source", "empty_draft", "excluded"}:
                processing = "skipped"
            elif native.readability != "readable":
                processing = "blocked"
            elif job is not None:
                processing = "completed" if job.id in proven else "needs_verification" if job.status == "completed" else job.status
            row = {**reference, "ownership": native.ownership, "readability": native.readability, "processing": processing,
                   "imported": bool(matching_jobs), "origin": "native"}
            if job is not None:
                row["job_id"] = job.id
            # Only identical host identity AND bytes deduplicate native copies.
            key = (client, native.session_id, native.native_digest)
            if native.native_digest and key in by_identity:
                previous = by_identity[key]
                if previous["ownership"] != row["ownership"]:
                    previous.update(ownership="unknown", processing="not_selected")
                    result.native.pop(previous["reference_id"], None)
                continue
            by_identity[key] = row
            result.rows.append(row)
            if native.ownership == "project" and native.readability != "excluded":
                result.native[reference["reference_id"]] = native
        # Unknown/other ownership is counted, never eligible for a manual batch.
    for source in sources:
        if source.id in seen_sources:
            continue
        if not decide_capture(config, client=source.client, session_id=source.session_id, source_uri=source.source_uri).admitted:
            continue
        matching_jobs = [job for job in jobs if job.source_id == source.id and job.source_revision == source.source_revision]
        job = max(matching_jobs, key=lambda value: value.updated_at) if matching_jobs else None
        reference = session_reference(source.client, source.session_id, source.id, source.source_revision)
        result.rows.append({**reference, "ownership": "project", "readability": "readable" if source.coverage == "complete" else "partial",
                            "processing": "completed" if job and job.id in proven else "needs_verification" if job and job.status == "completed" else job.status if job else "pending",
                            "imported": True, "origin": "ledger", **({"job_id": job.id} if job else {})})
    result.rows.sort(key=lambda row: (row["client"], row.get("session_id", ""), row.get("source_id", ""), row.get("source_revision", "")))
    return result


def read_session_page(
    data_dir: Path, *, project_root: Path, project_name: str, session: dict,
    offset: int = 0, page_chars: int = 16000,
    adapter_factory: Callable[..., Any] | None = None,
) -> dict:
    if offset < 0 or page_chars < 1 or page_chars > 200000:
        raise ValueError("invalid source page range")
    expected = session_reference(*(str(session.get(key) or "") for key in ("client", "session_id", "source_id", "source_revision")))
    if session.get("reference_id") != expected["reference_id"]:
        raise ValueError("invalid session reference")
    config = load_merged_config(str(project_root))
    text: str | None = None
    if (data_dir / "transcript_ledger.sqlite").is_file():
        with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
            revision = ledger.get_revision(session["source_id"], session["source_revision"])
            if revision is not None:
                if (revision.project_name != project_name or normalized_root(revision.project_root) != normalized_root(project_root)
                        or revision.client != session["client"] or revision.session_id != session["session_id"]):
                    raise ValueError("source belongs to another project or session")
                if not decide_capture(config, client=revision.client, session_id=revision.session_id, source_uri=revision.source_uri).admitted:
                    raise ValueError("source excluded by capture policy")
                if revision.coverage != "complete":
                    raise ValueError("source coverage is incomplete")
                text = ledger.reconstruct(revision.source_id, source_revision=revision.source_revision)
    if text is None:
        inventory = collect_session_inventory(data_dir, project_root=project_root, project_name=project_name,
                                              clients=[session["client"]], adapter_factory=adapter_factory)
        native = inventory.native.get(session["reference_id"])
        if native is None:
            raise ValueError("source revision changed, unavailable, or outside project")
        text = native.text
    if config.capture_private_tags:
        text, _ = redact_private_text(text)
    if offset > len(text):
        raise ValueError("source offset exceeds complete text")
    end = min(len(text), offset + page_chars)
    return {"success": True, "session": expected, "offset": offset, "end": end,
            "total_chars": len(text), "content": text[offset:end], "content_sha256": sha256_text(text),
            "next_offset": end if end < len(text) else None,
            "complete": offset == 0 and end == len(text)}
