"""Host Agent operations for reviewing finished conversations in local storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from harness_mem.agent_runtime import agent_backend
from harness_mem.commands.manual_distill import is_manual_distill_job, manual_job_guard, paused_batch_error
from harness_mem.core.schemas.session_distill import SessionDistillJob
from harness_mem.mcp.distill_handlers import (
    _finalize_call_contract,
    tool_finalize_session_distill,
    tool_prepare_session_distill,
    tool_submit_distill_chunk,
)
from harness_mem.mcp.session_handlers import tool_inspect_sessions
from harness_mem.storage.local_memory_backend import LocalMemoryBackend, resolve_default_data_dir


def _manual_job(backend: LocalMemoryBackend, job_id: str) -> SessionDistillJob:
    job = backend.transcript_store.get_distill_job(job_id)
    if job is None or not job.manual_only or not is_manual_distill_job(backend, job):
        raise ValueError("select the session with Distill.prepare before reviewing its job")
    reason = paused_batch_error(backend, job) or manual_job_guard(backend, job)
    if reason:
        raise ValueError(reason)
    return job


class Distill:
    """All progress lives in the selected data directory, across Agent invocations."""

    def __init__(self, data_dir: str | Path | None = None):
        self.data_dir = Path(data_dir) if data_dir is not None else resolve_default_data_dir()

    def sessions(
        self, *, project_root: str | None = None, clients: list[str] | None = None,
        project_name: str | None = None, archived_only: bool = False, batch_id: str | None = None,
    ) -> dict:
        """Inspect eligible sources and previously frozen batches without opening a writer."""
        return tool_inspect_sessions(
            project_root=project_root, project_name=project_name, clients=clients,
            archived_only=archived_only, batch_id=batch_id, _data_dir=self.data_dir,
        )

    def source(
        self, session: dict, *, project_root: str | None = None,
        offset: int = 0, page_chars: int = 16000,
    ) -> dict:
        """Read a bounded source page from a verified inventory selection."""
        return tool_inspect_sessions(
            action="source", session=session, project_root=project_root,
            offset=offset, page_chars=page_chars, _data_dir=self.data_dir,
        )

    def prepare(
        self, *, sessions: list[dict] | None = None, batch_id: str | None = None,
        project_root: str | None = None, project_name: str | None = None,
        evidence_mode: str = "raw", chunk_limit: int = 1, budget_tokens: int = 3000,
        pause: bool = False, continue_batch: bool = False, retry_failures: bool = False,
        archived_only: bool = False,
    ) -> dict:
        """Freeze a selection, or continue exactly its recorded sources and checkpoints."""
        if (sessions is None) == (batch_id is None) or sessions == [] or batch_id == "":
            raise ValueError("provide a nonempty session selection or an existing batch_id")
        with agent_backend(self.data_dir):
            result = tool_prepare_session_distill(
                batch_sessions=sessions, batch_id=batch_id, project_name=project_name,
                project_root=project_root, evidence_mode=evidence_mode, chunk_limit=chunk_limit,
                budget_tokens=budget_tokens, pause=pause, continue_batch=continue_batch,
                retry_failures=retry_failures, archived_only=archived_only,
            )
        if result.get("success") and result.get("distill_status") == "reviewing" and "finalize_contract" not in result:
            result["finalize_contract"] = _finalize_call_contract(result["distill_job_id"])
        return result

    def checkpoint(self, job_id: str, chunk_id: str, lease_owner: str, result: dict) -> dict:
        """Record the current Agent's completed reading of one leased chunk."""
        with agent_backend(self.data_dir) as backend:
            _manual_job(backend, job_id)
            return tool_submit_distill_chunk(job_id, chunk_id, lease_owner, result)

    def read(
        self, job_id: str, *, exchange_indexes: list[int] | None = None,
        native_evidence: dict[str, Any] | None = None,
    ) -> dict:
        """Return frozen exchange references or verify one page of native evidence."""
        if bool(exchange_indexes) == bool(native_evidence):
            raise ValueError("choose exchange indexes or a prepared native evidence request")
        with agent_backend(self.data_dir) as backend:
            job = _manual_job(backend, job_id)
            if exchange_indexes and job.status != "reviewing":
                raise ValueError("finish reading the selected chunks before requesting review evidence")
            return tool_prepare_session_distill(
                project_name=job.project_name, project_root=job.project_root,
                distill_job_id=job_id, run_ingest=False, drilldown_exchange_indexes=exchange_indexes,
                native_evidence=native_evidence,
            )

    def finish(
        self, job_id: str, *, semantic_review: dict, memory_points: list[dict[str, Any]],
        condition_exclusions: dict[str, str] | None = None,
    ) -> dict:
        """Validate the Agent's decisions, persist supported facts, and report the verified outcome."""
        with agent_backend(self.data_dir) as backend:
            job = _manual_job(backend, job_id)
            return tool_finalize_session_distill(
                job.project_name, job_id, semantic_review, memory_points=memory_points,
                condition_exclusions=condition_exclusions,
            )

    def revisit(self, job_id: str) -> dict:
        """Reopen unresolved judgments against the same reviewed source."""
        with agent_backend(self.data_dir) as backend:
            job = _manual_job(backend, job_id)
            if job.status != "completed":
                raise ValueError("resume the frozen batch to continue an unfinished job")
            return tool_prepare_session_distill(
                project_name=job.project_name, distill_job_id=job_id,
                run_ingest=False, retry_failures=True,
            )

    def cleanup(self, batch_id: str, *, apply: bool = False) -> dict:
        """Preview verified processed sources; apply only an explicitly requested deletion."""
        with agent_backend(self.data_dir):
            return tool_prepare_session_distill(
                batch_id=batch_id, cleanup_processed=True, apply_cleanup=apply,
            )
