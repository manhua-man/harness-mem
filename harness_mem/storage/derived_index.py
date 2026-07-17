"""Derived index boundary for rebuildable SQLite read models."""

from __future__ import annotations

import sqlite3
import builtins
from contextlib import AbstractContextManager
from pathlib import Path
from collections.abc import Callable, Iterable
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class DerivedIndex(Protocol):
    """Public boundary for indexes derived from canonical truth.

    Implementations may use SQLite, FTS, vector rows, or other read models.
    The index is explicitly rebuildable and must not be treated as the source
    of durable truth.
    """

    db_path: Path

    def init_db(self) -> None: ...

    def locked_connection(self) -> AbstractContextManager[sqlite3.Connection]: ...

    def get(self, table: str, id: str) -> dict[str, Any] | None: ...

    def list(
        self,
        table: str,
        where: str | None = None,
        where_params: tuple = (),
        order_by: str = "created_at DESC",
        limit: int = 100,
        offset: int = 0,
    ) -> builtins.list[dict[str, Any]]: ...

    def search(
        self,
        table: str,
        query: str,
        limit: int = 20,
        extra_where: str | None = None,
        extra_params: tuple = (),
    ) -> builtins.list[dict[str, Any]]: ...

    def update(self, table: str, id: str, data: dict[str, Any]) -> bool: ...

    def delete(self, table: str, id: str) -> bool: ...

    def count(
        self,
        table: str,
        where: str | None = None,
        where_params: tuple = (),
    ) -> int: ...

    def persist_embedding(
        self,
        entry_id: str,
        text: str,
        model_id: str,
        model_version: str | None = None,
    ) -> None: ...

    def replace_embeddings_batch(
        self,
        records: Iterable[tuple[str, str]],
        *,
        model_id: str,
        batch_size: int = 32,
        progress: Callable[[int, int], None] | None = None,
    ) -> dict[str, Any]: ...

    def rebuild_vec0_index(self, *, model_id: str) -> int: ...

    def vec0_coverage_report(self, *, model_id: str) -> dict[str, int]: ...
