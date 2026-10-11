"""Temporary manual-batch references, never knowledge or completion evidence.

Selection is sorted by (client, session_id, source_id, source_revision). Each
input dictionary contains those four strings and optionally reference_id.
There is no session-count cap. States describe orchestration only: active or
stopped for a batch; selected, bound or failed for a reference. Failures remain
until explicit retry on an active batch. The caller compares the frozen runtime
fingerprint before resuming work; this store does not inspect running code.
"""

from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from typing import Iterator
from uuid import UUID, uuid4

from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.core.schemas.transcript import TranscriptSourceRevision


_REFERENCE_FIELDS = ("client", "session_id", "source_id", "source_revision")


def _text(value: object, field: str, limit: int = 1024) -> str:
    if (not isinstance(value, str) or not value.strip() or value != value.strip()
            or len(value) > limit or any(ord(c) < 32 for c in value)):
        raise ValueError(f"invalid {field}")
    return value


def _scope(project_name: str, project_root: str) -> tuple[str, str]:
    name = _text(project_name, "project_name")
    root = Path(project_root)
    if not root.is_absolute() or ".." in root.parts:
        raise ValueError("project_root must be absolute and traversal-free")
    return name, os.path.normcase(str(root.resolve()))


def _selection(sessions: list[dict]) -> list[dict]:
    if not isinstance(sessions, list) or not sessions:
        raise ValueError("sessions must be a nonempty list")
    selected = []
    identities: set[tuple[str, ...]] = set()
    references: set[str] = set()
    for item in sessions:
        if not isinstance(item, dict) or set(item) - {*_REFERENCE_FIELDS, "reference_id"}:
            raise ValueError("selection must contain references only")
        identity = tuple(_text(item.get(key), key) for key in _REFERENCE_FIELDS)
        reference = item.get("reference_id")
        if reference is None:
            reference = hashlib.sha256(json.dumps(identity).encode()).hexdigest()
        reference = _text(reference, "reference_id")
        if identity in identities or reference in references:
            raise ValueError("duplicate selection or reference_id")
        identities.add(identity)
        references.add(reference)
        selected.append(dict(zip(_REFERENCE_FIELDS, identity), reference_id=reference))
    return sorted(selected, key=lambda row: tuple(row[key] for key in _REFERENCE_FIELDS))


def _completed_references(values: list[str], sessions: list[dict]) -> list[str]:
    """Freeze prior completion attribution without copying prior job results."""
    if not isinstance(values, list):
        raise ValueError("already_completed must be a list")
    references = {_text(value, "already_completed reference_id") for value in values}
    if references - {row["reference_id"] for row in sessions}:
        raise ValueError("already_completed must be a subset of selection")
    return sorted(references)


class ManualBatchStore:
    """One overwritten JSON manifest per batch; no append log or content copies.

    Construction and load are read-only. Missing loads raise FileNotFoundError;
    invalid scope, schema, selection or rebinding raises ValueError. Unknown
    reference IDs raise KeyError. OS locks serialize independent instances and
    processes and are released on process exit. Lock files contain no history.
    """

    def __init__(self, data_dir: Path):
        self._data_dir = Path(data_dir).resolve()
        self.root = self._data_dir / "manual-batches"

    def _path(self, batch_id: str) -> Path:
        if not isinstance(batch_id, str) or str(UUID(batch_id)) != batch_id:
            raise ValueError("batch_id must be a canonical UUID")
        if self.root.resolve() != self.root:
            raise ValueError("manual-batches must not redirect outside its directory")
        path = self.root / f"{batch_id}.json"
        if path.is_symlink() or path.resolve().parent != self.root:
            raise ValueError("manifest path must not redirect")
        return path

    def owns_job(self, job: SessionDistillJob, revision: TranscriptSourceRevision | None) -> bool:
        """Read frozen ownership independently of job binding, state or code version."""
        if job.manual_only:
            return True
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink():
                raise ValueError("manual batch manifest must not redirect")
            header = json.loads(path.read_text(encoding="utf-8"))
            if (header.get("project_name") != job.project_name
                    or _scope(job.project_name, header.get("project_root", ""))[1]
                    != _scope(job.project_name, job.project_root)[1]):
                continue
            manifest = self.load(path.stem, job.project_name, job.project_root)
            if job.id in manifest["bindings"].values():
                return True
            if (revision is None or revision.project_name != job.project_name
                    or _scope(job.project_name, revision.project_root)[1]
                    != _scope(job.project_name, job.project_root)[1]
                    or revision.client != job.client or revision.session_id != job.session_id):
                continue
            if any(
                ref["client"] == job.client and ref["session_id"] == job.session_id
                and (job.source_id == ref["source_id"] and job.source_revision == ref["source_revision"]
                     or f"sha256:{revision.raw_sha256}" == ref["source_revision"])
                for ref in manifest["sessions"]
            ):
                return True
        return False

    def create(self, project_name: str, project_root: str, sessions: list[dict],
               runtime_fingerprint: str | None = None,
               already_completed: list[str] | None = None) -> dict:
        name, root = _scope(project_name, project_root)
        selection = _selection(sessions)
        if runtime_fingerprint is not None:
            _text(runtime_fingerprint, "runtime_fingerprint")
        completed = _completed_references(
            [] if already_completed is None else already_completed, selection,
        )
        batch_id = str(uuid4())
        payload = {
            "version": 1, "batch_id": batch_id, "project_name": name,
            "project_root": root, "state": "active", "sessions": selection,
            "bindings": {}, "failures": {},
            "runtime_fingerprint": runtime_fingerprint,
            "already_completed": completed,
        }
        path = self._path(batch_id)
        self.root.mkdir(parents=True, exist_ok=True)
        with self._locked(path):
            if path.exists():
                raise FileExistsError(path)
            self._write(path, payload)
        return payload

    def load(self, batch_id: str, project_name: str, project_root: str) -> dict:
        name, root = _scope(project_name, project_root)
        payload = json.loads(self._path(batch_id).read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("invalid manifest schema")
        # Original v1 manifests have no fingerprint. Normalize only in memory;
        # loading never rewrites the file or invents a runtime identity.
        payload.setdefault("runtime_fingerprint", None)
        payload.setdefault("already_completed", [])
        if set(payload) != {
            "version", "batch_id", "project_name", "project_root", "state",
            "sessions", "bindings", "failures", "runtime_fingerprint",
            "already_completed",
        }:
            raise ValueError("invalid manifest schema")
        if payload["runtime_fingerprint"] is not None:
            _text(payload["runtime_fingerprint"], "runtime_fingerprint")
        if type(payload["version"]) is not int or payload["version"] != 1:
            raise ValueError("unsupported manifest version")
        if (payload["batch_id"] != batch_id or payload["project_name"] != name
                or payload["project_root"] != root):
            raise ValueError("manifest scope mismatch")
        if payload["state"] not in ("active", "stopped"):
            raise ValueError("invalid batch state")
        if _selection(payload["sessions"]) != payload["sessions"]:
            raise ValueError("invalid frozen selection")
        if _completed_references(payload["already_completed"], payload["sessions"]) != (
            payload["already_completed"]
        ):
            raise ValueError("already_completed must be sorted and unique")
        ids = {row["reference_id"] for row in payload["sessions"]}
        for field in ("bindings", "failures"):
            values = payload[field]
            if not isinstance(values, dict) or set(values) - ids:
                raise ValueError(f"invalid {field}")
            for value in values.values():
                _text(value, field)
        jobs = list(payload["bindings"].values())
        if len(jobs) != len(set(jobs)):
            raise ValueError("job bound to multiple references")
        return payload

    def bind_job(self, batch_id: str, project_name: str, project_root: str,
                 reference_id: str, job_id: str) -> dict:
        job_id = _text(job_id, "job_id")
        return self._update(batch_id, project_name, project_root, reference_id,
                            job_id=job_id)

    def record_failure(self, batch_id: str, project_name: str, project_root: str,
                       reference_id: str, reason: str, stop_batch: bool = False) -> dict:
        """Retain the first failure, allowing an atomic escalation to stopped.

        A different reason still rejects ordinary updates; stop_batch preserves
        the existing reason and escalates even when the new reason differs.
        """
        reason = _text(reason, "reason")
        if type(stop_batch) is not bool:
            raise ValueError("stop_batch must be boolean")
        return self._update(batch_id, project_name, project_root, reference_id,
                            reason=reason, stop_batch=stop_batch)

    def retry_failures(self, batch_id: str, project_name: str, project_root: str) -> dict:
        """Clear failures only for an explicit user retry of an active batch."""
        self.load(batch_id, project_name, project_root)
        path = self._path(batch_id)
        with self._locked(path):
            payload = self.load(batch_id, project_name, project_root)
            if payload["state"] != "active":
                raise ValueError("batch is stopped")
            if payload["failures"]:
                payload["failures"] = {}
                self._write(path, payload)
            return payload

    def _update(self, batch_id: str, project_name: str, project_root: str,
                reference_id: str, *, job_id: str | None = None,
                reason: str | None = None, stop_batch: bool = False) -> dict:
        # Reject missing or foreign manifests before creating a lock file.
        self.load(batch_id, project_name, project_root)
        path = self._path(batch_id)
        with self._locked(path):
            payload = self.load(batch_id, project_name, project_root)
            if reference_id not in {row["reference_id"] for row in payload["sessions"]}:
                raise KeyError(reference_id)
            before = json.dumps(payload, sort_keys=True)
            if job_id is not None:
                existing = payload["bindings"].get(reference_id)
                if existing is not None and existing != job_id:
                    raise ValueError("reference cannot be rebound")
                if existing is None:
                    if payload["state"] == "stopped":
                        raise ValueError("batch is stopped")
                    if job_id in payload["bindings"].values():
                        raise ValueError("job already bound to another reference")
                    payload["bindings"][reference_id] = job_id
            if reason is not None:
                existing = payload["failures"].get(reference_id)
                if existing is not None and existing != reason and not stop_batch:
                    raise ValueError("unresolved failure cannot be overwritten")
                payload["failures"].setdefault(reference_id, reason)
            if stop_batch:
                payload["state"] = "stopped"
            if before != json.dumps(payload, sort_keys=True):
                self._write(path, payload)
            return payload

    @staticmethod
    @contextmanager
    def _locked(path: Path) -> Iterator[None]:
        lock_path = path.with_suffix(".lock")
        if lock_path.is_symlink():
            raise ValueError("lock path must not redirect")
        with lock_path.open("a+b") as stream:
            deadline = time.monotonic() + 10
            while True:
                try:
                    if sys.platform == "win32":
                        import msvcrt

                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl

                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("manual batch lock timed out") from None
                    time.sleep(0.01)
            try:
                yield
            finally:
                if sys.platform == "win32":
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _write(path: Path, payload: dict) -> None:
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            with temporary.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            deadline = time.monotonic() + 10
            while True:
                try:
                    os.replace(temporary, path)
                    break
                except PermissionError as exc:
                    # Windows readers can briefly deny delete-sharing while
                    # loading the old manifest. Keep the writer lock and old
                    # file intact; retry only this atomic publication step.
                    if (sys.platform != "win32" or getattr(exc, "winerror", None) not in {5, 32, 33}
                            or time.monotonic() >= deadline):
                        raise
                    time.sleep(0.01)
        finally:
            temporary.unlink(missing_ok=True)


__all__ = ["ManualBatchStore"]
