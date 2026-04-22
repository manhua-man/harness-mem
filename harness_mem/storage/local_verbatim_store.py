"""LocalVerbatimStore — JSON + SQLite implementation of VerbatimStore."""

from __future__ import annotations
import json
import asyncio
from pathlib import Path

from harness_mem.core.interfaces.verbatim_store import VerbatimStore
from harness_mem.core.schemas.observation import Observation
from harness_mem.storage.sqlite_index import SQLiteIndex


class LocalVerbatimStore:
    """Verbatim store backed by JSON blobs + SQLite FTS index.

    raw_content is stored as individual JSON files under data_dir/verbatim/{id}.json
    Metadata and FTS index live in data_dir/verbatim_index.sqlite
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.blob_dir = self.data_dir / "verbatim"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._index = SQLiteIndex(self.data_dir / "verbatim_index.sqlite")
        self._index.init_db()

    async def save(self, observation: Observation) -> str:
        """Save an observation — blob to JSON, metadata to SQLite."""
        # Write raw_content blob
        blob_path = self.blob_dir / f"{observation.id}.json"
        blob_path.write_text(json.dumps(observation.to_dict(), indent=2, default=str))

        # Index metadata for search
        await asyncio.to_thread(
            self._index.insert,
            "observations",
            {
                "id": observation.id,
                "session_id": observation.session_id,
                "client": observation.client,
                "content_type": observation.content_type,
                "raw_content": observation.raw_content,
                "timestamp": observation.timestamp,
                "tags": observation.tags,
                "metadata": observation.metadata,
            },
        )
        return observation.id

    async def get(self, id: str) -> Observation | None:
        """Get by id — read blob, then enrich with SQLite metadata."""
        blob_path = self.blob_dir / f"{id}.json"
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return Observation.from_dict(data)

    async def list(
        self,
        session_id: str | None = None,
        limit: int = 100,
    ) -> list[Observation]:
        """List observations, optionally filtered by session_id."""
        where = "session_id = ?"
        params = (session_id,) if session_id else ()
        rows = await asyncio.to_thread(
            self._index.list,
            "observations",
            where if session_id else None,
            params,
            order_by="timestamp DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self.blob_dir / f"{row['id']}.json"
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Observation.from_dict(data))
        return results

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        limit: int = 20,
    ) -> list[Observation]:
        """Full-text search observations."""
        extra_where = "session_id = ?" if session_id else None
        extra_params = (session_id,) if session_id else ()
        rows = await asyncio.to_thread(
            self._index.search,
            "observations",
            query,
            limit,
            extra_where,
            extra_params,
        )
        results = []
        for row in rows:
            blob_path = self.blob_dir / f"{row['id']}.json"
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Observation.from_dict(data))
        return results

    async def delete(self, id: str) -> bool:
        """Delete observation blob and SQLite index entry."""
        blob_path = self.blob_dir / f"{id}.json"
        deleted_index = await asyncio.to_thread(self._index.delete, "observations", id)
        deleted_blob = False
        if blob_path.exists():
            blob_path.unlink()
            deleted_blob = True
        return deleted_index or deleted_blob

    async def timeline(
        self,
        project_name: str | None = None,
        limit: int = 50,
    ) -> list[Observation]:
        """Timeline — all observations ordered by timestamp."""
        # project_name filter not applicable at verbatim layer (no project_name field)
        rows = await asyncio.to_thread(
            self._index.list,
            "observations",
            order_by="timestamp DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self.blob_dir / f"{row['id']}.json"
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                results.append(Observation.from_dict(data))
        return results

    def close(self) -> None:
        self._index.close()
