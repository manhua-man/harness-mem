"""Direct runtime proof for Codex-aware native source cleanup liveness."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from contextlib import closing
import hashlib
import importlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import time
from typing import Any

from harness_mem.core.schemas.transcript import TranscriptSource
from harness_mem.native_source_cleanup import (
    apply_native_source_cleanup,
    cleanup_native_source,
    plan_native_source_cleanup,
)


def _source(root: Path, state_db: Path, session_id: str) -> tuple[TranscriptSource, Path]:
    path = root / "sessions" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    content = b'{"type":"session_meta"}\n'
    path.write_bytes(content)
    old = time.time() - 300
    os.utime(path, (old, old))
    digest = hashlib.sha256(content).hexdigest()
    source = TranscriptSource(
        id=f"source-{session_id}",
        project_name="cleanup-liveness-probe",
        project_root=str(root / "project"),
        client="codex",
        session_id=session_id,
        source_kind="codex-current",
        source_uri=path.absolute().as_uri(),
        source_revision=f"sha256:{digest}",
        raw_sha256=digest,
        normalized_sha256=digest,
        raw_size_bytes=len(content),
        normalized_size_bytes=len(content),
        mtime_ns=path.stat().st_mtime_ns,
        metadata={
            "native_source_uri": path.absolute().as_uri(),
            "native_input_sha256": digest,
            "native_cleanup_descriptor": {
                "version": 1,
                "allowed_root_uris": [(root / "sessions").absolute().as_uri()],
            },
            "codex_writer_lock_root_uri": (root / "thread-writer-locks").absolute().as_uri(),
            "codex_task_state_db_uri": state_db.absolute().as_uri(),
        },
    )
    return source, path


def _create_state_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE threads (id TEXT PRIMARY KEY, archived INTEGER)")
        connection.execute(
            "CREATE TABLE thread_spawn_edges (child_thread_id TEXT PRIMARY KEY, status TEXT)"
        )
        connection.commit()


def _record_task(path: Path, session_id: str, *, status: str = "closed") -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO threads VALUES (?, 0)", (session_id,))
        connection.execute(
            "INSERT INTO thread_spawn_edges VALUES (?, ?)",
            (session_id, status),
        )
        connection.commit()


def _hold_windows_lock(path: Path) -> Any:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    create_file = kernel32.CreateFileW
    create_file.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    create_file.restype = wintypes.HANDLE
    handle = create_file(str(path), 0x80000000, 0, None, 3, 0, None)
    if handle == wintypes.HANDLE(-1).value:
        raise OSError(ctypes.get_last_error(), "could not hold writer lock")
    return handle


def _close_windows_lock(handle: Any) -> None:
    ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)


def _hold_posix_lock(path: Path) -> Any:
    fcntl = importlib.import_module("fcntl")
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("wb")
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    return handle


def _close_posix_lock(handle: Any) -> None:
    fcntl = importlib.import_module("fcntl")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    finally:
        handle.close()


def _hold_activity_lock(path: Path) -> Any:
    if os.name == "nt":
        return _hold_windows_lock(path)
    return _hold_posix_lock(path)


def _close_activity_lock(handle: Any) -> None:
    if os.name == "nt":
        _close_windows_lock(handle)
        return
    _close_posix_lock(handle)


def run_cleanup_liveness_probe() -> dict[str, Any]:
    with TemporaryDirectory(prefix="harness-mem-cleanup-liveness-") as temporary:
        root = Path(temporary) / ".codex"
        state_db = root / "state_5.sqlite"
        _create_state_db(state_db)

        writer_id = "019ff900-1000-7000-8000-000000000001"
        writer_source, writer_path = _source(root, state_db, writer_id)
        _record_task(state_db, writer_id)
        writer_handle = _hold_activity_lock(
            root / "thread-writer-locks" / f"{writer_id}.lock"
        )
        try:
            writer = cleanup_native_source(writer_source, quiet_seconds=0)
        finally:
            _close_activity_lock(writer_handle)

        task_id = "019ff900-1000-7000-8000-000000000002"
        task_source, task_path = _source(root, state_db, task_id)
        _record_task(state_db, task_id, status="open")
        task = cleanup_native_source(task_source, quiet_seconds=0)

        inactive_id = "019ff900-1000-7000-8000-000000000003"
        inactive_source, inactive_path = _source(root, state_db, inactive_id)
        _record_task(state_db, inactive_id)
        inactive = cleanup_native_source(inactive_source, quiet_seconds=0)

        reactivated_id = "019ff900-1000-7000-8000-000000000004"
        reactivated_source, reactivated_path = _source(root, state_db, reactivated_id)
        _record_task(state_db, reactivated_id)
        reactivated_plan = plan_native_source_cleanup(reactivated_source, quiet_seconds=0)
        reactivated_handle = _hold_activity_lock(
            root / "thread-writer-locks" / f"{reactivated_id}.lock"
        )
        try:
            reactivated = apply_native_source_cleanup(reactivated_plan)
        finally:
            _close_activity_lock(reactivated_handle)

        unknown_root = Path(temporary) / "unknown" / ".codex"
        unknown_db = unknown_root / "state_5.sqlite"
        unknown_db.parent.mkdir(parents=True, exist_ok=True)
        unknown_db.write_bytes(b"not sqlite")
        unknown_id = "019ff900-1000-7000-8000-000000000005"
        unknown_source, unknown_path = _source(unknown_root, unknown_db, unknown_id)
        unknown = cleanup_native_source(unknown_source, quiet_seconds=0)

        result = {
            "active_writer_retained": writer.get("status") == "retained"
            and writer.get("reason_codes") == ["native_source_active_writer"]
            and writer_path.is_file(),
            "active_task_retained": task.get("status") == "retained"
            and task.get("reason_codes") == ["native_source_active_task"]
            and task_path.is_file(),
            "inactive_task_deleted": inactive.get("status") == "deleted"
            and not inactive_path.exists(),
            "reactivation_before_claim_retained": reactivated.get("status") == "retained"
            and reactivated.get("reason_codes")
            == ["native_source_reactivated_before_claim"]
            and reactivated_path.is_file(),
            "unknown_liveness_retained": unknown.get("status") == "retained"
            and unknown.get("reason_codes") == ["native_source_liveness_unknown"]
            and unknown_path.is_file(),
            "diagnostics": {
                "writer": {
                    "status": writer.get("status"),
                    "reason_codes": writer.get("reason_codes"),
                },
                "task": {
                    "status": task.get("status"),
                    "reason_codes": task.get("reason_codes"),
                },
                "inactive": {
                    "status": inactive.get("status"),
                    "reason_codes": inactive.get("reason_codes"),
                },
                "reactivated": {
                    "status": reactivated.get("status"),
                    "reason_codes": reactivated.get("reason_codes"),
                },
                "unknown": {
                    "status": unknown.get("status"),
                    "reason_codes": unknown.get("reason_codes"),
                },
            },
        }
        result["verified"] = all(
            value for key, value in result.items() if key != "diagnostics"
        )
        return result


def main() -> int:
    result = run_cleanup_liveness_probe()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
