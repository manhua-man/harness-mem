"""Retry-safe, finite-lifetime workspace for knowledge processing.

Candidates, evidence envelopes, and proposed decisions are inputs to a distill
or governance job.  They are not current knowledge and are deliberately kept
outside canonical SQLite.  This store persists only enough working state to
resume a running/retryable job and can remove a completed candidate atomically
from the product's point of view.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import threading
from typing import TypeVar
from uuid import uuid4

from harness_mem.core.schemas.knowledge import (
    AssimilationDecision,
    KnowledgeCandidate,
    KnowledgeEvidence,
)


T = TypeVar("T", KnowledgeCandidate, KnowledgeEvidence, AssimilationDecision)
_UNRESOLVED_DISPOSITIONS = {"defer", "conflict"}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class KnowledgeJobWorkspace:
    """File-backed work state with explicit terminal cleanup and TTL pruning."""

    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "job_workspaces" / "knowledge"
        self._candidate_dir = self.root / "candidates"
        self._evidence_dir = self.root / "evidence"
        self._decision_dir = self.root / "decisions"
        self._lock = threading.RLock()

    def save_candidate(
        self,
        candidate: KnowledgeCandidate,
        *,
        workspace_id: str | None = None,
    ) -> str:
        with self._lock:
            existing = self._read_wrapper(self._candidate_path(candidate.id))
            if existing is not None:
                previous = KnowledgeCandidate.from_dict(dict(existing["data"]))
                if previous.project_name != candidate.project_name:
                    raise ValueError("knowledge candidate id crosses projects")
            scope = (
                str(workspace_id or "").strip()
                or self._workspace_from_candidate_evidence(candidate.id)
                or f"adhoc:{candidate.id}"
            )
            self._write_wrapper(
                self._candidate_path(candidate.id),
                scope,
                candidate.to_dict(),
            )
        return candidate.id

    def get_candidate(self, candidate_id: str) -> KnowledgeCandidate | None:
        wrapper = self._read_wrapper(self._candidate_path(candidate_id))
        return (
            KnowledgeCandidate.from_dict(dict(wrapper["data"]))
            if wrapper is not None
            else None
        )

    def list_candidates(self, project_name: str) -> list[KnowledgeCandidate]:
        return [
            candidate
            for candidate in self._list_models(self._candidate_dir, KnowledgeCandidate)
            if candidate.project_name == project_name
        ]

    def save_evidence(self, evidence: KnowledgeEvidence) -> str:
        with self._lock:
            candidate = self.get_candidate(evidence.candidate_id)
            if candidate is None:
                raise ValueError("knowledge evidence requires an existing candidate")
            if candidate.project_name != evidence.project_name:
                raise ValueError("knowledge evidence must share the candidate project")
            workspace_id = (
                str(evidence.distill_job_id or "").strip()
                or self.workspace_id_for_candidate(evidence.candidate_id)
                or f"adhoc:{evidence.candidate_id}"
            )
            self.save_candidate(candidate, workspace_id=workspace_id)
            self._write_wrapper(
                self._evidence_path(evidence.candidate_id, evidence.id),
                workspace_id,
                evidence.to_dict(),
            )
        return evidence.id

    def list_evidence(self, candidate_id: str) -> list[KnowledgeEvidence]:
        return self._list_models(
            self._evidence_dir / self._key(candidate_id), KnowledgeEvidence
        )

    def save_unresolved_decision(self, decision: AssimilationDecision) -> str:
        """Persist only defer/conflict proposals that still require resolution."""

        if decision.disposition not in _UNRESOLVED_DISPOSITIONS:
            raise ValueError("only unresolved decisions belong in a job workspace")
        with self._lock:
            candidate = self.get_candidate(decision.candidate_id)
            if candidate is None:
                raise ValueError("assimilation decision requires an existing candidate")
            if candidate.project_name != decision.project_name:
                raise ValueError("assimilation decision must share the candidate project")
            workspace_id = (
                self.workspace_id_for_candidate(candidate.id)
                or f"adhoc:{candidate.id}"
            )
            path = self._decision_path(decision.id)
            existing = self._read_wrapper(path)
            if existing is not None and dict(existing["data"]) != decision.to_dict():
                raise ValueError("assimilation decision id already has different data")
            self._write_wrapper(path, workspace_id, decision.to_dict())
        return decision.id

    def get_unresolved_decision(
        self, decision_id: str
    ) -> AssimilationDecision | None:
        wrapper = self._read_wrapper(self._decision_path(decision_id))
        return (
            AssimilationDecision.from_dict(dict(wrapper["data"]))
            if wrapper is not None
            else None
        )

    def list_unresolved_decisions(self) -> list[AssimilationDecision]:
        return self._list_models(self._decision_dir, AssimilationDecision)

    def workspace_id_for_candidate(self, candidate_id: str) -> str | None:
        wrapper = self._read_wrapper(self._candidate_path(candidate_id))
        return str(wrapper["workspace_id"]) if wrapper is not None else None

    def cleanup_candidate(self, candidate_id: str) -> None:
        """Remove successful/terminal processing detail for one candidate."""

        with self._lock:
            candidate_path = self._candidate_path(candidate_id)
            if candidate_path.exists():
                candidate_path.unlink()
            evidence_dir = self._evidence_dir / self._key(candidate_id)
            if evidence_dir.exists():
                shutil.rmtree(evidence_dir)
            for path in self._decision_dir.glob("*.json"):
                wrapper = self._read_wrapper(path)
                if wrapper is None:
                    continue
                data = dict(wrapper["data"])
                if str(data.get("candidate_id") or "") == candidate_id:
                    path.unlink()
            self._prune_empty_directories()

    def cleanup_workspace(self, workspace_id: str) -> int:
        """Remove all processing detail belonging to a terminal job."""

        candidate_ids: list[str] = []
        for path in self._candidate_dir.glob("*.json"):
            wrapper = self._read_wrapper(path)
            if wrapper is not None and wrapper["workspace_id"] == workspace_id:
                candidate_ids.append(str(dict(wrapper["data"])["id"]))
        for candidate_id in candidate_ids:
            self.cleanup_candidate(candidate_id)
        return len(candidate_ids)

    def prune_expired(self, *, ttl_seconds: int, now: datetime | None = None) -> int:
        """Remove abandoned work older than the configured retry/diagnosis TTL."""

        if ttl_seconds < 0:
            raise ValueError("ttl_seconds must be non-negative")
        current = now or _utc_now()
        expired: list[str] = []
        for path in self._candidate_dir.glob("*.json"):
            wrapper = self._read_wrapper(path)
            if wrapper is None:
                continue
            updated = datetime.fromisoformat(str(wrapper["updated_at"]))
            if (current - updated).total_seconds() > ttl_seconds:
                expired.append(str(dict(wrapper["data"])["id"]))
        for candidate_id in expired:
            self.cleanup_candidate(candidate_id)
        return len(expired)

    def _workspace_from_candidate_evidence(self, candidate_id: str) -> str | None:
        evidence = self.list_evidence(candidate_id)
        for item in evidence:
            if item.distill_job_id:
                return item.distill_job_id
        return None

    @staticmethod
    def _key(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def _candidate_path(self, candidate_id: str) -> Path:
        return self._candidate_dir / f"{self._key(candidate_id)}.json"

    def _evidence_path(self, candidate_id: str, evidence_id: str) -> Path:
        return (
            self._evidence_dir
            / self._key(candidate_id)
            / f"{self._key(evidence_id)}.json"
        )

    def _decision_path(self, decision_id: str) -> Path:
        return self._decision_dir / f"{self._key(decision_id)}.json"

    @staticmethod
    def _read_wrapper(path: Path) -> dict | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise ValueError(f"invalid knowledge job record: {path}") from error
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("data"), dict)
            or not str(payload.get("workspace_id") or "").strip()
        ):
            raise ValueError(f"invalid knowledge job record: {path}")
        return payload

    @classmethod
    def _list_models(cls, directory: Path, model: type[T]) -> list[T]:
        if not directory.is_dir():
            return []
        records: list[T] = []
        for path in sorted(directory.glob("*.json")):
            wrapper = cls._read_wrapper(path)
            if wrapper is not None:
                records.append(model.from_dict(dict(wrapper["data"])))
        return records

    @staticmethod
    def _write_wrapper(path: Path, workspace_id: str, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "workspace_id": workspace_id,
            "updated_at": _utc_now().isoformat(),
            "data": data,
        }
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid4().hex}.tmp")
        try:
            with temporary.open("w", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def _prune_empty_directories(self) -> None:
        for directory in (self._evidence_dir, self._candidate_dir, self._decision_dir):
            if directory.is_dir() and not any(directory.iterdir()):
                directory.rmdir()
        if self.root.is_dir() and not any(self.root.iterdir()):
            self.root.rmdir()
        parent = self.root.parent
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


__all__ = ["KnowledgeJobWorkspace"]
