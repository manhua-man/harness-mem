"""LocalVerbatimStore — JSON + SQLite implementation of VerbatimStore."""

from __future__ import annotations
import builtins
import json
import asyncio
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

from harness_mem.core.schemas.observation import Observation
from harness_mem.search.hybrid_search import HybridSearchLayer
from harness_mem.storage.canonical_store import CanonicalStoreRuntime
from harness_mem.storage.derived_index import DerivedIndex
from harness_mem.storage.sqlite_index import SQLiteIndex

_CJK_ASCII_LEFT_BOUNDARY = re.compile(r"([\u3400-\u9fff])([A-Za-z0-9_])")
_CJK_ASCII_RIGHT_BOUNDARY = re.compile(r"([A-Za-z0-9_])([\u3400-\u9fff])")
_REGEX_META_CHARS = set(r"\.^$*+?{}[]|()")
_SEARCH_SCORE_FIELDS = (
    "_fts_score",
    "_fts_score_total",
    "_fts_match_count",
    "_fts_rank",
    "_vec_rank",
    "_vec_sim",
    "_fts_factor",
    "_vec_factor",
    "_rrf_score",
    "_hybrid_score",
    "_score",
)


def _copy_search_score_fields(data: dict[str, Any], row: dict[str, Any]) -> None:
    for field in _SEARCH_SCORE_FIELDS:
        if field in row:
            data[field] = row[field]


class RegexObservationMatch(NamedTuple):
    observation: Observation
    snippet: str
    match_start: int
    match_end: int
    candidate_count: int


class _CanonicalVerbatimBlobPath:
    """Path-like shim that stores observations in canonical SQLite truth."""

    def __init__(self, store: "LocalVerbatimStore", observation_id: str):
        self._store = store
        self._observation_id = observation_id

    def exists(self) -> bool:
        canonical = self._store._canonical
        return bool(canonical and canonical.payload_exists("observations", self._observation_id))

    def read_text(self, *_args, **_kwargs) -> str:
        canonical = self._store._canonical
        if canonical is None:
            raise FileNotFoundError(self._observation_id)
        payload_json = canonical.get_payload_json("observations", self._observation_id)
        if payload_json is None:
            raise FileNotFoundError(self._observation_id)
        return payload_json

    def write_text(self, data: str, *_args, **_kwargs) -> int:
        canonical = self._store._canonical
        if canonical is None:
            raise RuntimeError("canonical runtime is not enabled")
        payload = json.loads(data)
        canonical.upsert_payload(
            "observations",
            self._observation_id,
            payload,
            source_relpath=self._store._canonical_source_relpath(self._observation_id),
        )
        return len(data)

    def unlink(self) -> None:
        canonical = self._store._canonical
        if canonical is None:
            raise FileNotFoundError(self._observation_id)
        if not canonical.delete_payload("observations", self._observation_id):
            raise FileNotFoundError(self._observation_id)


class LocalVerbatimStore:
    """Verbatim store backed by JSON blobs + SQLite FTS index.

    raw_content is stored as individual JSON files under data_dir/verbatim/{id}.json
    Metadata and FTS index live in data_dir/verbatim_index.sqlite
    """

    def __init__(self, data_dir: Path, *, canonical_mode: bool = True):
        self.data_dir = Path(data_dir)
        self.canonical_mode = canonical_mode
        self._canonical = CanonicalStoreRuntime(self.data_dir) if canonical_mode else None
        self.blob_dir = self.data_dir / "verbatim"
        self.blob_dir.mkdir(parents=True, exist_ok=True)
        self._index = SQLiteIndex(self.data_dir / "verbatim_index.sqlite")
        self._index.init_db()
        self._search = HybridSearchLayer(self._index)

    @property
    def index(self) -> DerivedIndex:
        """Shared derived index owned by this store's lifecycle."""

        return self._index

    async def init_runtime(self) -> None:
        if not self.canonical_mode or self._canonical is None:
            return
        canonical_count = self._canonical.count("observations")
        if canonical_count <= 0:
            return
        indexed_count = await asyncio.to_thread(self._index.count, "observations")
        if indexed_count < canonical_count:
            for payload in self._canonical.list_payloads("observations"):
                observation_id = str(payload.get("id") or "")
                if not observation_id:
                    continue
                if await asyncio.to_thread(self._index.get, "observations", observation_id) is None:
                    await self.save(Observation.from_dict(payload))
        for payload in self._canonical.list_payloads("observations"):
            observation_id = str(payload.get("id") or "")
            raw_content = str(payload.get("raw_content") or "")
            if observation_id and raw_content:
                await asyncio.to_thread(
                    self._index.replace_observation_trigrams,
                    observation_id,
                    raw_content,
                )

    def _blob_path(self, observation_id: str) -> Path | _CanonicalVerbatimBlobPath:
        if self.canonical_mode:
            return _CanonicalVerbatimBlobPath(self, observation_id)
        return self.blob_dir / f"{observation_id}.json"

    @staticmethod
    def _canonical_source_relpath(observation_id: str) -> str:
        return f"verbatim/{observation_id}.json"

    async def save(self, observation: Observation) -> str:
        """Save an observation — blob to JSON, metadata to SQLite."""
        # Write raw_content blob
        blob_path = self._blob_path(observation.id)
        blob_path.write_text(json.dumps(observation.to_dict(), indent=2, default=str))

        # Index metadata for search
        await asyncio.to_thread(
            self._index.upsert,
            "observations",
            {
                "id": observation.id,
                "session_id": observation.session_id,
                "client": observation.client,
                "content_type": observation.content_type,
                "raw_content": _normalize_observation_search_text(observation.raw_content),
                "timestamp": observation.timestamp,
                "tags": observation.tags,
                "metadata": observation.metadata,
                "compacted": observation.compacted,
            },
        )
        await asyncio.to_thread(
            self._index.replace_observation_trigrams,
            observation.id,
            observation.raw_content,
        )

        # Persist embedding vector (v1.6.2)
        try:
            from harness_mem.commands.support import get_embedding_model_id

            model_id = get_embedding_model_id()
            await asyncio.to_thread(
                self._index.persist_embedding,
                observation.id,
                observation.raw_content,
                model_id,
            )
        except Exception:
            # Embedding persistence is best-effort, don't fail the save
            pass

        return observation.id

    async def get(self, id: str) -> Observation | None:
        """Get by id — read blob, then enrich with SQLite metadata."""
        blob_path = self._blob_path(id)
        if not blob_path.exists():
            return None
        data = json.loads(blob_path.read_text())
        return Observation.from_dict(data)

    async def list(
        self,
        session_id: str | None = None,
        limit: int = 100,
        project_name: str | None = None,
    ) -> builtins.list[Observation]:
        """List observations, optionally filtered by session or project."""
        where_parts = ["COALESCE(compacted, 0) = 0"]
        params: tuple = ()
        if session_id:
            where_parts.append("session_id = ?")
            params = (*params, session_id)
        if project_name:
            where_parts.append("metadata LIKE ?")
            params = (*params, self._project_metadata_pattern(project_name))
        rows = await asyncio.to_thread(
            self._index.list,
            "observations",
            " AND ".join(where_parts),
            params,
            order_by="timestamp DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path(row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                results.append(Observation.from_dict(data))
        return results

    async def search(
        self,
        query: str,
        session_id: str | None = None,
        project_name: str | None = None,
        limit: int = 20,
        mode: str = "auto",
        time_window: tuple[datetime | None, datetime | None] | None = None,
    ) -> builtins.list[Observation]:
        """Full-text search observations, optionally filtered by session_id or project_name."""
        extra_where_parts = ["COALESCE(compacted, 0) = 0"]
        extra_params: tuple = ()

        if session_id:
            extra_where_parts.append("session_id = ?")
            extra_params = (*extra_params, session_id)

        if project_name:
            extra_where_parts.append("metadata LIKE ?")
            extra_params = (*extra_params, self._project_metadata_pattern(project_name))

        if time_window:
            start, end = _normalize_time_window(time_window)
            if start is not None:
                extra_where_parts.append("timestamp >= ?")
                extra_params = (*extra_params, start.isoformat())
            if end is not None:
                extra_where_parts.append("timestamp < ?")
                extra_params = (*extra_params, end.isoformat())

        extra_where = " AND ".join(extra_where_parts) if extra_where_parts else None

        search_result = await asyncio.to_thread(
            self._search.search,
            query,
            "observations",
            limit,
            extra_where,
            extra_params,
            mode,
        )
        results = []
        for row in search_result.rows:
            blob_path = self._blob_path(row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                if time_window and not _timestamp_in_window(data.get("timestamp"), time_window):
                    continue
                data.update({
                    "_search_mode": search_result.effective_mode,
                    "_search_requested_mode": search_result.requested_mode,
                    "_search_fallback_reason": search_result.fallback_reason,
                })
                _copy_search_score_fields(data, row)
                results.append(Observation.from_dict(data))
        return results

    async def regex_search_observations(
        self,
        pattern: str,
        *,
        project_name: str | None = None,
        limit: int = 20,
        flags: int = 0,
    ) -> builtins.list[RegexObservationMatch]:
        """Search raw observation text by regex using trigram candidate pruning."""
        compiled = re.compile(pattern, flags)
        literal = _longest_literal_fragment(pattern)
        trigrams = _trigrams(literal) if literal else set()
        candidate_limit = max(limit * 20, 100)
        if trigrams:
            candidate_ids = await asyncio.to_thread(
                self._index.candidate_observation_ids_for_trigrams,
                trigrams,
                limit=candidate_limit,
            )
            if not candidate_ids:
                return []
        else:
            candidate_ids = []

        if not candidate_ids:
            observations = await self.list(limit=candidate_limit)
            candidate_count = len(observations)
        else:
            observations = [
                observation
                for observation_id in candidate_ids
                if (observation := await self.get(observation_id)) is not None
            ]
            candidate_count = len(candidate_ids)

        matches: list[RegexObservationMatch] = []
        for observation in observations:
            if project_name and observation.metadata.get("project_name") != project_name:
                continue
            if observation.compacted:
                continue
            match = compiled.search(observation.raw_content)
            if match is None:
                continue
            matches.append(
                RegexObservationMatch(
                    observation=observation,
                    snippet=_regex_snippet(observation.raw_content, match.start(), match.end()),
                    match_start=match.start(),
                    match_end=match.end(),
                    candidate_count=candidate_count,
                )
            )
            if len(matches) >= limit:
                break
        return matches

    async def delete(self, id: str) -> bool:
        """Delete observation blob and SQLite index entry."""
        blob_path = self._blob_path(id)
        deleted_index = await asyncio.to_thread(self._index.delete, "observations", id)
        await asyncio.to_thread(self._index.delete_observation_trigrams, id)
        deleted_blob = False
        if blob_path.exists():
            blob_path.unlink()
            deleted_blob = True
        return deleted_index or deleted_blob

    async def soft_delete(self, id: str) -> bool:
        """Soft-delete an observation by setting compacted=True."""
        blob_path = self._blob_path(id)
        if not blob_path.exists():
            return False
        data = json.loads(blob_path.read_text())
        data["compacted"] = True
        blob_path.write_text(json.dumps(data, indent=2, default=str))
        await asyncio.to_thread(self._index.delete_observation_trigrams, id)
        await asyncio.to_thread(
            self._index.update,
            "observations",
            id,
            {"compacted": True},
        )
        return True

    async def timeline(
        self,
        project_name: str | None = None,
        limit: int = 50,
    ) -> builtins.list[Observation]:
        """Timeline — all observations ordered by timestamp, optionally filtered by project_name."""
        where_parts = ["COALESCE(compacted, 0) = 0"]
        params: tuple = ()
        if project_name:
            where_parts.append("metadata LIKE ?")
            params = (*params, self._project_metadata_pattern(project_name))
        rows = await asyncio.to_thread(
            self._index.list,
            "observations",
            " AND ".join(where_parts),
            params,
            order_by="timestamp DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path(row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                results.append(Observation.from_dict(data))
        return results

    async def recent_observations(
        self,
        project_name: str,
        since: datetime,
        limit: int,
    ) -> builtins.list[Observation]:
        """Observations for a project recorded at or after ``since``, newest first.

        Mirrors :meth:`timeline` but adds a ``timestamp >= ?`` predicate. Used
        by the v2.3.0 replay-window selector to feed the recent-observations
        dimension. ``since`` is serialized as ISO-8601, matching how
        ``timestamp`` is stored in the SQLite index.
        """
        where_parts = [
            "COALESCE(compacted, 0) = 0",
            "metadata LIKE ?",
            "timestamp >= ?",
        ]
        params: tuple = (
            self._project_metadata_pattern(project_name),
            since.isoformat(),
        )
        rows = await asyncio.to_thread(
            self._index.list,
            "observations",
            " AND ".join(where_parts),
            params,
            order_by="timestamp DESC",
            limit=limit,
        )
        results = []
        for row in rows:
            blob_path = self._blob_path(row["id"])
            if blob_path.exists():
                data = json.loads(blob_path.read_text())
                if data.get("compacted", False):
                    continue
                results.append(Observation.from_dict(data))
        return results

    async def count_recent_observations(
        self,
        project_name: str,
        since: datetime,
    ) -> int:
        """Count non-compacted observations for a project at or after ``since``.

        Companion to :meth:`recent_observations`. The replay-window selector
        uses this when the ``cap+1`` probe has reported truncation, so the
        ``truncated_within_observations: <selected>/<pool>`` note can carry
        the true pool size as the denominator.
        """
        where = "COALESCE(compacted, 0) = 0 AND metadata LIKE ? AND timestamp >= ?"
        params = (
            self._project_metadata_pattern(project_name),
            since.isoformat(),
        )
        return await asyncio.to_thread(
            self._index.count,
            "observations",
            where,
            params,
        )

    async def rebuild_exact_index(self, project_name: str | None = None) -> tuple[int, int]:
        """Rebuild exact-search trigram postings for observations."""
        observations = await self.list(limit=100000)
        indexed = 0
        postings = 0
        for observation in observations:
            if project_name and observation.metadata.get("project_name") != project_name:
                continue
            postings += await asyncio.to_thread(
                self._index.replace_observation_trigrams,
                observation.id,
                observation.raw_content,
            )
            indexed += 1
        return indexed, postings

    def exact_index_stats(self) -> dict[str, int]:
        return self._index.observation_trigram_stats()

    def close(self) -> None:
        if self._canonical is not None:
            self._canonical.close()
        self._index.close()

    @staticmethod
    def _project_metadata_pattern(project_name: str) -> str:
        return f'%"project_name": "{project_name}"%'


def _normalize_observation_search_text(text: str) -> str:
    """Add token boundaries for mixed CJK/ASCII text before FTS indexing."""
    text = _CJK_ASCII_LEFT_BOUNDARY.sub(r"\1 \2", text)
    return _CJK_ASCII_RIGHT_BOUNDARY.sub(r"\1 \2", text)


def _normalize_time_window(
    time_window: tuple[datetime | None, datetime | None],
) -> tuple[datetime | None, datetime | None]:
    start, end = time_window
    return _normalize_datetime(start), _normalize_datetime(end)


def _timestamp_in_window(
    value: object,
    time_window: tuple[datetime | None, datetime | None],
) -> bool:
    timestamp = _normalize_datetime(value)
    if timestamp is None:
        return False
    start, end = _normalize_time_window(time_window)
    if start is not None and timestamp < start:
        return False
    if end is not None and timestamp >= end:
        return False
    return True


def _normalize_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        normalized = value
    elif isinstance(value, str) and value:
        try:
            normalized = datetime.fromisoformat(value)
        except ValueError:
            return None
    else:
        return None
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized


def _trigrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.lower())
    if len(normalized) < 3:
        return {normalized} if normalized else set()
    return {
        normalized[index:index + 3]
        for index in range(0, len(normalized) - 2)
    }


def _longest_literal_fragment(pattern: str) -> str:
    fragments: list[str] = []
    current: list[str] = []
    escaped = False
    for char in pattern:
        if escaped:
            if char in "dDsSwWbBAZ":
                if current:
                    fragments.append("".join(current))
                    current = []
            else:
                current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char in _REGEX_META_CHARS:
            if current:
                fragments.append("".join(current))
                current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    if current:
        fragments.append("".join(current))
    return max((fragment.strip() for fragment in fragments), key=len, default="")


def _regex_snippet(text: str, start: int, end: int, *, max_chars: int = 220) -> str:
    context = max_chars // 3
    snippet_start = max(0, start - context)
    snippet_end = min(len(text), max(end + context, snippet_start + max_chars))
    if snippet_end - snippet_start > max_chars:
        snippet_end = snippet_start + max_chars
    snippet = text[snippet_start:snippet_end].replace("\n", " ")
    if snippet_start > 0:
        snippet = "..." + snippet
    if snippet_end < len(text):
        snippet += "..."
    return snippet
