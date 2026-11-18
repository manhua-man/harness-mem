"""Wake-to-existing-worker recovery; all sources, queues and usage are isolated."""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import time
from types import SimpleNamespace as NS

import pytest

from harness_mem.commands import dream_continuation as recovery
from harness_mem.config.merge import MergedConfig
from harness_mem.autonomous.executors.task_budget import task_budget_receipt_path
from harness_mem import hook_background as queue


@pytest.fixture
def bound(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    root.mkdir()
    config = MergedConfig(distill_autonomous_enabled=True)
    raw = b"[user] Keep the complete durable source and its evidence limits."
    digest = hashlib.sha256(raw).hexdigest()
    revision = NS(
        source_id="source",
        source_revision="sha256:" + digest,
        project_name=root.name,
        project_root=str(root),
        client="codex",
        session_id="original-session",
        coverage="complete",
        raw_sha256=digest,
        raw_size_bytes=len(raw),
        normalized_sha256=digest,
        normalized_size_bytes=len(raw),
        chunk_count=1,
    )
    source = NS(**{**vars(revision), "id": "source", "status": "synced"})
    job = NS(
        id="source-job",
        project_name=root.name,
        project_root=str(root),
        client="codex",
        session_id="original-session",
        status="completed",
        source_id="source",
        source_revision=revision.source_revision,
    )
    run = NS(
        id="original-run",
        project_name=root.name,
        status="continuing",
        notes=["Hook session distill verified: source-job"],
        continuation={
            "version": "dream-slices-v3",
            "slice_count": 2,
            "max_slices": 4,
            "maintenance_scope": {
                "trigger_id": "original-session",
                "dispatch_generation": "original-generation",
            },
            "completed_signal_indexes": [0],
            "target_ids": ["old", "remaining"],
        },
    )

    async def get_run(rid):
        return run if rid == run.id else None

    async def list_runs(project_name, limit):
        return [run] if project_name == run.project_name else []

    backend = NS(
        data_dir=tmp_path / "data",
        structured_store=NS(get_dream_run=get_run, list_dream_runs=list_runs),
        transcript_store=NS(
            get_distill_job=lambda jid: job if jid == job.id else None,
            get_source=lambda sid: source if sid == "source" else None,
            get_revision=lambda *_: revision,
            reconstruct_raw=lambda *_args, **_kwargs: raw,
            reconstruct=lambda *_args, **_kwargs: raw.decode(),
            list_chunks=lambda *_args, **_kwargs: [revision],
        ),
        reflection_job_store=NS(list=lambda **_: []),
    )
    receipt = {
        "schema_version": 1,
        "kind": "task_model_budget",
        "task_scope": "maintenance:original-session:original-generation",
        "host_client": "codex",
        "bounds": {
            key: getattr(config, "task_model_budget_" + key)
            for key in (
                "max_calls",
                "max_seconds",
                "max_input_tokens",
                "max_output_tokens",
                "host_max_output_tokens",
            )
        },
        "calls": [
            {
                "call_id": "source-call",
                "phase": "source",
                "slice_id": "source-decide:source-job",
                "status": "completed",
                "usage_exact": True,
                "usage": {
                    "input_tokens": 101,
                    "output_tokens": 17,
                    "duration_seconds": 2.5,
                },
            }
        ],
    }
    path = task_budget_receipt_path(backend.data_dir, receipt["task_scope"])

    def persist():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(receipt), encoding="utf-8")

    persist()
    spawned = []
    original_dispatch = queue.dispatch_bound_continuation
    monkeypatch.setattr(
        queue,
        "dispatch_bound_continuation",
        lambda *args, **kwargs: original_dispatch(
            *args, **kwargs, popen=lambda *a, **k: spawned.append((a, k))
        ),
    )
    return NS(
        root=root,
        backend=backend,
        config=config,
        run=run,
        job=job,
        source=source,
        revision=revision,
        receipt=receipt,
        path=path,
        persist=persist,
        spawned=spawned,
    )


def enqueue(bound, **kwargs):
    return asyncio.run(
        recovery.enqueue_bound_continuation(
            bound.backend,
            project_name=bound.run.project_name,
            project_root=str(bound.root),
            config=kwargs.get("config", bound.config),
            host_client=kwargs.get("host_client", "codex"),
        )
    )


def test_native_wake_queues_original_account_then_resume_skips_source(
    bound, monkeypatch
):
    import harness_mem.host_entry.__main__ as host
    import harness_mem.storage.local_memory_backend as backend_module
    import harness_mem.commands.wake as wake
    import harness_mem.commands.dream as dream
    import harness_mem.autonomous.worker as worker
    from harness_mem.commands.maintenance import run_post_turn_maintenance

    async def noop(*_args, **_kwargs):
        return None

    async def fake_wake(*_args, **_kwargs):
        return "normal recall remains available"

    bound.backend.init = noop
    bound.backend.close = noop
    monkeypatch.setattr(backend_module, "DEFAULT_DATA_DIR", bound.backend.data_dir)
    monkeypatch.setattr(backend_module, "LocalMemoryBackend", lambda _: bound.backend)
    monkeypatch.setattr(host, "load_merged_config", lambda _: bound.config)
    monkeypatch.setattr(host, "ensure_project_profile", noop)
    monkeypatch.setattr(wake, "build_wake_injection", fake_wake)
    args = argparse.Namespace(
        action="wake-start",
        project_root=str(bound.root),
        source="ide_hook",
        trigger_id="new-wake",
        client="codex",
        current_task="continue normal work",
    )
    code, text = asyncio.run(host.run(args))
    assert code == 0 and text == "normal recall remains available"
    assert len(bound.spawned) == 1
    # Another wake reuses the immutable request and existing lease.
    assert enqueue(bound)["coalesced"] is True
    assert len(bound.spawned) == 1
    request = queue.load_background_request(
        bound.backend.data_dir,
        project_root=bound.root,
        client="codex",
        ready_only=True,
        now=0,
    )
    assert request.resume_run_id == "original-run"
    assert (
        request.generation == "original-generation"
        and request.trigger_id == "original-session"
    )
    assert queue.background_request_cancelled(bound.backend.data_dir, request) is False
    before = bound.path.read_bytes()
    calls = []

    async def fake_dream(_backend, **kwargs):
        calls.append(kwargs)
        assert kwargs["trigger_job_id"] is None
        assert kwargs["resume_run_id"] == "original-run"
        assert kwargs["trigger_id"] == "original-session"
        assert kwargs["host_client"] == "codex"
        assert bound.run.continuation["completed_signal_indexes"] == [0]
        bound.run.status = "completed"
        return {"status": "completed", "run_id": "original-run"}

    def forbidden(*_args, **_kwargs):
        raise AssertionError("resume must never prepare or process source")

    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", request.generation)
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_LEASE", request.generation)
    monkeypatch.setattr(dream, "dream_auto_tick", fake_dream)
    monkeypatch.setattr(worker, "run_autonomous_distill_batch", forbidden)
    monkeypatch.setattr(
        "harness_mem.mcp.tool_handlers.tool_prepare_session_distill", forbidden
    )
    monkeypatch.setattr(
        worker, "record_post_turn_maintenance_outcome", lambda *_a, **_k: None
    )
    result = asyncio.run(
        run_post_turn_maintenance(
            bound.backend,
            project_name=bound.run.project_name,
            project_root=str(bound.root),
            config=bound.config,
            source="ide_hook",
            trigger_id=request.trigger_id,
            resume_run_id=request.resume_run_id,
            host_client=request.client,
        )
    )
    assert result["success"] is True and len(calls) == 1
    assert bound.path.read_bytes() == before  # The fake call cannot reset the ledger.
    assert result["evidence_packet"] is None and result["distill_job"] is None


@pytest.mark.parametrize(
    "fault,reason",
    [
        ("disabled", "continuation_not_authorized"),
        ("wrong_host", "continuation_account_mismatch"),
        ("wrong_root", "continuation_source_scope_mismatch"),
        ("terminal", "no_current_continuation"),
        ("missing_scope", "continuation_account_missing"),
        ("wrong_scope", "continuation_account_mismatch"),
        ("bounds", "continuation_bounds_changed"),
        ("unknown", "continuation_usage_unknown_or_active"),
        ("reserved", "continuation_usage_unknown_or_active"),
        ("missing_ledger", "continuation_account_mismatch"),
        ("missing_source", "source_report_source_missing"),
        ("digest", "source_report_source_digest_changed"),
        ("source_job", "continuation_source_binding_missing"),
        ("job_session", "continuation_source_scope_mismatch"),
        ("job_unfinished", "continuation_source_scope_mismatch"),
        ("active", "continuation_processing_active"),
        ("slices", "continuation_slices_exhausted"),
        ("budget", "continuation_budget_exhausted"),
        ("duplicate_call", "continuation_call_identity_invalid"),
    ],
)
def test_wake_recovery_refuses_without_dispatch(bound, fault, reason):
    options = {}
    if fault == "disabled":
        options["config"] = replace(bound.config, distill_autonomous_enabled=False)
    elif fault == "wrong_host":
        bound.receipt["host_client"] = "hermes"
    elif fault == "wrong_root":
        bound.job.project_root += "other"
    elif fault == "terminal":
        bound.run.status = "completed"
    elif fault == "missing_scope":
        bound.run.continuation.pop("maintenance_scope")
    elif fault == "wrong_scope":
        bound.receipt["task_scope"] = "wrong-scope"
    elif fault == "bounds":
        bound.receipt["bounds"]["max_calls"] += 1
    elif fault in {"unknown", "reserved"}:
        bound.receipt["calls"][0]["status"] = fault
    elif fault == "missing_source":
        bound.backend.transcript_store.get_source = lambda _: None
    elif fault == "digest":
        bound.backend.transcript_store.reconstruct_raw = lambda *_a, **_k: b"tampered"
    elif fault == "source_job":
        bound.run.notes = ["Hook session distill verified: unrelated"]
    elif fault == "job_session":
        bound.job.session_id = "different-session"
    elif fault == "job_unfinished":
        bound.job.status = "retryable"
    elif fault == "active":
        bound.backend.reflection_job_store.list = lambda **_: [
            NS(updated_at=datetime.now(timezone.utc))
        ]
    elif fault == "slices":
        bound.run.continuation["slice_count"] = 4
    elif fault == "budget":
        bound.receipt["calls"][0]["usage"]["output_tokens"] = 128000
    elif fault == "duplicate_call":
        bound.receipt["calls"].append(bound.receipt["calls"][0].copy())
    bound.persist()
    if fault == "missing_ledger":
        bound.path.unlink()
    result = enqueue(bound, **options)
    assert result["status"] == "skipped" and result["reason"] == reason
    assert not bound.spawned


@pytest.mark.parametrize("pointer", [None, "", 7, {}, []])
def test_invalid_persisted_resume_pointer_cannot_become_intake(bound, pointer):
    assert enqueue(bound)["spawned"]
    pending = next(
        (bound.backend.data_dir / "hook_runtime" / "background").glob(
            "*.pending-*.json"
        )
    )
    payload = json.loads(pending.read_text())
    payload["resume_run_id"] = pointer
    pending.write_text(json.dumps(payload))
    assert (
        queue.load_background_request(
            bound.backend.data_dir, project_root=bound.root, client="codex"
        )
        is None
    )


def test_deleted_resume_pointer_cannot_become_intake(bound):
    assert enqueue(bound)["spawned"]
    pending = next(
        (bound.backend.data_dir / "hook_runtime" / "background").glob(
            "*.pending-*.json"
        )
    )
    assert ".pending-resume-" in pending.name
    payload = json.loads(pending.read_text())
    del payload["resume_run_id"]
    pending.write_text(json.dumps(payload))
    assert (
        queue.load_background_request(
            bound.backend.data_dir, project_root=bound.root, client="codex"
        )
        is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("resume_run_id", "unknown-run"),
        ("trigger_id", "wrong-session"),
        ("generation", "wrong-generation"),
    ],
)
def test_detached_revalidation_refuses_tampered_queue(bound, monkeypatch, field, value):
    from harness_mem.commands.maintenance import run_post_turn_maintenance

    args = dict(resume_run_id=bound.run.id, trigger_id="original-session")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    if field == "generation":
        monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", value)
    else:
        args[field] = value
    result = asyncio.run(
        run_post_turn_maintenance(
            bound.backend,
            project_name=bound.run.project_name,
            project_root=str(bound.root),
            config=bound.config,
            host_client="codex",
            **args,
        )
    )
    assert result["status"] == "failed" and result["evidence_packet"] is None


def test_resume_queue_does_not_coalesce_with_new_intake(bound):
    enqueue(bound)
    queue.dispatch_post_turn(
        bound.backend.data_dir,
        project_root=bound.root,
        client="codex",
        source="ide_hook",
        trigger_id="original-session",
        popen=lambda *_a, **_k: None,
    )
    request_path, _ = queue._state_paths(
        bound.backend.data_dir, project_root=bound.root, client="codex"
    )
    requests = queue._pending_requests(
        request_path, project_root=bound.root, client="codex"
    )
    assert len(requests) == 2
    assert len({queue._session_key(request) for _, request in requests}) == 2


def test_resume_respects_live_owner_even_with_overdue_heartbeat(bound):
    _request_path, lock = queue._state_paths(
        bound.backend.data_dir, project_root=bound.root, client="codex"
    )
    lock.write_text(json.dumps({"pid": os.getpid(), "generation": "existing-owner"}))
    os.utime(lock, (time.time() - 1000, time.time() - 1000))
    before = lock.read_bytes()
    result = enqueue(bound)
    assert result["coalesced"] is True and not bound.spawned
    assert lock.read_bytes() == before
    pending = queue.load_background_request(
        bound.backend.data_dir, project_root=bound.root, client="codex"
    )
    assert pending.resume_run_id == "original-run"


@pytest.mark.parametrize(
    "fault", ["disabled", "unknown", "source", "superseded", "active", "lease"]
)
def test_worker_rechecks_after_valid_enqueue_without_intake(bound, monkeypatch, fault):
    import harness_mem.commands.dream as dream
    from harness_mem.commands.maintenance import run_post_turn_maintenance

    assert enqueue(bound)["spawned"]
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_WORKER", "1")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", "original-generation")
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_LEASE", "original-generation")
    config = bound.config
    if fault == "disabled":
        config = replace(config, distill_autonomous_enabled=False)
    elif fault == "unknown":
        bound.receipt["calls"][0]["usage_exact"] = False
        bound.persist()
    elif fault == "source":
        bound.backend.transcript_store.get_source = lambda _: None
    elif fault == "superseded":

        async def newer(*_a, **_k):
            return [NS(id="new-run", status="continuing")]

        bound.backend.structured_store.list_dream_runs = newer
    elif fault == "active":
        bound.backend.reflection_job_store.list = lambda **_: [
            NS(updated_at=datetime.now(timezone.utc))
        ]
    elif fault == "lease":
        _, lock = queue._state_paths(
            bound.backend.data_dir, project_root=bound.root, client="codex"
        )
        lock.write_text(json.dumps({"generation": "different-owner"}))

    async def forbidden(*_a, **_k):
        raise AssertionError("refused worker must not call any Dream/model owner")

    monkeypatch.setattr(dream, "dream_auto_tick", forbidden)
    result = asyncio.run(
        run_post_turn_maintenance(
            bound.backend,
            project_name=bound.run.project_name,
            project_root=str(bound.root),
            config=config,
            host_client="codex",
            trigger_id="original-session",
            resume_run_id="original-run",
        )
    )
    assert result["status"] == "failed" and result["evidence_packet"] is None


def test_existing_worker_handoff_preserves_pending_intake_and_resume(
    bound, monkeypatch
):
    # An ordinary intake owner is already running when a wake requests recovery.
    first = queue.dispatch_post_turn(
        bound.backend.data_dir,
        project_root=bound.root,
        client="codex",
        source="ide_hook",
        trigger_id="different-session",
        popen=lambda *_a, **_k: None,
        now=1,
    )
    loaded = queue.load_background_request(
        bound.backend.data_dir, project_root=bound.root, client="codex"
    )
    assert loaded.generation == first.generation
    assert enqueue(bound)["coalesced"]
    handoffs = []
    monkeypatch.setenv("HARNESS_MEM_HOOK_BACKGROUND_LEASE", first.generation)
    assert queue.finish_background_worker(
        bound.backend.data_dir,
        project_root=bound.root,
        client="codex",
        processed_generation=loaded.generation,
        popen=lambda *args, **kwargs: handoffs.append((args, kwargs)),
    )
    assert len(handoffs) == 1
    recovered = queue.load_background_request(
        bound.backend.data_dir, project_root=bound.root, client="codex"
    )
    assert (
        recovered.resume_run_id == "original-run"
        and recovered.generation == "original-generation"
    )


@pytest.mark.parametrize("coverage", [True, False])
def test_known_coverage_usage_keeps_original_source_authority(bound, coverage):
    additional = {
        **bound.receipt["calls"][0],
        "call_id": "coverage-call",
        "slice_id": ("source-coverage-decide:" if coverage else "source-decide:")
        + "other-job",
    }
    bound.receipt["calls"].append(additional)
    bound.persist()
    before = bound.path.read_bytes()
    result = enqueue(bound)
    assert result["status"] == ("queued" if coverage else "skipped")
    if not coverage:
        assert result["reason"] == "continuation_source_binding_missing"
    assert bound.path.read_bytes() == before


def test_dream_coverage_account_tag_preserves_original_source_binding(bound):
    bound.receipt["calls"].append(
        {
            **bound.receipt["calls"][0],
            "call_id": "coverage-call",
            "phase": "dream",
            "slice_id": "source-coverage:original-run:hash:decide",
        }
    )
    bound.persist()
    assert enqueue(bound)["status"] == "queued"


@pytest.mark.parametrize(
    "fresh,kind", [(True, "dream"), (False, "dream"), (True, "other")]
)
def test_reflection_preflight_matches_existing_atomic_claim(bound, fresh, kind):
    job = NS(
        kind=kind,
        status="processing",
        updated_at=datetime.now(timezone.utc)
        - timedelta(
            seconds=0 if fresh else bound.config.dream_auto_max_runtime_seconds + 60
        ),
    )
    queries = []

    def jobs(**kwargs):
        queries.append(kwargs)
        return [job] if kwargs.get("kind") == kind else []

    bound.backend.reflection_job_store.list = jobs
    result = enqueue(bound)
    assert queries[0]["kind"] == "dream"
    assert result["status"] == ("skipped" if fresh and kind == "dream" else "queued")
