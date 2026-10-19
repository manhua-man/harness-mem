"""Coalesce each session's events behind one detached worker per project."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator
from uuid import uuid4

from harness_mem.diagnostic_events import DEBUG_PARENT_RUN_ID_ENV, diagnostic_parent_id

__all__ = [
    "BACKGROUND_WORKER_ENV",
    "BackgroundDispatch",
    "BackgroundRequest",
    "background_generation_from_env",
    "dispatch_post_turn",
    "finish_background_worker",
    "heartbeat_background_worker",
    "keep_background_worker_alive",
    "load_background_request",
    "record_background_activity",
    "wait_for_background_request",
    "background_request_cancelled",
]

BACKGROUND_WORKER_ENV = "HARNESS_MEM_HOOK_BACKGROUND_WORKER"
_BACKGROUND_GENERATION_ENV = "HARNESS_MEM_HOOK_BACKGROUND_GENERATION"
_BACKGROUND_LEASE_ENV = "HARNESS_MEM_HOOK_BACKGROUND_LEASE"
_DEBUG_PARENT_ENV = DEBUG_PARENT_RUN_ID_ENV
_LOCK_STALE_SECONDS = 300.0
# These hosts provide a native per-user-turn event, so a new question can
# cancel the previous reply's pending idle window without guessing activity.
_IDLE_CLIENTS = frozenset({"codex", "antigravity"})
POST_TURN_IDLE_SECONDS = 30.0
_Popen = Callable[..., subprocess.Popen[Any]]
# Only the immutable files observed by this process before processing may be
# retired together. A concurrent dispatch must always survive that retirement.
_loaded_requests: dict[tuple[Path, str], tuple[Path, ...]] = {}


@dataclass(frozen=True)
class BackgroundRequest:
    """One post-turn request, coalesced only with the same native session."""

    generation: str
    project_root: str
    client: str
    source: str
    trigger_id: str | None
    requested_at: float
    native_transcript_path: str | None = None


@dataclass(frozen=True)
class BackgroundDispatch:
    """Foreground dispatch result returned to a synchronous IDE hook."""

    spawned: bool
    coalesced: bool
    generation: str


def dispatch_post_turn(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    source: str,
    trigger_id: str | None,
    native_transcript_path: str | None = None,
    popen: _Popen = subprocess.Popen,
    now: float | None = None,
) -> BackgroundDispatch:
    """Persist an immutable request and ensure one worker lease is held."""

    requested_at = time.time() if now is None else now
    request = BackgroundRequest(
        generation=str(uuid4()),
        project_root=str(project_root.expanduser().resolve()),
        client=client,
        source=source,
        trigger_id=trigger_id,
        requested_at=requested_at,
        native_transcript_path=native_transcript_path,
    )
    request_path, lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    _write_request(_pending_path(request_path, request.generation), request)
    if not _acquire_lock(lock_path, now=requested_at, owner_generation=request.generation):
        return BackgroundDispatch(
            spawned=False,
            coalesced=True,
            generation=request.generation,
        )
    try:
        _spawn_worker(request, popen=popen)
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return BackgroundDispatch(
        spawned=True,
        coalesced=False,
        generation=request.generation,
    )


def load_background_request(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    ready_only: bool = False,
    now: float | None = None,
) -> BackgroundRequest | None:
    """Serve the oldest waiting session, using its latest complete trigger."""

    request_path, _lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    requests = _pending_requests(request_path, project_root=project_root, client=client)
    if not requests:
        return None
    if ready_only and client in _IDLE_CLIENTS:
        timestamp = time.time() if now is None else now
        latest_by_session: dict[tuple[str, str], BackgroundRequest] = {}
        for _path, item in requests:
            key = _session_key(item)
            previous = latest_by_session.get(key)
            if previous is None or _request_order(item) > _request_order(previous):
                latest_by_session[key] = item
        eligible = {
            key for key, item in latest_by_session.items()
            if timestamp >= item.requested_at + POST_TURN_IDLE_SECONDS
            or background_request_cancelled(data_dir, item)
        }
        requests = [(path, item) for path, item in requests if _session_key(item) in eligible]
        if not requests:
            return None
    # A busy session cannot replace another session's request or move ahead of
    # its older waiting trigger. Unknown session identities never coalesce.
    oldest = min(requests, key=lambda item: _request_order(item[1]))[1]
    session = _session_key(oldest)
    selected = [(path, item) for path, item in requests if _session_key(item) == session]
    latest = max(selected, key=lambda item: _request_order(item[1]))[1]
    _loaded_requests.setdefault(
        (request_path, latest.generation), tuple(path for path, _item in selected)
    )
    return latest


def _activity_path(request_path: Path, session_id: str) -> Path:
    identity = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    return request_path.with_name(f"{request_path.stem}.activity-{identity}.json")


def record_background_activity(
    data_dir: Path, *, project_root: Path, client: str,
    session_id: str | None, now: float | None = None,
) -> None:
    """Cancel only this session's earlier idle window on a native user turn.

    A later Stop still queues the complete source through the same worker.
    This current activity marker contains no prompt or transcript content.
    """
    if client not in _IDLE_CLIENTS or not session_id:
        return
    request_path, _lock_path = _state_paths(data_dir, project_root=project_root, client=client)
    target = _activity_path(request_path, session_id)
    temporary = target.with_name(f".{target.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps({"active_at": time.time() if now is None else now}) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, target)


def background_request_cancelled(data_dir: Path, request: BackgroundRequest) -> bool:
    if request.client not in _IDLE_CLIENTS or not request.trigger_id:
        return False
    request_path, _lock_path = _state_paths(
        data_dir, project_root=Path(request.project_root), client=request.client,
    )
    try:
        payload = json.loads(_activity_path(request_path, request.trigger_id).read_text(encoding="utf-8"))
        active_at = float(payload["active_at"])
    except (OSError, ValueError, TypeError, KeyError):
        return False
    return active_at > request.requested_at


def wait_for_background_request(
    data_dir: Path, *, project_root: Path, client: str,
) -> BackgroundRequest | None:
    """Wait inside the existing detached owner, never inside the user's turn.

    Re-read the queue so a newer Stop resets its session's timer, and another
    ready session can proceed while a busy session is still in its idle window.
    Cancelled requests are returned for retirement without semantic processing.
    """
    while True:
        request = load_background_request(
            data_dir, project_root=project_root, client=client, ready_only=True,
        )
        if request is not None:
            return request
        request_path, _lock_path = _state_paths(data_dir, project_root=project_root, client=client)
        if not _pending_requests(request_path, project_root=project_root, client=client):
            return None
        heartbeat_background_worker(data_dir, project_root=project_root, client=client)
        time.sleep(0.5)


def _read_request(path: Path, *, project_root: Path, client: str) -> BackgroundRequest | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        request = BackgroundRequest(
            generation=str(payload["generation"]),
            project_root=str(payload["project_root"]),
            client=str(payload["client"]),
            source=str(payload["source"]),
            trigger_id=(
                str(payload["trigger_id"])
                if payload.get("trigger_id") is not None
                else None
            ),
            requested_at=float(payload["requested_at"]),
            native_transcript_path=(str(payload["native_transcript_path"])
                                    if payload.get("native_transcript_path") else None),
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    expected_root = str(project_root.expanduser().resolve())
    if request.project_root != expected_root or request.client != client:
        return None
    return request


def _request_order(request: BackgroundRequest) -> tuple[float, str]:
    return request.requested_at, request.generation


def _session_key(request: BackgroundRequest) -> tuple[str, str]:
    identity = request.trigger_id
    if not identity or identity in {"codex-stop", "antigravity-stop", "hermes-post-llm"}:
        # These adapter defaults do not identify a native conversation.
        identity = request.generation
    return request.source, identity


def _pending_path(request_path: Path, generation: str) -> Path:
    # Hash even legacy identifiers rather than treating persisted text as a path.
    identity = hashlib.sha256(generation.encode("utf-8")).hexdigest()
    return request_path.with_name(f"{request_path.stem}.pending-{identity}.json")


def _pending_requests(
    request_path: Path, *, project_root: Path, client: str
) -> list[tuple[Path, BackgroundRequest]]:
    # Move the legacy mutable slot atomically before reading it. A concurrent
    # legacy writer can recreate the base slot; we never unlink that newer file.
    legacy = request_path.with_name(f"{request_path.stem}.pending-legacy-{uuid4().hex}.json")
    try:
        request_path.rename(legacy)
    except FileNotFoundError:
        pass
    pending = []
    for path in request_path.parent.glob(f"{request_path.stem}.pending-*.json"):
        request = _read_request(path, project_root=project_root, client=client)
        if request is not None:
            pending.append((path, request))
    return pending


def finish_background_worker(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    processed_generation: str | None,
    popen: _Popen = subprocess.Popen,
) -> bool:
    """Release the worker lease and hand off a request that arrived meanwhile."""

    request_path, lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    if not _lease_matches(lock_path):
        return False
    # Retire a closed snapshot, not a timestamp range: a newly persisted trigger
    # may carry an earlier timestamp because dispatch began before this worker.
    paths = _loaded_requests.pop((request_path, processed_generation or ""), ())
    if not paths and processed_generation is not None:
        # Preserve direct/older callers that finish without first loading here.
        paths = tuple(
            path
            for path, item in _pending_requests(
                request_path, project_root=project_root, client=client
            )
            if item.generation == processed_generation
        )
    for path in paths:
        path.unlink(missing_ok=True)
    lock_path.unlink(missing_ok=True)
    latest = load_background_request(
        data_dir,
        project_root=project_root,
        client=client,
    )
    if latest is None:
        return False
    if not _acquire_lock(lock_path, now=time.time(), owner_generation=latest.generation):
        return False
    try:
        _spawn_worker(latest, popen=popen)
    except Exception:
        lock_path.unlink(missing_ok=True)
        raise
    return True


def heartbeat_background_worker(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    now: float | None = None,
) -> bool:
    """Renew the detached-worker lock while semantic processing is active."""

    _request_path, lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    if not lock_path.is_file() or not _lease_matches(lock_path):
        return False
    timestamp = time.time() if now is None else float(now)
    try:
        os.utime(lock_path, (timestamp, timestamp))
    except OSError:
        return False
    return True


@contextmanager
def keep_background_worker_alive(
    data_dir: Path, *, project_root: Path, client: str,
) -> Iterator[None]:
    """Keep the existing worker lease alive through source I/O and all Dream slices."""
    stop = threading.Event()

    def renew() -> None:
        while not stop.wait(15.0):
            if not heartbeat_background_worker(data_dir, project_root=project_root, client=client):
                return

    heartbeat_background_worker(data_dir, project_root=project_root, client=client)
    thread = threading.Thread(target=renew, name="hm-background-lease", daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()
        thread.join(timeout=1.0)


def _state_paths(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
) -> tuple[Path, Path]:
    root = str(project_root.expanduser().resolve())
    key = hashlib.sha256(f"{client}\0{root}".encode("utf-8")).hexdigest()[:24]
    state_dir = Path(data_dir) / "hook_runtime" / "background"
    state_dir.mkdir(parents=True, exist_ok=True)
    return state_dir / f"{client}-{key}.json", state_dir / f"{client}-{key}.lock"


def _write_request(path: Path, request: BackgroundRequest) -> None:
    payload = {
        "generation": request.generation,
        "project_root": request.project_root,
        "client": request.client,
        "source": request.source,
        "trigger_id": request.trigger_id,
        "requested_at": request.requested_at,
        "native_transcript_path": request.native_transcript_path,
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _lease_matches(path: Path) -> bool:
    expected = os.environ.get(_BACKGROUND_LEASE_ENV)
    if not expected:
        return True  # Existing launchers have no lease token.
    try:
        payload = json.loads(path.read_text(encoding="ascii"))
        return isinstance(payload, dict) and payload.get("generation") == expected
    except (OSError, ValueError, TypeError):
        return False


def _acquire_lock(path: Path, *, now: float, owner_generation: str | None = None) -> bool:
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        try:
            stale = now - path.stat().st_mtime > _LOCK_STALE_SECONDS
        except OSError:
            return False
        if not stale:
            return False
        try:
            path.unlink()
        except OSError:
            return False
        try:
            descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            return False
    with os.fdopen(descriptor, "w", encoding="ascii") as handle:
        handle.write(json.dumps({"pid": os.getpid(), "generation": owner_generation}) + "\n")
    return True


def _spawn_worker(request: BackgroundRequest, *, popen: _Popen) -> None:
    command = [
        sys.executable,
        "-m",
        "harness_mem.host_entry.__main__",
        "--action",
        "post-turn-maintenance",
        "--project-root",
        request.project_root,
        "--source",
        request.source,
        "--client",
        request.client,
    ]
    if request.trigger_id:
        command.extend(("--trigger-id", request.trigger_id))
    env = os.environ.copy()
    env[BACKGROUND_WORKER_ENV] = "1"
    env[_BACKGROUND_GENERATION_ENV] = request.generation
    env[_BACKGROUND_LEASE_ENV] = request.generation
    parent_run_id = diagnostic_parent_id()
    if parent_run_id:
        env[_DEBUG_PARENT_ENV] = parent_run_id
    kwargs: dict[str, Any] = {
        "cwd": request.project_root,
        "env": env,
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        )
    else:
        kwargs["start_new_session"] = True
    popen(command, **kwargs)


def background_generation_from_env() -> str | None:
    value = os.environ.get(_BACKGROUND_GENERATION_ENV)
    return value.strip() if value and value.strip() else None
