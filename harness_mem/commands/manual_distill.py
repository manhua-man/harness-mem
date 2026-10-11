"""Frozen manual scope around existing per-session jobs, not another executor."""

from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import closing
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable

from harness_mem.adapters.source_inspection import normalized_root
from harness_mem.commands.distill_result import distill_unfinished_work, project_distill_result
from harness_mem.commands.session_inventory import (
    collect_session_inventory, completed_job_ids, current_entries, session_reference,
)
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.storage.manual_batch_store import ManualBatchStore
from harness_mem.storage.canonical_store import CanonicalStoreRuntime, canonical_store_path
from harness_mem.storage.transcript_store import TranscriptStore


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
        if (header.get("project_name") != job.project_name
                or normalized_root(header.get("project_root", "")) != normalized_root(job.project_root)):
            continue
        if job.id not in (header.get("bindings") or {}).values():
            continue
        manifest = store.load(path.stem, job.project_name, job.project_root)
        for ref, job_id in manifest["bindings"].items():
            if job_id == job.id:
                yield store, manifest, ref


def manual_job_guard(backend: Any, job: SessionDistillJob) -> str | None:
    if not job.retain_source:
        return None
    for _store, manifest, _ref in _bound_manifests(backend, job):
        if manifest["state"] == "stopped":
            return "manual_batch_stopped"
        if manifest.get("runtime_fingerprint") != runtime_fingerprint():
            return "runtime_version_changed"
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
    if not reasons.intersection(redlines) and "another project" not in str(payload.get("error") or ""):
        return
    for store, manifest, ref in _bound_manifests(backend, job):
        store.record_failure(manifest["batch_id"], job.project_name, job.project_root,
                             ref, "completion_verification_failed", stop_batch=True)


def _same_job_scope(job: SessionDistillJob, manifest: dict, reference: dict, ledger: TranscriptStore) -> bool:
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
        status = "blocked" if reason else "pending"
        if not reason and job is not None:
            status = "completed" if job.id in proven else "needs_verification" if job.status == "completed" else job.status
        statuses.append({"reference_id": ref, "status": status, **({"reason": reason} if reason else {})})
        if job is not None:
            unfinished_work.extend(distill_unfinished_work(job))
            for handoff in handoffs or []:
                bound = (handoff.get("context") or {}).get("distill_job_id")
                if (handoff.get("project_name") == manifest["project_name"]
                        and handoff.get("status") != "done"
                        and (bound == job.id or not bound and handoff.get("task_id") == job.id)):
                    unfinished_work.extend(handoff.get("next_steps") or [handoff.get("summary") or "继续处理未完成事项。"])
        if status != "completed" or job is None:
            continue
        if ref in manifest.get("already_completed", []):
            continue
        points = job.promotion_summary.get("points") or []
        result_points.extend(points)
        if not points:
            reason = "保留为未完成事项" if job.promotion_summary.get("readback", {}).get("handoff_ids") else "没有需要长期记住的内容"
            empty_reasons.append(reason)
    counts = dict(Counter(item["status"] for item in statuses))
    verified = counts.get("completed", 0)
    total = len(manifest["sessions"])
    status = "stopped" if manifest["state"] == "stopped" else "completed" if verified == total else "partial"
    result = project_distill_result(result_points, entries, empty_reasons=empty_reasons,
                                   unfinished_work=unfinished_work)
    if verified != total:
        result["organization_status"] = "partial"
    return {
        "success": True, "batch_id": manifest["batch_id"], "status": status,
        "progress": {"selected": total, "completed": verified, "remaining": total - verified, "states": counts},
        "sessions": statuses,
        **result,
    }


def inspect_manual_batch(
    data_dir: Path, *, project_name: str, project_root: Path, batch_id: str,
    check_new: bool = True,
) -> dict:
    manifest = ManualBatchStore(data_dir).load(batch_id, project_name, str(project_root))
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
            proof_jobs = [job for job in ledger.list_distill_jobs(project_name=project_name)
                          if normalized_root(job.project_root) == normalized_root(project_root)]
    handoffs: list[dict] = []
    if canonical_store_path(data_dir).is_file():
        with closing(CanonicalStoreRuntime(data_dir, read_only=True)) as store:
            handoffs = store.list_payloads("task_handoffs", project_name=project_name)
    payload = _project_batch(manifest, jobs, current_entries(data_dir, project_name), proof_jobs=proof_jobs, handoffs=handoffs)
    if manifest.get("runtime_fingerprint") != runtime_fingerprint():
        payload.update(success=False, status="stopped", error="runtime_version_changed")
    if check_new:
        inventory = collect_session_inventory(data_dir, project_root=project_root, project_name=project_name,
                                              clients=sorted({ref["client"] for ref in manifest["sessions"]}))
        frozen = {ref["reference_id"] for ref in manifest["sessions"]}
        payload["outside_batch_pending"] = sum(
            row.get("reference_id") not in frozen and row["ownership"] == "project"
            and row["processing"] not in {"completed", "skipped"}
            for row in inventory.rows
        )
    return payload


def prepare_manual_batch(
    backend: Any, *, project_name: str, project_root: Path, batch_id: str | None,
    sessions: list[dict] | None, prepare: Callable[..., dict], prepare_options: dict,
    retry_failures: bool = False,
) -> dict:
    """Prepare exactly one selected job; the active Agent supplies all semantics."""
    store = ManualBatchStore(backend.data_dir)
    try:
        if not project_root.is_absolute() or not project_root.is_dir():
            raise ValueError("project_root must be an existing absolute directory")
        if any(source.project_root and normalized_root(source.project_root) != normalized_root(project_root)
               for source in backend.transcript_store.list_sources(project_name=project_name, limit=None)):
            raise ValueError("project name is already associated with another root; use an unambiguous project name")
        if batch_id is not None and sessions is not None:
            raise ValueError("resume with batch_id only; frozen selection cannot be replaced")
        if retry_failures and batch_id is None:
            raise ValueError("retry_failures requires an existing batch_id")
        inventory = None
        if batch_id is None:
            if not sessions:
                raise ValueError("select session references before creating a batch")
            clients = sorted({str(item.get("client") or "") for item in sessions})
            inventory = collect_session_inventory(Path(backend.data_dir), project_root=project_root, project_name=project_name, clients=clients)
            available = {row.get("reference_id"): row for row in inventory.rows}
            selection = []
            already_completed = []
            for item in sessions:
                reference = session_reference(*(str(item.get(key) or "") for key in ("client", "session_id", "source_id", "source_revision")))
                row = available.get(reference["reference_id"])
                if (item.get("reference_id") != reference["reference_id"] or row is None
                        or row["ownership"] != "project" or row["readability"] != "readable"):
                    raise ValueError("selected source changed, unreadable, empty, or outside project")
                selection.append(reference)
                if row["processing"] == "completed":
                    already_completed.append(reference["reference_id"])
            scope = {"project_name": project_name, "project_root": str(project_root)}
            manifest = backend.transcript_store.freeze_manual_selection(
                lambda: store.create(project_name, str(project_root), selection,
                                     runtime_fingerprint=runtime_fingerprint(), already_completed=already_completed),
                matches=lambda job: any(_same_job_scope(job, scope, ref, backend.transcript_store) for ref in selection),
            )
            batch_id = manifest["batch_id"]
            for reference in selection:
                existing_id = available[reference["reference_id"]].get("job_id")
                if existing_id:
                    backend.transcript_store.reserve_manual_distill_job(existing_id)
                    manifest = store.bind_job(batch_id, project_name, str(project_root), reference["reference_id"], existing_id)
        else:
            manifest = store.load(batch_id, project_name, str(project_root))
        assert batch_id is not None
        if manifest["state"] == "stopped" or manifest.get("runtime_fingerprint") != runtime_fingerprint():
            return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "batch_stopped_or_runtime_changed"}
        if retry_failures:
            manifest = store.retry_failures(batch_id, project_name, str(project_root))
        for reference in manifest["sessions"]:
            ref = reference["reference_id"]
            if ref in manifest["failures"]:
                continue
            job_id = manifest["bindings"].get(ref)
            job = backend.transcript_store.get_distill_job(job_id) if job_id else None
            if job_id and (job is None or not _same_job_scope(job, manifest, reference, backend.transcript_store)):
                store.record_failure(batch_id, project_name, str(project_root), ref, "job_scope_or_revision_changed", stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "job_scope_or_revision_changed"}
            if job is None:
                if inventory is None:
                    inventory = collect_session_inventory(Path(backend.data_dir), project_root=project_root, project_name=project_name,
                                                          clients=sorted({item["client"] for item in manifest["sessions"]}))
                row = next((row for row in inventory.rows if row.get("reference_id") == ref), None)
                if row is None:
                    store.record_failure(batch_id, project_name, str(project_root), ref, "selected_source_unavailable_or_changed")
                    continue
                if row.get("job_id"):
                    job = backend.transcript_store.get_distill_job(row["job_id"])
                else:
                    native = inventory.native.get(ref)
                    if native is None or row["ownership"] != "project" or row["readability"] != "readable":
                        store.record_failure(batch_id, project_name, str(project_root), ref, "selected_source_unreadable")
                        continue
                    native.adapter.backend = backend
                    if hasattr(native.adapter, "project_root"):
                        native.adapter.project_root = project_root
                    kwargs = {"project_root": project_root} if native.client == "claude-code" else {}
                    try:
                        synced = asyncio.run(native.adapter.sync_session(native.record["path"], native.session_id, project_name, **kwargs))
                    except (OSError, ValueError, sqlite3.Error):
                        store.record_failure(batch_id, project_name, str(project_root), ref, "selected_source_import_failed")
                        continue
                    job = backend.transcript_store.get_distill_job(synced.distill_job_id) if synced.distill_job_id else None
                if job is None or not _same_job_scope(job, manifest, reference, backend.transcript_store):
                    store.record_failure(batch_id, project_name, str(project_root), ref, "source_changed_during_import", stop_batch=True)
                    return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "source_changed_during_import"}
                manifest = store.bind_job(batch_id, project_name, str(project_root), ref, job.id)
            guard = manual_job_guard(backend, job)
            if guard:
                store.record_failure(batch_id, project_name, str(project_root), ref, guard, stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": guard}
            job = backend.transcript_store.reserve_manual_distill_job(job.id)
            backend.transcript_store.retain_distill_source(job.id)
            entries = current_entries(Path(backend.data_dir), project_name)
            project_jobs = [value for value in backend.transcript_store.list_distill_jobs(project_name=project_name)
                            if normalized_root(value.project_root) == normalized_root(project_root)]
            proven, superseded = completed_job_ids(project_jobs, entries)
            if job.status == "completed" and job.completion_disposition is not None and job.id not in proven:
                store.record_failure(batch_id, project_name, str(project_root), ref, "completed_job_needs_verification", stop_batch=True)
                return {"success": False, "batch_id": batch_id, "status": "stopped", "error": "completed_job_needs_verification"}
            if job.id in proven:
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
                        error = asyncio.run(_promotion_commit_error(backend, project_name=project_name,
                                            promotion_summary={"promoted": len(points), "points": points}))
                        if error:
                            break
                if error:
                    store.record_failure(batch_id, project_name, str(project_root), ref, error, stop_batch=True)
                    return {"success": False, "batch_id": batch_id, "status": "stopped", "error": error}
                continue
            if job.status == "completed" and job.completion_disposition is None:
                from harness_mem.mcp.distill_handlers import tool_finalize_session_distill
                packet = tool_finalize_session_distill(project_name, job.id, job.semantic_review)
            else:
                packet = prepare(project_name=project_name, project_root=str(project_root), client=reference["client"],
                                 run_ingest=False, distill_job_id=job.id, _batch_selected=True, **prepare_options)
            progress = inspect_manual_batch(Path(backend.data_dir), project_name=project_name, project_root=project_root, batch_id=batch_id, check_new=False)
            if not packet.get("success"):
                reasons = packet.get("reason_codes") or []
                stop = any("promotion_" in str(reason) or "project" in str(reason) for reason in reasons) or job.status == "completed"
                if stop:
                    store.record_failure(batch_id, project_name, str(project_root), ref, "completion_verification_failed", stop_batch=True)
                elif "lease" not in str(packet.get("error") or "") and not (packet.get("distill_status") == "retryable" and packet.get("retry_after")):
                    store.record_failure(batch_id, project_name, str(project_root), ref, "selected_source_processing_failed")
                return {**packet, "batch_id": batch_id, "batch_progress": progress["progress"], "batch_stopped": stop}
            if packet.get("distill_status") == "completed":
                continue
            return {**packet, "batch_id": batch_id, "batch_progress": progress["progress"], "next_after_finalize": "prepare_session_distill with this batch_id"}
        return inspect_manual_batch(Path(backend.data_dir), project_name=project_name, project_root=project_root, batch_id=batch_id, check_new=False)
    except (OSError, ValueError, KeyError, sqlite3.Error) as exc:
        return {"success": False, **({"batch_id": batch_id} if batch_id else {}), "error": str(exc)}
