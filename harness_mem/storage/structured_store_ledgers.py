"""Dream, metabolism, and retrieval ledgers for LocalStructuredStore."""

# The concrete LocalStructuredStore supplies persistence primitives and sibling
# capability methods through composition. Contract tests exercise the complete host.
# mypy: disable-error-code="attr-defined"

from __future__ import annotations
import json
import asyncio
from datetime import datetime

from harness_mem.core.schemas.metabolism_run import MetabolismRun
from harness_mem.core.schemas.dream_run import DreamRun
from harness_mem.core.schemas.retrieval_signal import RetrievalSignal


class StructuredLedgerMixin:
    async def save_metabolism_run(self, run: MetabolismRun) -> str:
        """Persist a metabolism run record. Returns run id."""
        blob_path = self._blob_path("metabolism_runs", run.id)
        blob_path.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.insert,
            "metabolism_runs",
            {
                "id": run.id,
                "project_name": run.project_name,
                "kind": run.kind,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
                "status": run.status,
                "duration_ms": run.duration_ms,
            },
        )
        return run.id

    async def list_metabolism_runs(
        self,
        project_name: str,
        *,
        limit: int = 50,
        kind: str | None = None,
    ) -> list[MetabolismRun]:
        """List metabolism runs for project, newest first.

        ``kind`` filters to ``"preview"`` or ``"metabolism"`` when set.
        """
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if kind is not None:
            where_parts.append("kind = ?")
            params.append(kind)
        rows = await asyncio.to_thread(
            self._index.list,
            "metabolism_runs",
            " AND ".join(where_parts),
            tuple(params),
            order_by="started_at DESC",
            limit=limit,
        )
        results: list[MetabolismRun] = []
        for row in rows:
            blob_path = self._blob_path("metabolism_runs", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(MetabolismRun.from_dict(data))
        return results

    # ---- DreamRun ----

    async def save_dream_run(self, run: DreamRun) -> str:
        """Persist a dream run ledger record. Returns run id."""
        blob_path = self._blob_path("dream_runs", run.id)
        blob_path.write_text(json.dumps(run.to_dict(), indent=2, default=str))
        row = {
            "id": run.id,
            "project_name": run.project_name,
            "started_at": run.started_at,
            "completed_at": run.completed_at,
            "status": run.status,
            "trigger_source": run.trigger_source,
            "reflection_job_id": run.reflection_job_id,
            "policy_version": run.policy_version,
            "duration_ms": run.duration_ms,
        }
        if self._index.get("dream_runs", run.id) is None:
            await asyncio.to_thread(self._index.insert, "dream_runs", row)
        else:
            await asyncio.to_thread(self._index.update, "dream_runs", run.id, row)
        return run.id

    async def get_dream_run(self, id: str) -> DreamRun | None:
        blob_path = self._blob_path("dream_runs", id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return DreamRun.from_dict(data)

    async def list_dream_runs(
        self,
        project_name: str,
        *,
        limit: int = 20,
    ) -> list[DreamRun]:
        rows = await asyncio.to_thread(
            self._index.list,
            "dream_runs",
            "project_name = ?",
            (project_name,),
            order_by="started_at DESC",
            limit=limit,
        )
        results: list[DreamRun] = []
        for row in rows:
            blob_path = self._blob_path("dream_runs", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(DreamRun.from_dict(data))
        return results

    # ---- RetrievalSignal ----

    async def save_retrieval_signal(self, signal: RetrievalSignal) -> str:
        """Persist a retrieval signal record. Returns signal id."""
        blob_path = self._blob_path("retrieval_signals", signal.id)
        blob_path.write_text(json.dumps(signal.to_dict(), indent=2, default=str))
        await asyncio.to_thread(
            self._index.upsert,
            "retrieval_signals",
            {
                "id": signal.id,
                "project_name": signal.project_name,
                "signal_type": signal.signal_type,
                "target_kind": signal.target_kind,
                "target_id": signal.target_id,
                "recorded_at": signal.recorded_at,
                "value": signal.value,
            },
        )
        return signal.id

    async def query_retrieval_signals(
        self,
        project_name: str,
        *,
        signal_type: str | None = None,
        target_kind: str | None = None,
        target_id: str | None = None,
        since: datetime | None = None,
        limit: int = 1000,
    ) -> list[RetrievalSignal]:
        """Query retrieval signals by filters; newest first.

        Used by the replay-window selector — ``target_id`` filter exists so
        selectors can ask "how many search_hits for this entry id in the
        last week?".
        """
        where_parts = ["project_name = ?"]
        params: list[str] = [project_name]
        if signal_type is not None:
            where_parts.append("signal_type = ?")
            params.append(signal_type)
        if target_kind is not None:
            where_parts.append("target_kind = ?")
            params.append(target_kind)
        if target_id is not None:
            where_parts.append("target_id = ?")
            params.append(target_id)
        if since is not None:
            where_parts.append("recorded_at >= ?")
            params.append(since.isoformat())
        rows = await asyncio.to_thread(
            self._index.list,
            "retrieval_signals",
            " AND ".join(where_parts),
            tuple(params),
            order_by="recorded_at DESC",
            limit=limit,
        )
        results: list[RetrievalSignal] = []
        for row in rows:
            blob_path = self._blob_path("retrieval_signals", row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(RetrievalSignal.from_dict(data))
        return results
