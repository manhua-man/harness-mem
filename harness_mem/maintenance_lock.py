"""Cross-process exclusion for explicit maintenance runs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Iterator


def maintenance_lock_path(data_dir: Path) -> Path:
    return Path(data_dir) / "maintenance" / "exclusive-run.json"


def maintenance_is_locked(data_dir: Path) -> bool:
    return maintenance_lock_path(data_dir).is_file()


def _owner_is_alive(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        pid = int(payload["pid"])
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError):
        return True
    if pid == os.getpid():
        return True
    if os.name == "nt":
        try:
            import ctypes

            process = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if process:
                ctypes.windll.kernel32.CloseHandle(process)
                return True
            return int(ctypes.windll.kernel32.GetLastError()) not in {87, 1168}
        except (AttributeError, OSError):
            return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (OSError, PermissionError):
        return True
    return True


def _open_lock(path: Path) -> int:
    try:
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        if _owner_is_alive(path):
            raise
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


@contextmanager
def exclusive_maintenance_run(
    data_dir: Path,
    *,
    run_id: str,
    operation: str,
) -> Iterator[Path]:
    """Hold one fail-closed lock for a user-requested maintenance operation."""

    path = maintenance_lock_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = _open_lock(path)
    try:
        payload = json.dumps(
            {
                "run_id": run_id,
                "operation": operation,
                "pid": os.getpid(),
                "started_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        os.write(descriptor, payload)
        os.close(descriptor)
        descriptor = -1
        yield path
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            path.unlink()
        except FileNotFoundError:
            pass


__all__ = [
    "exclusive_maintenance_run",
    "maintenance_is_locked",
    "maintenance_lock_path",
]
