"""Content-free runtime diagnostics for the independent developer debugger.

This module is deliberately not part of the MCP or ``hm`` product surface.
Runtime code may emit best-effort lifecycle events, while the developer-only
debugger reads the append-only NDJSON ledger without initializing or mutating
any of the memory stores.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Iterable, Mapping
from uuid import uuid4
from contextlib import contextmanager
from contextvars import ContextVar

_ACTIVE_RUN: ContextVar[Any] = ContextVar("harness_mem_diagnostic_run", default=None)


def diagnostic_parent_id() -> str | None:
    active = _ACTIVE_RUN.get()
    return active.run_id if active is not None else os.environ.get(DEBUG_PARENT_RUN_ID_ENV)


def emit_current_stage(stage: str, *, details: Mapping[str, Any] | None = None) -> None:
    active = _ACTIVE_RUN.get()
    if active is not None:
        active.emit(stage, "running", details=details)


def exception_locations(exc: BaseException, *, _chain_depth: int = 0) -> dict[str, Any]:
    """Record bounded package code locations without source, SQL or locals."""
    locations: list[str] = []
    package_root = Path(__file__).resolve().parent
    traceback = exc.__traceback__
    while traceback is not None:
        code = traceback.tb_frame.f_code
        try:
            relative = Path(code.co_filename).resolve().relative_to(package_root)
        except (ValueError, OSError):
            pass
        else:
            locations.append(f"{relative.as_posix()}:{code.co_name}:{traceback.tb_lineno}")
        traceback = traceback.tb_next
    details: dict[str, Any] = {"exception_locations": locations[-8:]}
    for name in ("sqlite_errorcode", "sqlite_errorname"):
        value = getattr(exc, name, None)
        if isinstance(value, (int, str)):
            details[name] = value
    previous = exc.__cause__ or exc.__context__
    if previous is not None and previous is not exc and _chain_depth < 3:
        details["previous_exception"] = {
            "exception_type": type(previous).__name__,
            **exception_locations(previous, _chain_depth=_chain_depth + 1),
        }
    return details

LOGGER = logging.getLogger(__name__)

RUN_EVENT_SCHEMA_VERSION = "harness_mem.run_event.v1"
RUN_EVENT_DIRECTORY = "debug"
RUN_EVENT_FILENAME = "run-events.ndjson"
DEBUG_RUN_ID_ENV = "HARNESS_MEM_DEBUG_RUN_ID"
DEBUG_PARENT_RUN_ID_ENV = "HARNESS_MEM_DEBUG_PARENT_RUN_ID"
RUN_EVENT_OPERATIONS = frozenset({"hook", "autonomous", "dream", "distill"})
RUN_EVENT_STAGES = frozenset(
    {
        "accepted",
        "started",
        "source_loaded",
        "provider_started",
        "provider_finished",
        "answer_gate",
        "sqlite_committed",
        "readback_verified",
        "queued",
        "completed",
        "failed",
        "blocked",
        "deferred",
        "skipped",
    }
)
RUN_EVENT_STATUSES = frozenset(
    {"running", "completed", "failed", "blocked", "deferred", "skipped"}
)

TERMINAL_EVENT_STATUSES = frozenset(
    {"completed", "failed", "blocked", "deferred", "skipped"}
)
FAILURE_EVENT_STATUSES = frozenset({"failed", "blocked"})

_MAX_ERROR_MESSAGE_CHARS = 512
_MAX_DETAIL_STRING_CHARS = 160
_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(bearer\s+)[^\s,;]+"),
    re.compile(r"(?i)(api[_-]?key\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(access[_-]?token\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(secret\s*[=:]\s*)[^\s,;]+"),
    re.compile(r"(?i)(password\s*[=:]\s*)[^\s,;]+"),
)
_BLOCKED_DETAIL_KEYS = frozenset(
    {
        "prompt",
        "transcript",
        "content",
        "raw_output",
        "stdout",
        "stderr",
        "response",
        "messages",
        "secret",
        "api_key",
        "access_token",
    }
)


def new_run_id() -> str:
    """Return one opaque diagnostic run identifier."""

    return f"run-{uuid4().hex}"


def run_event_path(data_dir: Path) -> Path:
    """Return the independent append-only runtime event ledger path."""

    return Path(data_dir) / RUN_EVENT_DIRECTORY / RUN_EVENT_FILENAME


def sha256_text(value: str | Path | None) -> str | None:
    """Hash a non-secret identity value for content-free diagnostics."""

    if value is None:
        return None
    return "sha256:" + hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def project_root_sha256(project_root: str | Path | None) -> str | None:
    if project_root is None:
        return None
    try:
        resolved = Path(project_root).expanduser().resolve()
    except OSError:
        resolved = Path(str(project_root))
    return sha256_text(resolved)


def _default_runtime_fingerprint() -> str:
    """Return a stable, content-free fingerprint for the installed runtime."""

    try:
        from harness_mem import __version__

        version = str(__version__)
    except Exception:  # pragma: no cover - import fallback for standalone use.
        version = "unknown"
    return sha256_text(f"harness-mem:{version}") or "sha256:unknown"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_valid_event(event: Mapping[str, Any]) -> bool:
    required = {
        "schema_version",
        "event_id",
        "run_id",
        "timestamp",
        "operation",
        "stage",
        "status",
    }
    if not required.issubset(event):
        return False
    if event.get("schema_version") != RUN_EVENT_SCHEMA_VERSION:
        return False
    if not all(isinstance(event.get(key), str) and event.get(key) for key in required):
        return False
    return bool(
        event["operation"] in RUN_EVENT_OPERATIONS
        and event["stage"] in RUN_EVENT_STAGES
        and event["status"] in RUN_EVENT_STATUSES
    )


def _redact_text(value: Any, *, limit: int = _MAX_ERROR_MESSAGE_CHARS) -> str:
    text = str(value or "")
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(r"\1<redacted>", text)
    text = " ".join(text.split())
    return text[:limit]


def redact_text(value: Any, *, limit: int = _MAX_ERROR_MESSAGE_CHARS) -> str:
    """Return a bounded, secret-redacted diagnostic string."""

    return _redact_text(value, limit=limit)


def _safe_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _redact_text(value, limit=_MAX_DETAIL_STRING_CHARS)


def _safe_details(value: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not value:
        return None
    result: dict[str, Any] = {}
    for key, item in value.items():
        normalized_key = str(key)
        if normalized_key.lower() in _BLOCKED_DETAIL_KEYS:
            continue
        if isinstance(item, Mapping):
            nested = _safe_details(item)
            if nested:
                result[normalized_key] = nested
        elif isinstance(item, (list, tuple)):
            safe_items = [_safe_scalar(entry) for entry in item[:20]]
            result[normalized_key] = safe_items
        else:
            result[normalized_key] = _safe_scalar(item)
    return result or None


def _safe_error(value: Mapping[str, Any] | str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key in ("kind", "exception_type", "message", "retryable", "status_code"):
            if key not in value:
                continue
            item = value[key]
            if key == "message":
                result[key] = _redact_text(item)
            elif key == "retryable":
                result[key] = bool(item)
            elif key == "status_code":
                try:
                    result[key] = int(item)
                except (TypeError, ValueError):
                    result[key] = _redact_text(item, limit=32)
            else:
                result[key] = _redact_text(item, limit=128)
        return result or None
    return {"message": _redact_text(value)}


def safe_error(value: Mapping[str, Any] | str | None) -> dict[str, Any] | None:
    """Return an error summary safe for diagnostic reports and bundles."""

    return _safe_error(value)


def append_run_event(
    data_dir: Path,
    *,
    run_id: str,
    operation: str,
    stage: str,
    status: str,
    project_name: str | None = None,
    project_root: str | Path | None = None,
    parent_run_id: str | None = None,
    references: Mapping[str, Any] | None = None,
    runtime_fingerprint: str | None = None,
    duration_ms: int | float | None = None,
    error: Mapping[str, Any] | str | None = None,
    details: Mapping[str, Any] | None = None,
) -> str | None:
    """Best-effort append of one content-free diagnostic event.

    Diagnostics must never change the result of the memory operation being
    observed.  A write failure is therefore logged and represented to readers
    as an evidence gap rather than raised to the caller.
    """

    event_id = f"evt-{uuid4().hex}"
    event: dict[str, Any] = {
        "schema_version": RUN_EVENT_SCHEMA_VERSION,
        "event_id": event_id,
        "run_id": str(run_id),
        "timestamp": _now(),
        "operation": _redact_text(operation, limit=64),
        "stage": _redact_text(stage, limit=64),
        "status": _redact_text(status, limit=32),
        "runtime_fingerprint": runtime_fingerprint or _default_runtime_fingerprint(),
    }
    if project_name:
        event["project_name"] = _redact_text(project_name, limit=160)
    root_digest = project_root_sha256(project_root)
    if root_digest:
        event["project_root_sha256"] = root_digest
    if parent_run_id:
        event["parent_run_id"] = str(parent_run_id)
    if references:
        event["references"] = {
            str(key): _safe_scalar(value)
            for key, value in references.items()
            if value is not None and str(key).lower() not in _BLOCKED_DETAIL_KEYS
        }
    if runtime_fingerprint:
        event["runtime_fingerprint"] = _redact_text(runtime_fingerprint, limit=160)
    if duration_ms is not None:
        try:
            event["duration_ms"] = max(0, int(float(duration_ms)))
        except (TypeError, ValueError):
            pass
    safe_error = _safe_error(error)
    if safe_error:
        event["error"] = safe_error
    safe_details = _safe_details(details)
    if safe_details:
        event["details"] = safe_details

    path = run_event_path(Path(data_dir))
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
    except Exception:  # noqa: BLE001 - diagnostic persistence is best effort.
        LOGGER.warning("could not persist diagnostic run event", exc_info=True)
        return None
    return event_id


@dataclass
class DiagnosticRun:
    """Small context passed across one runtime operation's existing owner calls."""

    data_dir: Path
    operation: str
    project_name: str | None = None
    project_root: str | Path | None = None
    run_id: str = field(default_factory=new_run_id)
    parent_run_id: str | None = None
    references: dict[str, Any] = field(default_factory=dict)
    runtime_fingerprint: str | None = None
    _started_monotonic: float = field(
        default_factory=time.monotonic,
        init=False,
        repr=False,
    )

    @contextmanager
    def activate_children(self):
        """Link nested calls without modifying process-global environment."""
        token = _ACTIVE_RUN.set(self)
        try:
            yield self
        finally:
            _ACTIVE_RUN.reset(token)

    def emit(
        self,
        stage: str,
        status: str,
        *,
        references: Mapping[str, Any] | None = None,
        duration_ms: int | float | None = None,
        error: Mapping[str, Any] | str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> str | None:
        merged = {**self.references, **(dict(references or {}))}
        if duration_ms is None and status in TERMINAL_EVENT_STATUSES:
            duration_ms = (time.monotonic() - self._started_monotonic) * 1000.0
        return append_run_event(
            self.data_dir,
            run_id=self.run_id,
            operation=self.operation,
            stage=stage,
            status=status,
            project_name=self.project_name,
            project_root=self.project_root,
            parent_run_id=self.parent_run_id,
            references=merged,
            duration_ms=duration_ms,
            error=error,
            details=details,
            runtime_fingerprint=self.runtime_fingerprint
            or self.references.get("runtime_fingerprint"),
        )


def load_run_events(
    data_dir: Path,
    *,
    run_id: str | None = None,
    project_name: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Load valid events and count malformed lines for diagnostic reporting."""

    path = run_event_path(Path(data_dir))
    if not path.is_file():
        return [], 0
    events: list[dict[str, Any]] = []
    malformed = 0
    try:
        with path.open("r", encoding="utf-8") as stream:
            for line in stream:
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    malformed += 1
                    continue
                if not isinstance(event, dict):
                    malformed += 1
                    continue
                if not _is_valid_event(event):
                    malformed += 1
                    continue
                if run_id is not None and event.get("run_id") != run_id:
                    continue
                if project_name is not None and event.get("project_name") != project_name:
                    continue
                events.append(event)
    except OSError:
        raise
    return events, malformed


def iter_run_events(
    data_dir: Path,
    *,
    run_id: str | None = None,
    project_name: str | None = None,
) -> Iterable[dict[str, Any]]:
    """Yield valid events without making the ledger a runtime authority."""

    events, _malformed = load_run_events(
        data_dir,
        run_id=run_id,
        project_name=project_name,
    )
    yield from events


__all__ = [
    "DiagnosticRun",
    "DEBUG_PARENT_RUN_ID_ENV",
    "DEBUG_RUN_ID_ENV",
    "FAILURE_EVENT_STATUSES",
    "RUN_EVENT_FILENAME",
    "RUN_EVENT_OPERATIONS",
    "RUN_EVENT_SCHEMA_VERSION",
    "RUN_EVENT_STAGES",
    "RUN_EVENT_STATUSES",
    "TERMINAL_EVENT_STATUSES",
    "append_run_event",
    "iter_run_events",
    "load_run_events",
    "new_run_id",
    "project_root_sha256",
    "redact_text",
    "run_event_path",
    "safe_error",
]
