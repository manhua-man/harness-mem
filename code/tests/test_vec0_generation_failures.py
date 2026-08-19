from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from harness_mem.storage.sqlite_vec_index import (
    VEC0_TABLE,
    SqliteVecIndex,
)


class _TableBackedVecIndex(SqliteVecIndex):
    """Exercise vec0 publication transactions without the optional extension."""

    def _ensure_vec0_table(
        self,
        conn: sqlite3.Connection,
        dimensions: int,
        *,
        table_name: str = VEC0_TABLE,
    ) -> bool:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {table_name} (
                entry_id TEXT PRIMARY KEY,
                embedding BLOB NOT NULL,
                model_id TEXT NOT NULL
            )
            """
        )
        if table_name == VEC0_TABLE:
            self._vec0_dimension = dimensions
        return True


def _connection(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE vec_embeddings (
            entry_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            model_version TEXT NOT NULL,
            embedding BLOB NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        f"""
        CREATE TABLE {VEC0_TABLE} (
            entry_id TEXT PRIMARY KEY,
            embedding BLOB NOT NULL,
            model_id TEXT NOT NULL
        )
        """
    )
    conn.execute(
        f"INSERT INTO {VEC0_TABLE} VALUES ('old-active', ?, 'demo')",
        (b"old-vector",),
    )
    conn.executemany(
        """
        INSERT INTO vec_embeddings
            (entry_id, model_id, model_version, embedding, created_at)
        VALUES (?, 'demo', 'v1', ?, 1)
        """,
        [
            ("new-a", b"\x00\x00\x80\x3f\x00\x00\x00\x00"),
            ("new-b", b"\x00\x00\x00\x00\x00\x00\x80\x3f"),
        ],
    )
    conn.commit()
    return conn


def _active_ids(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(f"SELECT entry_id FROM {VEC0_TABLE}").fetchall()
    }


@pytest.mark.parametrize(
    "failure_point",
    [
        "after_staging_write",
        "after_staging_validation",
        "after_active_drop",
        "before_publish_commit",
    ],
)
def test_vec0_rebuild_failure_preserves_previous_active_generation(
    tmp_path: Path,
    failure_point: str,
) -> None:
    db_path = tmp_path / f"{failure_point}.sqlite"
    conn = _connection(db_path)
    vec = _TableBackedVecIndex()
    vec.mark_extension_loaded()

    def failpoint(point: str) -> None:
        if point == failure_point:
            raise RuntimeError(f"injected:{point}")

    assert (
        vec.rebuild_from_embeddings(
            conn,
            model_id="demo",
            failpoint=failpoint,
        )
        == 0
    )
    assert _active_ids(conn) == {"old-active"}
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?",
        (f"{VEC0_TABLE}_staging",),
    ).fetchone() is None
    conn.close()

    # Restart recovery must observe the same previous active generation.
    reopened = sqlite3.connect(db_path)
    assert _active_ids(reopened) == {"old-active"}
    reopened.close()


def test_vec0_rebuild_source_change_fails_closed_and_preserves_new_source(
    tmp_path: Path,
) -> None:
    conn = _connection(tmp_path / "source-change.sqlite")
    vec = _TableBackedVecIndex()
    vec.mark_extension_loaded()

    def mutate_source(point: str) -> None:
        if point != "after_staging_validation":
            return
        conn.execute(
            """
            INSERT INTO vec_embeddings
                (entry_id, model_id, model_version, embedding, created_at)
            VALUES ('concurrent-new', 'demo', 'v1', ?, 2)
            """,
            (b"concurrent-vector",),
        )
        conn.commit()

    assert (
        vec.rebuild_from_embeddings(
            conn,
            model_id="demo",
            failpoint=mutate_source,
        )
        == 0
    )
    assert _active_ids(conn) == {"old-active"}
    assert conn.execute(
        "SELECT COUNT(*) FROM vec_embeddings WHERE entry_id = 'concurrent-new'"
    ).fetchone()[0] == 1


def test_vec0_manifest_failure_rolls_back_physical_publish(tmp_path: Path) -> None:
    conn = _connection(tmp_path / "manifest-failure.sqlite")
    vec = _TableBackedVecIndex()
    vec.mark_extension_loaded()

    def fail_manifest(
        _conn: sqlite3.Connection,
        _indexed: int,
        _ids: tuple[str, ...],
        _dimensions: int,
        _content_hash: str,
    ) -> None:
        raise sqlite3.IntegrityError("injected manifest failure")

    assert (
        vec.rebuild_from_embeddings(
            conn,
            model_id="demo",
            publish_generation=fail_manifest,
        )
        == 0
    )
    assert _active_ids(conn) == {"old-active"}


def test_vec0_success_publishes_manifest_callback_in_same_transaction(
    tmp_path: Path,
) -> None:
    conn = _connection(tmp_path / "success.sqlite")
    conn.execute(
        "CREATE TABLE published_generation (id_hash TEXT, row_count INTEGER)"
    )
    conn.commit()
    vec = _TableBackedVecIndex()
    vec.mark_extension_loaded()

    def publish(
        publish_conn: sqlite3.Connection,
        indexed: int,
        ids: tuple[str, ...],
        _dimensions: int,
        _content_hash: str,
    ) -> None:
        publish_conn.execute(
            "INSERT INTO published_generation VALUES (?, ?)",
            ("|".join(ids), indexed),
        )

    assert (
        vec.rebuild_from_embeddings(
            conn,
            model_id="demo",
            publish_generation=publish,
        )
        == 2
    )
    assert _active_ids(conn) == {"new-a", "new-b"}
    assert conn.execute(
        "SELECT id_hash, row_count FROM published_generation"
    ).fetchone() == ("new-a|new-b", 2)


def test_parallel_vec0_rebuilds_use_isolated_staging_tables(tmp_path: Path) -> None:
    db_path = tmp_path / "parallel.sqlite"
    bootstrap = _connection(db_path)
    bootstrap.close()
    barrier = threading.Barrier(2)
    results: list[int] = []
    errors: list[BaseException] = []

    def worker() -> None:
        conn = sqlite3.connect(db_path, timeout=10)
        vec = _TableBackedVecIndex()
        vec.mark_extension_loaded()
        try:
            results.append(
                vec.rebuild_from_embeddings(
                    conn,
                    model_id="demo",
                    failpoint=lambda point: (
                        barrier.wait(timeout=5)
                        if point == "after_staging_validation"
                        else None
                    ),
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker), threading.Thread(target=worker)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert results == [2, 2]
    check = sqlite3.connect(db_path)
    assert _active_ids(check) == {"new-a", "new-b"}
    assert check.execute(
        "SELECT name FROM sqlite_master WHERE name LIKE 'vec_embeddings_vec0_staging_%'"
    ).fetchall() == []
    check.close()
