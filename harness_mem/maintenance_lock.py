"""Cross-process exclusion for explicit maintenance runs."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Iterable, Iterator


_OWNER_SESSION_ENV_NAMES = (
    "CODEX_SESSION_ID",
    "CODEX_THREAD_ID",
)
_POST_RUN_SUPPRESSION_SECONDS = 300


def maintenance_lock_path(data_dir: Path) -> Path:
    return Path(data_dir) / "maintenance" / "exclusive-run.json"


def _read_payload(path: Path) -> dict[str, object] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _remove_lock(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _owner_session_ids(values: Iterable[str] | None) -> list[str]:
    candidates = (
        values
        if values is not None
        else (os.environ.get(name, "") for name in _OWNER_SESSION_ENV_NAMES)
    )
    return sorted({str(value).strip() for value in candidates if str(value).strip()})


def maintenance_is_locked(
    data_dir: Path,
    *,
    trigger_id: str | None = None,
) -> bool:
    """Return whether ordinary background work must stay out.

    A live maintenance process excludes every background writer. After the
    process exits, only the Agent session that launched it stays suppressed for
    a short hand-off window, so its own maintenance transcript cannot be
    ingested as project knowledge when the host emits the delayed Stop Hook.
    """

    path = maintenance_lock_path(data_dir)
    payload = _read_payload(path)
    if payload is None:
        return False
    if not payload:
        return True
    released_until = payload.get("suppress_until")
    if isinstance(released_until, str):
        try:
            until = datetime.fromisoformat(released_until)
        except ValueError:
            return True
        if until <= datetime.now(timezone.utc):
            _remove_lock(path)
            return False
        raw_owner_ids = payload.get("owner_session_ids")
        owner_ids = {
            value
            for value in raw_owner_ids
            if isinstance(value, str) and value
        } if isinstance(raw_owner_ids, list) else set()
        return bool(trigger_id and trigger_id in owner_ids)
    if _owner_is_alive(path):
        return True
    _remove_lock(path)
    return False


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
        payload = _read_payload(path)
        if payload and isinstance(payload.get("suppress_until"), str):
            _remove_lock(path)
            return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        if _owner_is_alive(path):
            raise
        _remove_lock(path)
        return os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)


@contextmanager
def exclusive_maintenance_run(
    data_dir: Path,
    *,
    run_id: str,
    operation: str,
    owner_session_ids: Iterable[str] | None = None,
    post_run_suppression_seconds: int = _POST_RUN_SUPPRESSION_SECONDS,
) -> Iterator[Path]:
    """Hold one fail-closed lock for a user-requested maintenance operation."""

    path = maintenance_lock_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = _open_lock(path)
    session_ids = _owner_session_ids(owner_session_ids)
    started_at = datetime.now(timezone.utc)
    lock_payload = {
        "run_id": run_id,
        "operation": operation,
        "pid": os.getpid(),
        "started_at": started_at.isoformat(),
        "owner_session_ids": session_ids,
    }
    try:
        payload = json.dumps(
            lock_payload,
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
        suppression_seconds = max(0, int(post_run_suppression_seconds))
        if session_ids and suppression_seconds:
            released_at = datetime.now(timezone.utc)
            path.write_text(
                json.dumps(
                    {
                        **lock_payload,
                        "released_at": released_at.isoformat(),
                        "suppress_until": (
                            released_at + timedelta(seconds=suppression_seconds)
                        ).isoformat(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        else:
            _remove_lock(path)


__all__ = [
    "exclusive_maintenance_run",
    "maintenance_is_locked",
    "maintenance_lock_path",
]
