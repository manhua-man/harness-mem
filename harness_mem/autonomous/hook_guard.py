"""Block and verify Hook re-entry during background CLI runs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

AUTONOMOUS_PROVIDER_ENV = "HARNESS_MEM_AUTONOMOUS_PROVIDER"
_BLOCKED_ACTIONS = frozenset({"wake-start", "post-turn-maintenance", "dream-end"})


def autonomous_provider_context_active() -> bool:
    """True when the current process was spawned by an autonomous provider."""

    return os.environ.get(AUTONOMOUS_PROVIDER_ENV) == "1"


def _active_lease_dir(data_dir: Path) -> Path:
    return Path(data_dir) / "autonomous" / "hook_guard" / "active"


def _linux_process_stat(pid: int) -> tuple[int | None, str | None]:
    try:
        text = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None, None
    try:
        fields = text.rsplit(")", 1)[1].strip().split()
        return int(fields[1]), fields[19]
    except (IndexError, ValueError):
        return None, None


def _posix_process_stat(pid: int) -> tuple[int | None, str | None]:
    parent, token = _linux_process_stat(pid)
    if parent is not None:
        return parent, token
    try:
        completed = subprocess.run(
            ["ps", "-o", "ppid=", "-o", "lstart=", "-p", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
            check=False,
        )
        fields = completed.stdout.strip().split(maxsplit=1)
        if completed.returncode != 0 or not fields:
            return None, None
        return int(fields[0]), fields[1] if len(fields) > 1 else None
    except (OSError, ValueError, subprocess.SubprocessError):
        return None, None


def _windows_process_snapshot() -> dict[int, int]:
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes

    class ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessEntry)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    snapshot = kernel32.CreateToolhelp32Snapshot(0x00000002, 0)
    if snapshot == ctypes.c_void_p(-1).value:
        return {}
    parents: dict[int, int] = {}
    entry = ProcessEntry()
    entry.dwSize = ctypes.sizeof(ProcessEntry)
    try:
        if not kernel32.Process32FirstW(snapshot, ctypes.byref(entry)):
            return {}
        while True:
            parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snapshot, ctypes.byref(entry)):
                break
    finally:
        kernel32.CloseHandle(snapshot)
    return parents


def _process_start_token(pid: int) -> str | None:
    if os.name != "nt":
        _parent, token = _posix_process_stat(pid)
        return token

    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
        ctypes.POINTER(wintypes.FILETIME),
    ]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return None
    created = wintypes.FILETIME()
    exited = wintypes.FILETIME()
    kernel = wintypes.FILETIME()
    user = wintypes.FILETIME()
    try:
        if not kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            return None
    finally:
        kernel32.CloseHandle(handle)
    value = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
    return str(value)


def _ancestor_process_ids() -> set[int]:
    parents = _windows_process_snapshot()
    current = os.getpid()
    ancestors: set[int] = set()
    for _ in range(64):
        if os.name == "nt":
            parent = parents.get(current)
        else:
            parent, _token = _posix_process_stat(current)
        if parent is None or parent <= 1 or parent in ancestors:
            break
        ancestors.add(parent)
        current = parent
    return ancestors


def register_provider_process_lease(data_dir: Path, *, pid: int) -> Path:
    """Record one active provider process outside its mutable environment."""

    directory = _active_lease_dir(data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{pid}-{uuid4().hex}.json"
    payload = {
        "pid": pid,
        "process_start": _process_start_token(pid),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return path


def release_provider_process_lease(path: Path | None) -> None:
    if path is None:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        pass


@contextmanager
def active_provider_process_lease(
    data_dir: Path,
    *,
    pid: int,
) -> Iterator[None]:
    path = register_provider_process_lease(data_dir, pid=pid)
    try:
        yield
    finally:
        release_provider_process_lease(path)


def autonomous_provider_ancestor_active(data_dir: Path) -> bool:
    """True when an active provider process appears in this process's parents."""

    ancestors = _ancestor_process_ids()
    if not ancestors:
        return False
    directory = _active_lease_dir(data_dir)
    try:
        paths = tuple(directory.glob("*.json"))
    except OSError:
        return False
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            pid = int(payload.get("pid"))
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue
        if pid not in ancestors:
            continue
        expected_start = str(payload.get("process_start") or "")
        actual_start = str(_process_start_token(pid) or "")
        if expected_start and actual_start != expected_start:
            continue
        return True
    return False


def autonomous_provider_hook_reentry_blocked(
    action: str,
    *,
    data_dir: Path | None = None,
) -> bool:
    """True when this host-entry action must not recurse from autonomous work."""

    blocked_action = str(action or "") in _BLOCKED_ACTIONS
    if not blocked_action:
        return False
    if autonomous_provider_context_active():
        return True
    return data_dir is not None and autonomous_provider_ancestor_active(data_dir)


def _distill_job_ids(data_dir: Path, *, project_name: str) -> set[str]:
    database = Path(data_dir) / "transcript_ledger.sqlite"
    if not database.is_file():
        return set()
    try:
        connection = sqlite3.connect(f"file:{database.as_posix()}?mode=ro", uri=True)
        try:
            rows = connection.execute(
                "SELECT id FROM distill_jobs WHERE project_name = ?",
                (project_name,),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        return set()
    return {str(row[0]) for row in rows}


def _trigger_block_recorded(data_dir: Path, trigger_id: str) -> bool:
    directory = Path(data_dir) / "autonomous" / "hook_reentry"
    try:
        paths = tuple(directory.glob("*.jsonl"))
    except OSError:
        return False
    for path in paths:
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line in lines:
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(payload.get("trigger_id") or "") == trigger_id:
                return True
    return False


def challenge_hook_reentry_guard(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    client: str,
) -> dict[str, Any]:
    """Call every Hook action with the env marker removed and verify it is blocked."""

    before_jobs = _distill_job_ids(data_dir, project_name=project_name)
    challenge_group = hashlib.sha256(
        f"{project_name}\0{uuid4().hex}".encode("utf-8")
    ).hexdigest()[:32]
    results: dict[str, bool] = {}
    with active_provider_process_lease(data_dir, pid=os.getpid()):
        for action in sorted(_BLOCKED_ACTIONS):
            trigger_id = f"hook-guard-{challenge_group}-{action}"
            env = os.environ.copy()
            env.pop(AUTONOMOUS_PROVIDER_ENV, None)
            env.pop("HARNESS_MEM_HOOK_BACKGROUND_WORKER", None)
            env.pop("HARNESS_MEM_HOOK_BACKGROUND_GENERATION", None)
            env["HARNESS_MEM_DATA_DIR"] = str(Path(data_dir).resolve())
            command = [
                sys.executable,
                "-m",
                "harness_mem.host_entry",
                "--action",
                action,
                "--project-root",
                str(project_root),
                "--source",
                "ide_hook",
                "--trigger-id",
                trigger_id,
                "--client",
                client,
            ]
            try:
                completed = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=20,
                    check=False,
                )
                payload = json.loads(completed.stdout.strip() or "{}")
            except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
                results[action] = False
                continue
            results[action] = bool(
                completed.returncode == 0
                and payload.get("status") == "skipped"
                and payload.get("reason")
                == "autonomous_provider_hook_reentry_blocked"
                and _trigger_block_recorded(data_dir, trigger_id)
            )
    created_jobs = sorted(
        _distill_job_ids(data_dir, project_name=project_name) - before_jobs
    )
    return {
        "actions": results,
        "all_blocked": len(results) == len(_BLOCKED_ACTIONS) and all(results.values()),
        "downstream_jobs_created": len(created_jobs),
    }


def _project_key(project_name: str, project_root: Path) -> str:
    material = f"{project_name}\0{project_root.expanduser().resolve()}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()[:24]


def hook_reentry_ledger_path(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
) -> Path:
    key = _project_key(project_name, project_root)
    return Path(data_dir) / "autonomous" / "hook_reentry" / f"{key}.jsonl"


def record_hook_reentry_block(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    action: str,
    trigger_id: str | None = None,
) -> None:
    """Append one blocked Hook attempt while autonomous provider context is active."""

    path = hook_reentry_ledger_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "action": str(action or ""),
        "trigger_id": str(trigger_id or ""),
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")


def count_hook_reentry_blocks(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None = None,
) -> int:
    """Count ledger entries, optionally scoped to one Hook trigger id."""

    path = hook_reentry_ledger_path(
        data_dir,
        project_name=project_name,
        project_root=project_root,
    )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 0
    selected = str(trigger_id or "")
    count = 0
    for line in lines:
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(payload, dict):
            continue
        if selected and str(payload.get("trigger_id") or "") != selected:
            continue
        count += 1
    return count


def summarize_hook_reentry_blocks(
    data_dir: Path,
    *,
    project_name: str,
    project_root: Path,
    trigger_id: str | None = None,
) -> dict[str, Any]:
    """Return a compact audit view for receipts and health cards."""

    return {
        "count": count_hook_reentry_blocks(
            data_dir,
            project_name=project_name,
            project_root=project_root,
            trigger_id=trigger_id,
        ),
        "trigger_id": trigger_id,
    }
