"""Frozen manual scope around existing per-session jobs, not another executor."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import closing, nullcontext
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import sqlite3
from typing import TYPE_CHECKING, Any, Callable

from harness_mem.adapters.source_inspection import normalized_root
from harness_mem.adapters.snapshot import persist_inspected_session
from harness_mem.capture_policy import decide_capture, source_capture_policy
from harness_mem.commands.distill_result import (
    DEFERRED_REVIEW_PIPELINE, deferred_review, distill_unfinished_work, project_distill_result,
)
from harness_mem.commands.session_inventory import (
    collect_session_inventory, completed_job_ids, current_entries, session_reference,
)
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.storage.manual_batch_store import ManualBatchStore, frozen_source_matches
from harness_mem.storage.canonical_store import CanonicalStoreRuntime, canonical_store_path
from harness_mem.storage.transcript_store import TranscriptStore

if TYPE_CHECKING:
    from harness_mem.adapters.antigravity.sqlite_cleanup import AntigravityCleanupPlan

_ARCHIVE_CHANGED = "archived_source_changed_or_unverified"


def runtime_fingerprint() -> str:
    """Pin the executing package bytes, not just its declared version."""
    import harness_mem
    package = Path(harness_mem.__file__).parent
    digest = sha256(str(harness_mem.__version__).encode())
    for path in sorted(package.rglob("*.py")):
        digest.update(path.relative_to(package).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _bound_manifests(backend: Any, job: SessionDistillJob):
    store = ManualBatchStore(backend.data_dir)
    for path in sorted(store.root.glob("*.json")):
        if path.is_symlink():
            continue
        header = json.loads(path.read_text(encoding="utf-8"))
        device_scope = header.get("scope") == "all"
        if not device_scope and (header.get("project_name") != job.project_name
                or normalized_root(header.get("project_root", "")) != normalized_root(job.project_root)):
            continue
        if job.id not in (header.get("bindings") or {}).values():
            continue
        manifest = store.load(path.stem, header["project_name"] if device_scope else job.project_name,
                              "" if device_scope else job.project_root)
        for ref, job_id in manifest["bindings"].items():
            if job_id == job.id:
                yield store, manifest, ref


def paused_batch_error(backend: Any, job: SessionDistillJob | None) -> str | None:
    """Block progress while a user pause still covers this job.

    This is not an integrity stop. Continue clears the hold without retrying
    failures or changing the captured revision. The manifest file and the
    transcript ledger are separate stores; callers re-read the manifest at the
    write boundary instead of treating the two as one transaction.
    """

    if job is None:
        return None
    revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    if ManualBatchStore(backend.data_dir).owning_pause(job, revision):
        return "batch_paused"
    return None


def manual_job_guard(backend: Any, job: SessionDistillJob, *, check_archive: bool = True) -> str | None:
    if not job.retain_source:
        return None
    from harness_mem.commands import session_inventory
    revision = backend.transcript_store.get_revision(job.source_id, job.source_revision)
    if revision is None:
        return "manual_source_revision_missing"
    try:
        config = source_capture_policy(revision.metadata.get("source_context_roots")
                                       or ([revision.project_root] if revision.project_root else []),
                                       config_loader=session_inventory.load_merged_config)
    except (OSError, ValueError):
        return "source_policy_unreadable"
    if not decide_capture(config, client=job.client, session_id=job.session_id, source_uri=revision.source_uri).admitted:
        return "source_excluded_by_capture_policy"
    if job.pipeline_version.startswith(DEFERRED_REVIEW_PIPELINE):
        previous = backend.transcript_store.get_distill_job(job.pipeline_version.removeprefix(DEFERRED_REVIEW_PIPELINE))
        if (previous is None or previous.source_id != job.source_id or previous.source_revision != job.source_revision
                or previous.status != "completed" or previous.id == job.id):
            return "manual_source_revision_missing"
        inherited = paused_batch_error(backend, previous) or manual_job_guard(
            backend, previous, check_archive=check_archive,
        )
        if inherited:
            return inherited
    for _store, manifest, ref in _bound_manifests(backend, job):
        if manifest["state"] == "stopped":
            return "manual_batch_stopped"
        if check_archive and manifest.get("archived_only") and job.source_cleanup_status != "deleted":
            reference = next(row for row in manifest["sessions"] if row["reference_id"] == ref)
            if (manifest["failures"].get(ref) == _ARCHIVE_CHANGED
                    or not _archive_selection_still_matches(backend, job, manifest, reference)):
                return _ARCHIVE_CHANGED
    return None


def is_manual_distill_job(backend: Any, job: SessionDistillJob) -> bool:
    """Exclude frozen manual selections even before import/binding or on restart."""
    return ManualBatchStore(backend.data_dir).owns_job(
        job, backend.transcript_store.get_revision(job.source_id, job.source_revision),
    )


def record_manual_finalize_failure(backend: Any, job_id: str, payload: dict) -> None:
    if payload.get("success"):
        return
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None or not job.retain_source:
        return
    redlines = {"promotion_write_unreadable", "promotion_write_missing", "runtime_version_changed",
                "source_revision_changed", "source_content_address_invalid", "distill_source_missing"}
    reasons = set(payload.get("reason_codes") or [])
    if _ARCHIVE_CHANGED in reasons:
        for store, manifest, ref in _bound_manifests(backend, job):
            if manifest.get("archived_only"):
                store.record_failure(manifest["batch_id"], manifest["project_name"], manifest["project_root"],
                                     ref, _ARCHIVE_CHANGED)
        return
    if not reasons.intersection(redlines) and "another project" not in str(payload.get("error") or ""):
        return
    for store, manifest, ref in _bound_manifests(backend, job):
        store.record_failure(manifest["batch_id"], manifest["project_name"], manifest["project_root"],
                             ref, "completion_verification_failed", stop_batch=True)


def _same_job_scope(job: SessionDistillJob, manifest: dict, reference: dict, ledger: TranscriptStore) -> bool:
    if job.source_cleanup_status == "deleted" or not job.session_id and not job.project_root:
        if "batch_id" not in manifest or "bindings" not in manifest:
            return False
        return _cleaned_manual_source_matches(job, manifest, reference, ledger, require_complete=False)
    if manifest.get("scope") == "all":
        reference_id = reference["reference_id"]
        validated = manifest.get("validated", {}).get(reference_id)
        return frozen_source_matches(job, ledger.get_revision(job.source_id, job.source_revision),
                                     validated or reference, metadata_hint=validated is None)
    if (job.project_name != manifest["project_name"]
            or normalized_root(job.project_root) != normalized_root(manifest["project_root"])
            or job.client != reference["client"] or job.session_id != reference["session_id"]):
        return False
    revision = ledger.get_revision(job.source_id, job.source_revision)
    if (revision is None or revision.project_name != job.project_name
            or normalized_root(revision.project_root) != normalized_root(job.project_root)
            or revision.client != job.client or revision.session_id != job.session_id):
        return False
    return (job.source_id == reference["source_id"] and job.source_revision == reference["source_revision"]
            or f"sha256:{revision.raw_sha256}" == reference["source_revision"])


def _cleanup_scope(manifest: dict, reference: dict) -> dict[str, str]:
    return {
        "manual_batch_id_sha256": sha256(manifest["batch_id"].encode()).hexdigest(),
        "manual_reference_id_sha256": sha256(reference["reference_id"].encode()).hexdigest(),
        "project_root_sha256": sha256(normalized_root(manifest["project_root"]).encode()).hexdigest(),
    }


def _manual_cleanup_receipt(job: SessionDistillJob, manifest: dict, reference: dict,
                            ledger: TranscriptStore) -> dict | None:
    frozen = manifest.get("validated", {}).get(reference["reference_id"], reference)
    expected = {
        **_cleanup_scope(manifest, reference),
        "job_id_sha256": sha256(job.id.encode()).hexdigest(),
        "source_id_sha256": sha256(job.source_id.encode()).hexdigest(),
        "source_revision_sha256": sha256(job.source_revision.encode()).hexdigest(),
        "session_id_sha256": sha256(frozen["session_id"].encode()).hexdigest(),
    }
    return next((receipt for receipt in ledger.list_deletion_audit(project_name=job.project_name)
                 if (not job.source_cleanup_receipt_id or receipt.get("id") == job.source_cleanup_receipt_id)
                 and receipt.get("kind") == "processed_source_cleanup"
                 and receipt.get("project_name") == job.project_name
                 and all((receipt.get("scope") or {}).get(key) == value for key, value in expected.items())), None)


def _cleaned_manual_source_matches(job: SessionDistillJob, manifest: dict, reference: dict,
                                   ledger: TranscriptStore, *, require_complete: bool = True) -> bool:
    frozen = manifest.get("validated", {}).get(reference["reference_id"], reference)
    # The pre-cleanup full-body check may bind a moved native locator to an
    # existing canonical source. The receipt separately seals both identities.
    for value in (reference, frozen):
        if session_reference(*(value[key] for key in ("client", "session_id", "source_id", "source_revision"))) != value:
            return False
    if (manifest["bindings"].get(reference["reference_id"]) != job.id
            or job.client != frozen["client"]
            or manifest.get("scope") != "all" and job.project_name != manifest["project_name"]):
        return False
    receipt = _manual_cleanup_receipt(job, manifest, reference, ledger)
    if not receipt or (receipt.get("native_cleanup") or {}).get("status") != "deleted":
        return False
    if require_complete and (receipt.get("status") != "succeeded" or (receipt.get("verification") or {}).get("passed") is not True):
        return False
    remaining = ledger.verify_completed_distill_evidence_pruned(job.id)
    return remaining.get("completed_job") == 1 and not any(value for key, value in remaining.items() if key != "completed_job")


def _manual_retained_outputs(backend: Any, job: SessionDistillJob, reference: dict) -> tuple[dict, Path | None, str | None]:
    """Retain actual task artifacts across every revision affected by source pruning."""
    from harness_mem.mcp.distill_handlers import _session_notes_dir
    from harness_mem.session_notes import existing_session_note_path
    from harness_mem.processed_source_cleanup import retained_handoff_error

    store = backend.structured_store
    jobs = backend.transcript_store.list_distill_jobs()
    entries = current_entries(Path(backend.data_dir), None)
    proven, superseded = completed_job_ids(jobs, entries)
    rows = store.list_record_payloads("task_handoffs", strict=True)
    task_job_ids = {row.get("context", {}).get("distill_job_id") or row.get("task_id") for row in rows
                    if row.get("project_name") == job.project_name}
    affected = [value for value in jobs if value.source_id == job.source_id and (
        value.id == job.id or distill_unfinished_work(value)
        or (value.promotion_summary.get("readback") or {}).get("handoff_ids") or value.id in task_job_ids)]
    digests: dict[str, str] = {}
    historical_notes: dict[str, str] = {}
    historical_unavailable_truth_ids: dict[str, list[str]] = {}
    current_note: Path | None = None
    notes_dir = _session_notes_dir(backend).resolve()
    for bound in affected:
        if bound.project_name != job.project_name or bound.id == job.id and bound.id not in proven:
            return {}, None, "affected_source_job_needs_verification"
        confirmed = [point for point in bound.promotion_summary.get("points", []) if point.get("disposition") == "confirm"]
        if bound.id == job.id and any(not point.get("canonical_truth_ids") or any(identity not in entries and identity not in superseded
               for identity in point["canonical_truth_ids"]) for point in confirmed):
            return {}, None, "confirmed_knowledge_unreadable"
        recorded = set((bound.promotion_summary.get("readback") or {}).get("handoff_ids") or [])
        payloads = {row["id"]: row for row in rows if row.get("project_name") == bound.project_name
                    and ((row.get("context") or {}).get("distill_job_id") == bound.id or row.get("task_id") == bound.id)}
        if set(payloads) != recorded:
            return {}, None, "handoff_readback_incomplete"
        saved_work = {str(text).strip() for row in payloads.values()
                      for text in row.get("next_steps") or [row.get("summary") or ""] if str(text).strip()}
        if set(distill_unfinished_work(bound)) - saved_work:
            return {}, None, "unfinished_work_not_preserved"
        if recorded and not saved_work:
            return {}, None, "handoff_content_missing"
        digests.update({identity: store.record_payload_sha256("task_handoffs", identity) for identity in recorded})
        note_job = bound.model_copy(update={"session_id": reference["session_id"]}) if bound.id == job.id else bound
        note, _ = existing_session_note_path(notes_dir, note_job)
        if (note is None or note.is_symlink() or not note.resolve().is_relative_to(notes_dir)
                or len(note.read_text(encoding="utf-8").strip()) < 12):
            return {}, None, "final_note_unreadable"
        if bound.id == job.id:
            current_note = note
        else:
            historical_notes[bound.id] = sha256(note.read_bytes()).hexdigest()
            missing = sorted({identity for point in bound.promotion_summary.get("points", [])
                              if point.get("disposition") in {"add", "confirm", "refine", "replace"}
                              for identity in point.get("canonical_truth_ids", [])
                              if identity not in entries and identity not in superseded})
            if missing:
                historical_unavailable_truth_ids[bound.id] = missing
    error = retained_handoff_error(backend, job, digests)
    if error:
        return {}, None, error
    if current_note is None:
        return {}, None, "final_note_unreadable"
    return {"handoffs": digests, "final_note_sha256": sha256(current_note.read_bytes()).hexdigest(),
            "historical_notes": historical_notes,
            "historical_unavailable_truth_ids": historical_unavailable_truth_ids}, current_note, None


def _handoffs_require_native_evidence(backend: Any, preserved: dict, actions: Any) -> bool:
    """Do not remove explicitly referenced proof files or raw-exchange evidence."""
    from harness_mem.native_source_cleanup import path_from_local_file_uri

    def depends(value: Any, *, evidence: bool = False) -> bool:
        if isinstance(value, dict):
            if evidence and value.get("kind") in {"session_exchange", "transcript", "raw_source"}:
                return True
            return any(depends(item, evidence=evidence or key in {"verification_refs", "evidence_refs", "proof_refs"})
                       for key, item in value.items())
        if isinstance(value, list):
            return any(depends(item, evidence=evidence) for item in value)
        if not isinstance(value, str):
            return False
        paths = []
        for uri in re.findall(r"file://[^\s\"'<>]+", value):
            try:
                paths.append(path_from_local_file_uri(uri.rstrip(".,;")))
            except ValueError:
                return True
        if Path(value).is_absolute():
            paths.append(Path(value))
        return any(path.resolve() == action.target.resolve()
                   or action.kind == "directory" and path.resolve().is_relative_to(action.target.resolve())
                   for path in paths for action in actions)

    return any(depends(backend.structured_store.read_record_payload("task_handoffs", identity))
               for identity in preserved["handoffs"])


def _project_batch(manifest: dict, jobs: dict[str, SessionDistillJob], entries: dict[str, dict], *, proof_jobs: list[SessionDistillJob] | None = None, handoffs: list[dict] | None = None) -> dict:
    statuses: list[dict] = []
    result_points: list[dict] = []
    empty_reasons: list[str] = []
    unfinished_work: list[str] = []
    proven, _ = completed_job_ids(proof_jobs if proof_jobs is not None else list(jobs.values()), entries)
    for reference in manifest["sessions"]:
        ref = reference["reference_id"]
        job = jobs.get(manifest["bindings"].get(ref, ""))
        reason = manifest["failures"].get(ref)
        skipped = manifest.get("skipped", {}).get(ref)
        status = "skipped" if skipped else "blocked" if reason else "pending"
        if not reason and job is not None:
            status = "completed" if job.id in proven else "needs_verification" if job.status == "completed" else job.status
        statuses.append({"reference_id": ref, "status": status, **({"reason": reason} if reason else {}),
                         **(deferred_review(job) if job is not None and status == "completed"
                            and manifest["state"] == "active" else {})})
        resolved_job_handoffs = False
        if job is not None:
            recorded_handoffs = set(job.promotion_summary.get("readback", {}).get("handoff_ids") or [])
            closed_handoffs = {
                handoff["id"] for handoff in handoffs or []
                if handoff.get("project_name") == job.project_name and handoff.get("status") == "done"
                and (handoff.get("context") or {}).get("distill_job_id") == job.id
            }
            resolved_job_handoffs = bool(recorded_handoffs and recorded_handoffs <= closed_handoffs)
            # Closed task records resolve the old work list, not the historical
            # receipt or any knowledge evidence. Untracked work stays visible.
            if not resolved_job_handoffs:
                unfinished_work.extend(distill_unfinished_work(job))
            for handoff in handoffs or []:
                bound = (handoff.get("context") or {}).get("distill_job_id")
                if (handoff.get("project_name") == job.project_name
                        and handoff.get("status") != "done"
                        and (bound == job.id or not bound and handoff.get("task_id") == job.id)):
                    unfinished_work.extend(handoff.get("next_steps") or [handoff.get("summary") or "继续处理未完成事项。"])
        if status != "completed" or job is None:
            if skipped:
                empty_reasons.append("原始会话没有对话内容" if skipped in {"empty_draft", "empty_source"} else "按已有隐私设置不读取")
            continue
        if ref in manifest.get("already_completed", []):
            continue
        points = job.promotion_summary.get("points") or []
        result_points.extend(
            {**point, "disposition": "no_write"}
            if resolved_job_handoffs and point.get("disposition") in {"defer", "handoff", "conflict"}
            else point for point in points
        )
        if not points:
            reason = "保留为未完成事项" if recorded_handoffs and not resolved_job_handoffs else "没有需要长期记住的内容"
            empty_reasons.append(reason)
    counts = dict(Counter(item["status"] for item in statuses))
    verified = counts.get("completed", 0)
    total = len(manifest["sessions"])
    finished = verified + counts.get("skipped", 0)
    if manifest["state"] == "stopped":
        status = "stopped"
    elif finished == total:
        status = "completed"
    elif manifest["state"] == "paused":
        status = "paused"
    else:
        status = "partial"
    result = project_distill_result(result_points, entries, empty_reasons=empty_reasons,
        unfinished_work=unfinished_work, source_review_complete=(finished == total
            and all(job.semantic_review.get("evidence_status") == "answered"
                    and job.semantic_review.get("promotion_decision") == "promote"
                    and job.promotion_summary.get("readback", {}).get("verified") is True
                    for job in jobs.values())))
    if finished != total:
        result["organization_status"] = "partial"
    return {
        "success": True, "batch_id": manifest["batch_id"], "status": status,
        "progress": {"selected": total, "completed": verified, "remaining": total - finished, "states": counts},
        "sessions": statuses,
        **result,
    }


def inspect_manual_batch(
    data_dir: Path, *, project_name: str, project_root: Path | None, batch_id: str,
    check_new: bool = True,
) -> dict:
    root_text = str(project_root) if project_root is not None else ""
    manifest = ManualBatchStore(data_dir).load(batch_id, project_name, root_text)
    jobs: dict[str, SessionDistillJob] = {}
    proof_jobs: list[SessionDistillJob] = []
    if (data_dir / "transcript_ledger.sqlite").is_file():
        with closing(TranscriptStore(data_dir, read_only=True)) as ledger:
            for ref in manifest["sessions"]:
                job_id = manifest["bindings"].get(ref["reference_id"])
                if job_id is None:
                    continue
                job = ledger.get_distill_job(job_id)
                if job is None or not _same_job_scope(job, manifest, ref, ledger):
                    raise ValueError("batch job binding no longer matches the selected project revision")
                jobs[job.id] = job
            proof_jobs = [job for job in ledger.list_distill_jobs(project_name=project_name if project_root is not None else None)
                          if project_root is None or normalized_root(job.project_root) == normalized_root(project_root)
                          or job.id in jobs]
    handoffs: list[dict] = []
    if canonical_store_path(data_dir).is_file():
        with closing(CanonicalStoreRuntime(data_dir, read_only=True)) as store:
            handoffs = store.list_payloads("task_handoffs", project_name=project_name if project_root is not None else None)
    payload = _project_batch(manifest, jobs, current_entries(data_dir, project_name if project_root is not None else None), proof_jobs=proof_jobs, handoffs=handoffs)
    if check_new:
        inventory = collect_session_inventory(data_dir, project_root=project_root, project_name=project_name,
                                              clients=sorted({ref["client"] for ref in manifest["sessions"]}), lightweight=True)
        frozen = {ref["reference_id"] for ref in manifest["sessions"]}
        frozen_identities = {(ref["client"], ref["session_id"]) for ref in manifest["sessions"]}
        payload["outside_batch_pending"] = sum(
            row.get("reference_id") not in frozen and row["ownership"] in {"project", "source"}
            and (row["client"], row["session_id"]) not in frozen_identities
            and row["processing"] not in {"completed", "skipped"}
            for row in inventory.rows
        )
    return payload


def _archive_selection_still_matches(backend: Any, job: SessionDistillJob, manifest: dict, reference: dict) -> bool:
    """Bind a live archive flag and the exact source bytes to the frozen locator."""
    source = backend.transcript_store.get_source(job.source_id)
    if source is None or source.source_revision != job.source_revision:
        return False
    locator = source.metadata.get("native_source_uri", source.source_uri)
    expected_digest = source.metadata.get("native_input_sha256")
    expected_primary = source.metadata.get("cursor_cleanup_primary_sha256")
    if not expected_digest:
        return False
    root = Path(manifest["project_root"]) if manifest["project_root"] else None
    inventory = collect_session_inventory(
        Path(backend.data_dir), project_root=root, project_name=manifest["project_name"],
        clients=[job.client], selected_sessions=[reference], session_id=job.session_id, archived_only=True,
    )
    for native in inventory.native.values():
        if native.source_uri != locator or native.native_digest != source.raw_sha256 or native.readability != "readable":
            continue
        if expected_primary and native.cursor_cleanup_primary_sha256 != expected_primary:
            continue
        digest = native.native_input_digest
        if digest is None and native.native_input_bytes is not None:
            digest = sha256(native.native_input_bytes).hexdigest()
        if digest == expected_digest:
            return True
    return False


def _recheck_legacy_cleanup_file(data_dir: Path, source: TranscriptSource) -> TranscriptSource | None:
    """Recover missing file type for cleanup without rewriting the stored revision."""
    from harness_mem.native_source_cleanup import build_native_cleanup_descriptor

    locator = source.metadata.get("native_source_uri")
    native_digest = source.metadata.get("native_input_sha256")
    original_roots = source.metadata.get("source_context_roots") or []
    if (not isinstance(locator, str) or not isinstance(native_digest, str)
            or not isinstance(original_roots, list) or any(not isinstance(path, str) for path in original_roots)):
        return None
    root = Path(source.project_root) if source.project_root else None
    inventory = collect_session_inventory(
        data_dir, project_root=root, project_name=source.project_name,
        clients=[source.client], session_id=source.session_id,
    )
    for inspected in inventory.native.values():
        kind = inspected.native_cleanup_file_kind
        if (kind is None or inspected.readability != "readable" or inspected.source_uri != locator
                or inspected.native_digest != source.raw_sha256 or inspected.native_input_bytes is None
                or sha256(inspected.native_input_bytes).hexdigest() != native_digest):
            continue
        if {normalized_root(path) or path for path in inspected.project_roots or []} != {
            normalized_root(path) or path for path in original_roots
        }:
            continue
        descriptor = build_native_cleanup_descriptor(client=source.client, source_kind=kind, source_uri=locator)
        if descriptor is not None:
            return source.model_copy(update={"source_kind": kind, "metadata": {
                **source.metadata, "native_cleanup_descriptor": descriptor,
            }})
    return None


def cleanup_manual_batch(
    backend: Any, *, project_name: str, project_root: Path | None, batch_id: str,
    apply: bool = False,
) -> dict:
    """Preview or explicitly remove verified, completed frozen session sources.

    This is a separate maintenance action. It never resumes semantic processing,
    relaxes source retention, or changes the batch's selected sessions.
    """
    from harness_mem.adapters.cursor.sqlite_cleanup import (
        CursorCleanupPlan, apply_cursor_cleanup, cursor_receipt_absence_verified,
        cursor_source_absence_verified, discard_cursor_cleanup_backup, is_cursor_sqlite_source,
        plan_cursor_cleanup,
    )
    from harness_mem.adapters.cursor.cross_store_cleanup import apply_cursor_cross_cleanup, plan_cursor_cross_recovery
    from harness_mem.adapters.hermes.sqlite_cleanup import (
        HermesCleanupPlan, apply_hermes_cleanup, discard_hermes_cleanup_backup, hermes_receipt_absence_verified,
        hermes_source_absence_verified, is_hermes_sqlite_source, plan_hermes_cleanup,
    )
    from harness_mem.maintenance_lock import exclusive_maintenance_run
    from harness_mem.native_source_cleanup import (
        NativeCleanupPlan, apply_native_source_cleanup, path_from_local_file_uri, plan_native_source_cleanup,
    )
    from harness_mem.processed_source_cleanup import (
        _plan_structured_cleanup, begin_processed_source_cleanup, cleanup_processed_source,
    )
    from harness_mem.mcp.distill_handlers import _promotion_commit_error

    store = ManualBatchStore(backend.data_dir)
    root_text = str(project_root) if project_root is not None else ""
    # Validate the exact existing selection before creating even a maintenance lock.
    manifest = store.load(batch_id, project_name, root_text)
    lock = exclusive_maintenance_run(
        Path(backend.data_dir), run_id=f"manual-cleanup-{batch_id}", operation="manual_history_cleanup",
    ) if apply else nullcontext()
    outcomes: list[dict] = []
    try:
        with lock:
            manifest = store.load(batch_id, project_name, root_text)
            if manifest["state"] != "active":
                return {"success": False, "batch_id": batch_id, "mode": "apply" if apply else "preview",
                        "status": manifest["state"], "error": "batch_must_be_active", "sessions": []}
            ledger = backend.transcript_store
            jobs = ledger.list_distill_jobs()
            entries = current_entries(Path(backend.data_dir), None)
            proven, superseded = completed_job_ids(jobs, entries)
            for position, reference in enumerate(manifest["sessions"], 1):
                ref = reference["reference_id"]
                frozen = manifest.get("validated", {}).get(ref, reference)
                outcome = {"reference_id": ref, "position": position, "client": frozen["client"],
                           "source_revision": frozen["source_revision"], "status": "retained", "reason_codes": []}
                outcomes.append(outcome)
                if ref in manifest.get("skipped", {}):
                    outcome.update(status="skipped", reason_codes=[manifest["skipped"][ref]])
                    continue
                if ref in manifest["failures"]:
                    outcome["reason_codes"] = ["batch_source_has_failure"]
                    continue
                job = ledger.get_distill_job(manifest["bindings"].get(ref, ""))
                if job is None or not _same_job_scope(job, manifest, reference, ledger):
                    outcome["reason_codes"] = ["job_scope_or_revision_changed"]
                    continue
                outcome.update(project_name=job.project_name, source_revision=job.source_revision)
                if job.id not in proven:
                    outcome["reason_codes"] = ["completed_job_needs_verification"]
                    continue
                confirmed = [point for point in job.promotion_summary.get("points", [])
                             if point.get("disposition") == "confirm"]
                if any(not point.get("canonical_truth_ids") or any(
                        identity not in entries and identity not in superseded
                        for identity in point["canonical_truth_ids"]) for point in confirmed):
                    outcome["reason_codes"] = ["confirmed_knowledge_unreadable"]
                    continue
                source_jobs = [value for value in jobs if value.source_id == job.source_id]
                now = datetime.now(timezone.utc)
                if any(value.review_lease_until and value.review_lease_until > now
                       or any(checkpoint.lease_until and checkpoint.lease_until > now
                              for checkpoint in ledger.list_distill_checkpoints(value.id)) for value in source_jobs):
                    outcome["reason_codes"] = ["source_has_active_review"]
                    continue
                if any(point.get("disposition") in {"defer", "conflict", "pending", "handoff"}
                       for value in source_jobs for point in value.promotion_summary.get("points", [])):
                    outcome["reason_codes"] = ["unresolved_semantic_work_keeps_source"]
                    continue
                preserved, note_path, preserve_error = _manual_retained_outputs(backend, job, reference)
                if preserve_error:
                    outcome["reason_codes"] = [preserve_error]
                    continue
                # Read actual current successors through the same ordinary-consumer gate
                # used by finalize, including replacements of older selected outputs.
                readback_error = None
                relevant_jobs = {value.id for value in source_jobs if value.id == job.id or distill_unfinished_work(value)
                                 or (value.promotion_summary.get("readback") or {}).get("handoff_ids")}
                related_truth = {identity for value in source_jobs if value.id in relevant_jobs
                                 for point in value.promotion_summary.get("points", [])
                                 for identity in point.get("canonical_truth_ids", [])}
                while True:
                    successors = [value for value in jobs if value.id in proven and value.id not in relevant_jobs
                                  and value.project_name == job.project_name
                                  and any(related_truth.intersection(point.get("replaced_truth_ids", []))
                                          for point in value.promotion_summary.get("points", []))]
                    if not successors:
                        break
                    for value in successors:
                        relevant_jobs.add(value.id)
                        related_truth.update(identity for point in value.promotion_summary.get("points", [])
                                             for identity in point.get("canonical_truth_ids", []))
                for value in jobs:
                    if value.id not in relevant_jobs:
                        continue
                    points = [{**point, "disposition": "add", "canonical_truth_ids": [identity for identity in point.get("canonical_truth_ids", [])
                                                                if identity in entries]}
                              for point in value.promotion_summary.get("points", [])
                              if point.get("disposition") in {"add", "refine", "replace", "confirm"}
                              and any(identity in entries for identity in point.get("canonical_truth_ids", []))]
                    if points:
                        readback_error = asyncio.run(_promotion_commit_error(
                            backend, project_name=value.project_name,
                            promotion_summary={"promoted": len(points), "points": points},
                        ))
                        if readback_error:
                            break
                if readback_error:
                    outcome["reason_codes"] = [readback_error]
                    continue
                outcome["review"] = {
                    "completion": job.completion_disposition,
                    "readback_verified": True,
                    "current_knowledge": len(related_truth.intersection(entries)),
                    "final_note_sha256": preserved["final_note_sha256"],
                    "handoffs": len(preserved["handoffs"]),
                }
                prior = _manual_cleanup_receipt(job, manifest, reference, ledger)
                if prior and prior.get("preserved_outputs") != preserved:
                    outcome["reason_codes"] = ["retained_outputs_changed"]
                    continue
                pruned = bool(prior and _cleaned_manual_source_matches(job, manifest, reference, ledger, require_complete=False))
                if pruned and prior is not None:
                    native_receipt = prior.get("native_cleanup", {})
                    if native_receipt.get("storage") == "cursor_sqlite":
                        # The receipt probe checks the exact primary, search and
                        # companion locations. Unrelated inventory warnings do
                        # not describe this archive's native absence.
                        cross = native_receipt.get("cross_store")
                        rowid = (cross.get("search_rowid") or 0) if isinstance(cross, dict) else None
                        if not cursor_receipt_absence_verified(
                            native_receipt.get("locator_sha256", ""), reference["session_id"], search_rowid=rowid,
                        ):
                            outcome["reason_codes"] = ["cursor_cleanup_absence_unverified"]
                            continue
                    elif native_receipt.get("storage") == "hermes_sqlite":
                        if not hermes_receipt_absence_verified(
                            native_receipt.get("locator_sha256", ""), reference["session_id"],
                            message_ids=native_receipt.get("message_ids", ()),
                        ):
                            outcome["reason_codes"] = ["hermes_cleanup_absence_unverified"]
                            continue
                    elif native_receipt.get("storage") == "antigravity_sqlite":
                        from harness_mem.adapters.antigravity.sqlite_cleanup import antigravity_receipt_absence_verified

                        if not antigravity_receipt_absence_verified(
                            native_receipt.get("locator_sha256", ""), reference["session_id"],
                            witness=native_receipt.get("antigravity"),
                        ):
                            outcome["reason_codes"] = ["antigravity_cleanup_absence_unverified"]
                            continue
                    else:
                        inventory = collect_session_inventory(
                            Path(backend.data_dir), project_name=project_name, project_root=project_root,
                            clients=[reference["client"]], selected_sessions=[reference], lightweight=True,
                        )
                        if any(value.get("origin") == "native" for value in inventory.rows):
                            outcome["reason_codes"] = ["native_source_reappeared"]
                            continue
                        if inventory.issues:
                            outcome["reason_codes"] = ["native_source_absence_unverified"]
                            continue
                if job.source_cleanup_status == "deleted" and _cleaned_manual_source_matches(job, manifest, reference, ledger):
                    outcome.update(status="already_deleted", receipt_id=job.source_cleanup_receipt_id)
                    if prior is not None:
                        accounting = prior.get("native_cleanup", {}).get("accounting")
                        if accounting is not None:
                            outcome["native"] = accounting
                    continue
                source = ledger.get_source(job.source_id)
                revision = ledger.get_revision(job.source_id, job.source_revision)
                if source is None or revision is None or source.source_revision != job.source_revision:
                    outcome["reason_codes"] = ["source_revision_changed"]
                    continue
                if _plan_structured_cleanup(backend, job)["blocking_candidate_ids"]:
                    outcome["reason_codes"] = ["unresolved_candidates"]
                    continue
                resume_prune = (prior if prior and prior.get("status") in {"partial_failure", "in_progress"}
                                and (prior.get("native_cleanup") or {}).get("status") == "deleted" else None)
                cross_witness = (prior.get("native_cleanup", {}).get("cross_store")
                                 if prior and is_cursor_sqlite_source(source) else None)
                recover_cross = cross_witness if not resume_prune and isinstance(cross_witness, dict) else None
                if (not resume_prune and recover_cross is None and manifest.get("archived_only")
                        and not _archive_selection_still_matches(backend, job, manifest, reference)):
                    uncertain_commit = (prior and is_cursor_sqlite_source(source)
                                        and cursor_source_absence_verified(source))
                    outcome["reason_codes"] = ["cursor_cleanup_commit_unverified" if uncertain_commit else _ARCHIVE_CHANGED]
                    continue
                cleanup_source = source
                if (not resume_prune and source.client in {"hermes", "antigravity"}
                        and source.source_kind == "native-session-export"
                        and source.parser_version == "native-inspected-source-v1"):
                    # Shared exports have a URI fragment and remain unsupported
                    # by the existing file planner.
                    locator = str(source.metadata.get("native_source_uri") or source.source_uri)
                    if "#" not in locator:
                        rebound = _recheck_legacy_cleanup_file(Path(backend.data_dir), source)
                        if rebound is None:
                            outcome["reason_codes"] = ["legacy_native_source_unverified"]
                            continue
                        cleanup_source = rebound
                cursor_sqlite = is_cursor_sqlite_source(cleanup_source)
                hermes_sqlite = is_hermes_sqlite_source(cleanup_source)
                antigravity_sqlite = cleanup_source.client == "antigravity" and cleanup_source.source_kind == "antigravity-sqlite"
                agy_witness = prior.get("native_cleanup", {}).get("antigravity") if antigravity_sqlite and prior else None
                recover_agy = agy_witness if not resume_prune and isinstance(agy_witness, dict) else None
                native: CursorCleanupPlan | NativeCleanupPlan | HermesCleanupPlan | AntigravityCleanupPlan
                if recover_cross is not None and prior is not None:
                    try:
                        native = plan_cursor_cross_recovery(
                            cleanup_source, data_dir=Path(backend.data_dir), receipt_id=prior["id"],
                            witness=recover_cross,
                        )
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("cursor_") else "cursor_cross_store_recovery_unverified"
                        outcome["reason_codes"] = [reason]
                        continue
                elif recover_agy is not None and prior is not None:
                    from harness_mem.adapters.antigravity.sqlite_cleanup import plan_antigravity_sqlite_recovery

                    try:
                        native = plan_antigravity_sqlite_recovery(
                            cleanup_source, data_dir=Path(backend.data_dir), receipt_id=prior["id"], witness=recover_agy,
                        )
                    except (OSError, ValueError, sqlite3.Error) as exc:
                        reason = str(exc) if isinstance(exc, ValueError) and str(exc).startswith("antigravity_") else "antigravity_cleanup_recovery_unverified"
                        outcome["reason_codes"] = [reason]
                        continue
                elif cursor_sqlite:
                    native = plan_cursor_cleanup(cleanup_source)
                elif hermes_sqlite:
                    native = plan_hermes_cleanup(cleanup_source)
                elif antigravity_sqlite:
                    from harness_mem.adapters.antigravity.sqlite_cleanup import plan_antigravity_sqlite_cleanup

                    native = plan_antigravity_sqlite_cleanup(cleanup_source)
                else:
                    native = plan_native_source_cleanup(cleanup_source)
                native_preview = native.to_preview()
                accounting: dict[str, Any] = {
                    "locator_sha256": native_preview["locator_sha256"],
                    "plan_counts": native_preview["counts"],
                    # For shared stores these are record groups within the
                    # selected session, never a plan to delete the container.
                    "file_targets": [
                        {"kind": action.kind, "locator_sha256": action.locator_sha256}
                        for action in native.actions
                    ] if not (cursor_sqlite or hermes_sqlite) else [],
                }
                if isinstance(native, CursorCleanupPlan):
                    accounting["record_sets"] = {
                        "primary": {"sha256": native.primary_sha256, "key_value_rows": len(native.keys)},
                        **({"search": {"sha256": native.search_sha256, "records": 3}}
                           if native.search_database is not None else {}),
                    }
                elif isinstance(native, HermesCleanupPlan):
                    accounting["record_sets"] = {"state": {"sha256": native.witness, "counts": native.counts}}
                elif antigravity_sqlite:
                    accounting["record_sets"] = {"summary_and_companions": {
                        "sha256": cleanup_source.metadata.get("antigravity_cleanup_sha256"),
                        "counts": {key: count for key, count in native_preview["counts"].items()
                                   if key in {"summary_rows", "search_rows", "protobuf_entries"}},
                    }}
                elif isinstance(native, NativeCleanupPlan) and native.expected_native_sha256:
                    accounting["native_sha256"] = native.expected_native_sha256
                if prior is not None and (resume_prune or recover_cross or recover_agy):
                    accounting = prior.get("native_cleanup", {}).get("accounting") or accounting
                outcome["native"] = accounting
                if _handoffs_require_native_evidence(backend, preserved, native.actions):
                    outcome["reason_codes"] = ["handoff_requires_native_evidence"]
                    continue
                if resume_prune:
                    if not pruned:
                        locator = str(source.metadata.get("native_source_uri") or source.source_uri)
                        rowid = (cross_witness.get("search_rowid") or 0) if isinstance(cross_witness, dict) else None
                        if cursor_sqlite:
                            absent = cursor_source_absence_verified(source, search_rowid=rowid)
                        elif hermes_sqlite:
                            absent = hermes_source_absence_verified(source, message_ids=resume_prune["native_cleanup"].get("message_ids", ()))
                        elif antigravity_sqlite:
                            from harness_mem.adapters.antigravity.sqlite_cleanup import antigravity_source_absence_verified

                            absent = antigravity_source_absence_verified(source, witness=agy_witness)
                        else:
                            absent = not path_from_local_file_uri(locator).exists()
                        if ((resume_prune.get("native_cleanup") or {}).get("locator_sha256") != sha256(locator.encode()).hexdigest()
                                or not absent):
                            outcome["reason_codes"] = ["native_source_reappeared"]
                            continue
                elif native.retained or not native.supported:
                    outcome.update(status="retained" if native.retained else "unsupported",
                                   reason_codes=list(native.reason_codes))
                    if cursor_sqlite and prior and "cursor_cleanup_source_absent" in native.reason_codes:
                        outcome["reason_codes"] = ["cursor_cleanup_commit_unverified"]
                    if hermes_sqlite and prior and "hermes_cleanup_source_absent" in native.reason_codes:
                        outcome["reason_codes"] = ["hermes_cleanup_commit_unverified"]
                    continue
                if not apply:
                    outcome.update(status="ready", reason_codes=["completed_source_verified"],
                                   counts=accounting["plan_counts"])
                    continue
                # Re-read source scope after all read-only checks and before the saga.
                fresh = ledger.get_distill_job(job.id)
                fresh_source = ledger.get_source(job.source_id)
                fresh_manifest = store.load(batch_id, project_name, root_text)
                if (fresh is None or fresh.to_dict() != job.to_dict() or fresh_source is None
                        or fresh_source.to_dict() != source.to_dict()
                        or fresh_manifest["state"] != "active"
                        or fresh_manifest["bindings"].get(ref) != job.id
                        or ref in fresh_manifest["failures"]
                        or not pruned and manual_job_guard(backend, fresh, check_archive=not resume_prune and recover_cross is None)):
                    outcome["reason_codes"] = ["source_changed_before_cleanup"]
                    continue
                fresh_preserved, _, preserve_error = _manual_retained_outputs(backend, fresh, reference)
                if preserve_error or fresh_preserved != preserved:
                    outcome["reason_codes"] = [preserve_error or "retained_outputs_changed"]
                    continue
                if resume_prune:
                    receipt = dict(resume_prune)
                    receipt["status"] = "in_progress"
                    ledger.save_deletion_receipt(receipt)
                    receipt_id = receipt["id"]
                    native_result = {"status": "deleted"}
                else:
                    if (recover_cross is not None or recover_agy is not None) and prior is not None:
                        receipt = dict(prior)
                        receipt["status"] = "in_progress"
                        receipt_id = receipt["id"]
                    else:
                        if (cursor_sqlite and prior
                                and prior.get("native_cleanup", {}).get("status") in {"planned", "retained"}
                                and not discard_cursor_cleanup_backup(Path(backend.data_dir), prior["id"])):
                            outcome["reason_codes"] = ["cursor_cleanup_backup_retained"]
                            continue
                        if (hermes_sqlite and prior
                                and prior.get("native_cleanup", {}).get("status") in {"planned", "retained", "partial_failure"}
                                and not discard_hermes_cleanup_backup(Path(backend.data_dir), prior["id"])):
                            outcome["reason_codes"] = ["hermes_cleanup_backup_retained"]
                            continue
                        begun = begin_processed_source_cleanup(backend, job_id=job.id, native_preview=native_preview)
                        if not begun.get("success"):
                            outcome.update(status="partial_failure", reason_codes=begun.get("reason_codes", []))
                            continue
                        receipt_id = begun["receipt_id"]
                        receipt = next(value for value in ledger.list_deletion_audit(project_name=job.project_name)
                                       if value["id"] == receipt_id)
                        receipt["scope"].update(_cleanup_scope(manifest, reference))
                        receipt["preserved_outputs"] = preserved
                        if cursor_sqlite:
                            receipt["native_cleanup"]["storage"] = "cursor_sqlite"
                        elif hermes_sqlite:
                            receipt["native_cleanup"]["storage"] = "hermes_sqlite"
                        elif antigravity_sqlite:
                            receipt["native_cleanup"]["storage"] = "antigravity_sqlite"
                    receipt["native_cleanup"]["accounting"] = accounting
                    ledger.save_deletion_receipt(receipt)
                    if isinstance(native, CursorCleanupPlan) and native.search_database is not None:
                        def record_witness(witness: dict) -> None:
                            staged = {**receipt, "native_cleanup": {**receipt["native_cleanup"], "cross_store": witness}}
                            ledger.save_deletion_receipt(staged)
                            receipt.update(staged)

                        native_result = apply_cursor_cross_cleanup(
                            native, data_dir=Path(backend.data_dir), receipt_id=receipt_id,
                            record_witness=record_witness, witness=recover_cross,
                        )
                    elif isinstance(native, CursorCleanupPlan):
                        native_result = apply_cursor_cleanup(native, data_dir=Path(backend.data_dir), receipt_id=receipt_id)
                    elif isinstance(native, HermesCleanupPlan):
                        native_result = apply_hermes_cleanup(native, data_dir=Path(backend.data_dir), receipt_id=receipt_id)
                        if native_result["status"] == "deleted":
                            receipt["native_cleanup"]["message_ids"] = native_result["message_ids"]
                    elif antigravity_sqlite:
                        from harness_mem.adapters.antigravity.sqlite_cleanup import AntigravityCleanupPlan, apply_antigravity_sqlite_cleanup

                        assert isinstance(native, AntigravityCleanupPlan)
                        def record_agy_witness(witness: dict) -> None:
                            staged = {**receipt, "native_cleanup": {**receipt["native_cleanup"], "antigravity": witness}}
                            ledger.save_deletion_receipt(staged)
                            receipt.update(staged)

                        native_result = apply_antigravity_sqlite_cleanup(
                            native, data_dir=Path(backend.data_dir), receipt_id=receipt_id,
                            record_witness=record_agy_witness, witness=recover_agy,
                        )
                    else:
                        assert isinstance(native, NativeCleanupPlan)
                        native_result = apply_native_source_cleanup(native)
                    accounting["result"] = {
                        "status": native_result["status"],
                        "counts": native_result.get("counts", {}),
                        "file_results": native_result.get("actions", []),
                    }
                    receipt["native_cleanup"]["status"] = native_result["status"]
                    ledger.save_deletion_receipt(receipt)
                discard_backup = (discard_cursor_cleanup_backup if cursor_sqlite
                                  else discard_hermes_cleanup_backup if hermes_sqlite else None)
                if discard_backup and native_result["status"] == "deleted" and not discard_backup(Path(backend.data_dir), receipt_id):
                    receipt["status"] = "partial_failure"
                    receipt["reason_codes"] = [f"{source.client}_cleanup_backup_retained"]
                    ledger.save_deletion_receipt(receipt)
                    outcome.update(status="partial_failure", receipt_id=receipt_id, reason_codes=receipt["reason_codes"])
                    continue
                result = asyncio.run(cleanup_processed_source(
                    backend, job_id=job.id, native_cleanup=native_result, receipt_id=receipt_id,
                    retained_handoffs=preserved["handoffs"],
                ))
                if result.get("status") == "deleted":
                    current_job = ledger.get_distill_job(job.id)
                    after_preserved, _, preserve_error = _manual_retained_outputs(backend, current_job, reference)
                    if preserve_error or after_preserved != preserved:
                        result = {**result, "status": "partial_failure",
                                  "reason_codes": [*result.get("reason_codes", []), preserve_error or "retained_outputs_changed"]}
                        receipt = next(value for value in ledger.list_deletion_audit(project_name=job.project_name)
                                       if value["id"] == receipt_id)
                        receipt["status"] = "partial_failure"
                        receipt["verification"]["passed"] = False
                        receipt["reason_codes"] = list(result["reason_codes"])
                        ledger.save_deletion_receipt(receipt)
                outcome.update({key: result[key] for key in ("status", "receipt_id", "counts", "reason_codes") if key in result})
                if result.get("status") == "deleted" and isinstance(native_result.get("counts"), dict):
                    outcome["native_counts"] = native_result["counts"]
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return {"success": False, "batch_id": batch_id, "mode": "apply" if apply else "preview",
                "status": "partial", "error": str(exc), "sessions": outcomes}
    counts = dict(Counter(value["status"] for value in outcomes))
    finished = all(value["status"] in {"deleted", "already_deleted", "skipped"} for value in outcomes)
    ready = all(value["status"] in {"ready", "already_deleted", "skipped"} for value in outcomes)
    return {"success": finished if apply else ready, "batch_id": batch_id,
            "mode": "apply" if apply else "preview", "status": "completed" if finished else "ready" if not apply and ready else "partial",
            "counts": counts, "sessions": outcomes}


def _retained_hold(manifest: dict, *, error: str) -> dict:
    """Report a pause or integrity stop without clearing its reason or selection."""

    failures = [
        {"reference_id": reference_id, "reason": reason}
        for reference_id, reason in sorted(manifest.get("failures", {}).items())
    ]
    return {
        "success": False, "batch_id": manifest["batch_id"], "status": manifest["state"],
        "state": manifest["state"], "error": error,
        "retained_reason": failures[0]["reason"] if failures else error,
        "retained_failures": failures,
    }


def prepare_manual_batch(
    backend: Any, *, project_name: str, project_root: Path | None, batch_id: str | None,
    sessions: list[dict] | None, prepare: Callable[..., dict], prepare_options: dict,
    retry_failures: bool = False, pause: bool = False, continue_batch: bool = False,
    archived_only: bool = False,
) -> dict:
    """Prepare exactly one selected job; the active Agent supplies all semantics."""
    store = ManualBatchStore(backend.data_dir)
    device_scope = project_root is None
    root_text = str(project_root) if project_root is not None else ""
    try:
        if project_root is not None and not project_root.is_absolute():
            raise ValueError("project_root must be absolute")
        if sum(bool(flag) for flag in (pause, continue_batch, retry_failures)) > 1:
            raise ValueError("pause, continue, and retry are separate actions")
        if (pause or continue_batch) and (batch_id is None or sessions is not None):
            raise ValueError("pause and continue use the existing batch_id only")
        if batch_id is not None and sessions is not None:
            raise ValueError("resume with batch_id only; frozen selection cannot be replaced")
        if retry_failures and batch_id is None:
            raise ValueError("retry_failures requires an existing batch_id")
        inventory = None
        source_issues: list[dict] = []
        if batch_id is None:
            if not sessions:
                raise ValueError("select session references before creating a batch")
            clients = sorted({str(item.get("client") or "") for item in sessions})
            # A device request freezes the selected native hints, then captures
            # and binds one complete immutable revision at a time. Legacy
            # project selections retain their already-verified v1 contract.
            inventory = collect_session_inventory(Path(backend.data_dir), project_root=project_root,
                                                  project_name=project_name, clients=clients, selected_sessions=sessions,
                                                  lightweight=device_scope and all(
                                                      str(item.get("source_revision", "")).startswith("metadata:")
                                                      for item in sessions
                                                  ), archived_only=archived_only)
            available = {key: row for row in inventory.rows
                         for key in (row.get("reference_id"), row.get("metadata_reference_id")) if key}
            selection = []
            already_completed = []
            initial_failures: dict[str, str] = {}
            for item in sessions:
                reference = session_reference(*(str(item.get(key) or "") for key in ("client", "session_id", "source_id", "source_revision")))
                row = available.get(reference["reference_id"])
                if item.get("reference_id") != reference["reference_id"]:
                    raise ValueError("selected source reference is invalid")
                if archived_only and row is None:
                    raise ValueError("selected source is not a verified archive or changed since inspection")
                if device_scope:
                    selection.append(reference)
                    if row is None:
                        initial_failures[reference["reference_id"]] = "selected_source_unavailable_or_changed"
                    elif row["processing"] == "completed":
                        already_completed.append(reference["reference_id"])
                    continue
                if (row is None
                        or row["ownership"] != "project" or row["readability"] != "readable"):
                    raise ValueError("selected source changed, unreadable, empty, or outside project")
                reference = session_reference(*(str(row[key]) for key in ("client", "session_id", "source_id", "source_revision")))
                selection.append(reference)
                if row["processing"] == "completed":
                    already_completed.append(reference["reference_id"])
            scope = {"project_name": project_name, "project_root": root_text,
                     **({"scope": "all"} if device_scope else {})}
            manifest = backend.transcript_store.freeze_manual_selection(
                lambda: store.create(project_name, root_text, selection,
                                     runtime_fingerprint=runtime_fingerprint(), already_completed=already_completed,
                                     scope="all" if device_scope else "project", archived_only=archived_only),
                matches=lambda job: any(_same_job_scope(job, scope, ref, backend.transcript_store) for ref in selection),
            )
            batch_id = manifest["batch_id"]
            for reference_id, reason in initial_failures.items():
                manifest = store.record_failure(batch_id, project_name, root_text, reference_id, reason)
            for reference in selection:
                if device_scope:
                    continue
                existing_id = available[reference["reference_id"]].get("job_id")
                if existing_id:
                    backend.transcript_store.reserve_manual_distill_job(existing_id)
                    manifest = store.bind_job(batch_id, project_name, root_text, reference["reference_id"], existing_id)
        else:
            manifest = store.load(batch_id, project_name, root_text)
        assert batch_id is not None
        if pause:
            if manifest["state"] == "stopped":
                return _retained_hold(manifest, error="batch_stopped")
            manifest = store.pause(batch_id, project_name, root_text)
            paused = inspect_manual_batch(
                Path(backend.data_dir), project_name=project_name, project_root=project_root,
                batch_id=batch_id, check_new=False,
            )
            return {**paused, "paused": True}
        if manifest["state"] == "stopped":
            return _retained_hold(manifest, error="batch_stopped")
        if continue_batch and manifest["state"] == "paused":
            manifest = store.resume_paused(batch_id, project_name, root_text)
        if manifest["state"] == "paused":
            held = inspect_manual_batch(
                Path(backend.data_dir), project_name=project_name, project_root=project_root,
                batch_id=batch_id, check_new=False,
            )
            if retry_failures:
                return {**_retained_hold(manifest, error="batch_paused"), **held, "success": False, "status": "paused"}
            return {**held, "paused": True}
        if retry_failures:
            manifest = store.retry_failures(batch_id, project_name, root_text)
        for reference in manifest["sessions"]:
            ref = reference["reference_id"]
            if ref in manifest["failures"] or ref in manifest.get("skipped", {}):
                continue
            job_id = manifest["bindings"].get(ref)
            job = backend.transcript_store.get_distill_job(job_id) if job_id else None
            if job_id and (job is None or not _same_job_scope(job, manifest, reference, backend.transcript_store)):
                store.record_failure(batch_id, project_name, root_text, ref, "job_scope_or_revision_changed", stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "job_scope_or_revision_changed"}
            if job is None:
                if device_scope:
                    inventory = collect_session_inventory(
                        Path(backend.data_dir), clients=[reference["client"]], selected_sessions=[reference],
                        archived_only=manifest.get("archived_only", False),
                    )
                elif inventory is None:
                    inventory = collect_session_inventory(Path(backend.data_dir), project_root=project_root, project_name=project_name,
                                                          clients=sorted({item["client"] for item in manifest["sessions"]}),
                                                          selected_sessions=manifest["sessions"],
                                                          archived_only=manifest.get("archived_only", False))
                row = next((row for row in inventory.rows if row.get("reference_id") == ref
                            or device_scope and row.get("metadata_reference_id") == ref), None)
                if row is None:
                    source_issues.append({
                        "reference_id": ref,
                        "returned_sources": len(inventory.rows),
                        "issues": [item.get("reason", "source_unreadable") for item in inventory.issues],
                    })
                    store.record_failure(batch_id, project_name, root_text, ref, "selected_source_unavailable_or_changed")
                    continue
                if device_scope and row["readability"] in {"empty_source", "empty_draft", "excluded"}:
                    manifest = store.record_skip(batch_id, project_name, ref, row["readability"])
                    continue
                if row.get("job_id"):
                    job = backend.transcript_store.get_distill_job(row["job_id"])
                else:
                    native = inventory.native.get(row["reference_id"])
                    if native is None or row["ownership"] not in {"project", "source"} or row["readability"] != "readable":
                        if row.get("origin") == "ledger" and row["readability"] == "readable":
                            job = backend.transcript_store.enqueue_distill_job(row["source_id"])
                        else:
                            store.record_failure(batch_id, project_name, root_text, ref, "selected_source_unreadable")
                            continue
                    if job is None and native is not None:
                        try:
                            synced = asyncio.run(persist_inspected_session(
                                backend, native, project_name=row.get("project_name", project_name),
                                project_root=row.get("project_root", root_text),
                                capture_config=native.capture_config,
                            ))
                        except (OSError, ValueError, sqlite3.Error):
                            store.record_failure(batch_id, project_name, root_text, ref, "selected_source_import_failed")
                            continue
                        job = backend.transcript_store.get_distill_job(synced.distill_job_id) if synced.distill_job_id else None
                if job is None or not _same_job_scope(job, manifest, reference, backend.transcript_store):
                    store.record_failure(batch_id, project_name, root_text, ref, "source_changed_during_import", stop_batch=True)
                    return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "source_changed_during_import"}
                manifest = store.bind_job(
                    batch_id, project_name, root_text, ref, job.id,
                    source_reference=session_reference(job.client, job.session_id, job.source_id, job.source_revision)
                    if device_scope else None,
                )
            cleaned = job.source_cleanup_status == "deleted"
            if not cleaned and job.status != "completed":
                # An archived/moved native file can have exactly the same
                # captured dialogue as an existing job. Reuse that job, but
                # still reopen the inspected native bytes through the common
                # snapshot owner: its cleanup locator, native digest and
                # author category must describe the file actually reviewed.
                def native_rows(current_inventory):
                    return [value for value in current_inventory.rows
                            if value.get("origin") == "native" and (
                                value.get("reference_id") == ref
                                or device_scope and value.get("metadata_reference_id") == ref
                                or value.get("job_id") == job.id
                                and value.get("session_id") == job.session_id
                                and value.get("client") == job.client
                                and value.get("source_revision") == job.source_revision)]

                rows = native_rows(inventory) if inventory is not None else []
                if not rows:
                    inventory = collect_session_inventory(
                        Path(backend.data_dir), project_root=project_root,
                        project_name=project_name, clients=[reference["client"]],
                        session_id=job.session_id, archived_only=manifest.get("archived_only", False),
                    )
                    rows = native_rows(inventory)
                row = rows[0] if len(rows) == 1 else None
                native = inventory.native.get(row["reference_id"]) if inventory is not None and row is not None else None
                if native is not None:
                    try:
                        refreshed = asyncio.run(persist_inspected_session(
                            backend, native, project_name=job.project_name,
                            project_root=job.project_root, capture_config=native.capture_config,
                            expected_source_id=job.source_id, expected_source_revision=job.source_revision,
                        ))
                        if (refreshed.source is None or refreshed.source.id != job.source_id
                                or refreshed.source.source_revision != job.source_revision):
                            raise ValueError("native binding changed the selected source")
                    except (OSError, ValueError, sqlite3.Error):
                        store.record_failure(batch_id, project_name, root_text, ref,
                                             "selected_native_binding_failed", stop_batch=True)
                        return {"success": False, "batch_id": batch_id, "status": "stopped",
                                "error": "selected_native_binding_failed"}
            if not cleaned:
                backend.transcript_store.release_other_manual_revisions(job)
            guard = None if cleaned else manual_job_guard(backend, job)
            if guard:
                if guard == _ARCHIVE_CHANGED:
                    manifest = store.record_failure(batch_id, project_name, root_text, ref, guard)
                    continue
                store.record_failure(batch_id, project_name, root_text, ref, guard, stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": guard}
            if not cleaned:
                job = backend.transcript_store.reserve_manual_distill_job(job.id)
                backend.transcript_store.retain_distill_source(job.id)
            entries = current_entries(Path(backend.data_dir), project_name if not device_scope else None)
            project_jobs = [value for value in backend.transcript_store.list_distill_jobs(project_name=project_name if not device_scope else None)
                            if project_root is None or normalized_root(value.project_root) == normalized_root(project_root)
                            or value.id == job.id]
            proven, superseded = completed_job_ids(project_jobs, entries)
            if job.status == "completed" and job.completion_disposition is not None and job.id not in proven:
                store.record_failure(batch_id, project_name, root_text, ref, "completed_job_needs_verification", stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "completed_job_needs_verification"}
            if job.id in proven:
                if (device_scope and job.completed_at is not None
                        and job.completed_at < datetime.fromisoformat(manifest["started_at"])):
                    manifest = store.mark_already_completed(batch_id, project_name, root_text, ref)
                from harness_mem.mcp.distill_handlers import _promotion_commit_error
                # Recheck the successor's ordinary retrieval when its turn is
                # reached; a deliberately replaced predecessor must be absent.
                current_points = []
                for point in job.promotion_summary.get("points") or []:
                    remaining_ids = [value for value in point.get("canonical_truth_ids") or [] if value not in superseded]
                    if remaining_ids and point.get("disposition") in {"add", "refine", "replace"}:
                        current_points.append({**point, "canonical_truth_ids": remaining_ids})
                error = asyncio.run(_promotion_commit_error(backend, project_name=job.project_name,
                                    promotion_summary={"promoted": len(current_points), "points": current_points}))
                if not error and any(set(point.get("canonical_truth_ids") or []).intersection(superseded)
                                     for point in job.promotion_summary.get("points") or []):
                    # Read-only successor checks prove an already-processed
                    # selected revision; they never expand the batch's writes.
                    for successor in project_jobs:
                        if successor.id not in proven or successor.id == job.id:
                            continue
                        points = []
                        for point in successor.promotion_summary.get("points") or []:
                            ids = [value for value in point.get("canonical_truth_ids") or [] if value in entries]
                            if ids and point.get("disposition") in {"add", "refine", "replace"}:
                                points.append({**point, "canonical_truth_ids": ids})
                        error = asyncio.run(_promotion_commit_error(backend, project_name=successor.project_name,
                                            promotion_summary={"promoted": len(points), "points": points}))
                        if error:
                            break
                if error:
                    store.record_failure(batch_id, project_name, root_text, ref, error, stop_batch=True)
                    return {"success": False, "batch_id": batch_id, "status": "stopped", "error": error}
                continue
            if job.status == "completed" and job.completion_disposition is None:
                from harness_mem.mcp.distill_handlers import tool_finalize_session_distill
                packet = tool_finalize_session_distill(job.project_name, job.id, job.semantic_review)
            else:
                packet = prepare(project_name=job.project_name, project_root=job.project_root or None, client=job.client,
                                 scope="all" if device_scope else "project",
                                 run_ingest=False, distill_job_id=job.id, _batch_selected=True, **prepare_options)
            progress = inspect_manual_batch(Path(backend.data_dir), project_name=project_name, project_root=project_root, batch_id=batch_id, check_new=False)
            if not packet.get("success"):
                reasons = packet.get("reason_codes") or []
                stop = any("promotion_" in str(reason) or "project" in str(reason) for reason in reasons) or job.status == "completed"
                if stop:
                    store.record_failure(batch_id, project_name, root_text, ref, "completion_verification_failed", stop_batch=True)
                elif "lease" not in str(packet.get("error") or "") and not (packet.get("distill_status") == "retryable" and packet.get("retry_after")):
                    store.record_failure(batch_id, project_name, root_text, ref, "selected_source_processing_failed")
                return {**packet, "batch_id": batch_id, "batch_progress": progress["progress"], "batch_stopped": stop}
            if packet.get("distill_status") == "completed":
                continue
            return {**packet, "batch_id": batch_id, "batch_progress": progress["progress"], "next_after_finalize": "Distill.prepare(batch_id=original_batch_id)"}
        result = inspect_manual_batch(Path(backend.data_dir), project_name=project_name, project_root=project_root, batch_id=batch_id, check_new=False)
        if source_issues:
            result["source_issues"] = source_issues
        return result
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return {"success": False, **({"batch_id": batch_id} if batch_id else {}), "error": str(exc)}
