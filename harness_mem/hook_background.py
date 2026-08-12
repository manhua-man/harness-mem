"""Coalesce IDE maintenance events behind one detached worker per project."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

__all__ = [
    "BACKGROUND_WORKER_ENV",
    "BackgroundDispatch",
    "BackgroundRequest",
    "background_generation_from_env",
    "dispatch_post_turn",
    "finish_background_worker",
    "heartbeat_background_worker",
    "load_background_request",
]

BACKGROUND_WORKER_ENV = "HARNESS_MEM_HOOK_BACKGROUND_WORKER"
_BACKGROUND_GENERATION_ENV = "HARNESS_MEM_HOOK_BACKGROUND_GENERATION"
_LOCK_STALE_SECONDS = 300.0
_Popen = Callable[..., subprocess.Popen[Any]]


@dataclass(frozen=True)
class BackgroundRequest:
    """Latest coalesced post-turn request for one host and project."""

    generation: str
    project_root: str
    client: str
    source: str
    trigger_id: str | None
    requested_at: float


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
    popen: _Popen = subprocess.Popen,
    now: float | None = None,
) -> BackgroundDispatch:
    """Persist the latest request and ensure exactly one worker is running."""

    requested_at = time.time() if now is None else now
    request = BackgroundRequest(
        generation=str(uuid4()),
        project_root=str(project_root.expanduser().resolve()),
        client=client,
        source=source,
        trigger_id=trigger_id,
        requested_at=requested_at,
    )
    request_path, lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    _write_request(request_path, request)
    if not _acquire_lock(lock_path, now=requested_at):
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
) -> BackgroundRequest | None:
    """Load the latest valid request for a worker before it starts."""

    request_path, _lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    try:
        payload = json.loads(request_path.read_text(encoding="utf-8"))
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
        )
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    expected_root = str(project_root.expanduser().resolve())
    if request.project_root != expected_root or request.client != client:
        return None
    return request


def finish_background_worker(
    data_dir: Path,
    *,
    project_root: Path,
    client: str,
    processed_generation: str | None,
    popen: _Popen = subprocess.Popen,
) -> bool:
    """Release the worker lease and hand off a request that arrived meanwhile."""

    _request_path, lock_path = _state_paths(
        data_dir,
        project_root=project_root,
        client=client,
    )
    lock_path.unlink(missing_ok=True)
    latest = load_background_request(
        data_dir,
        project_root=project_root,
        client=client,
    )
    if latest is None or latest.generation == processed_generation:
        return False
    if not _acquire_lock(lock_path, now=time.time()):
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
    if not lock_path.is_file():
        return False
    timestamp = time.time() if now is None else float(now)
    try:
        os.utime(lock_path, (timestamp, timestamp))
    except OSError:
        return False
    return True


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
    }
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _acquire_lock(path: Path, *, now: float) -> bool:
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
        handle.write(f"{os.getpid()}\n")
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
