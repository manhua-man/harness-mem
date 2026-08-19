from __future__ import annotations

from pathlib import Path
import sqlite3
import threading

import pytest

from harness_mem.storage.sqlite_index import SQLiteIndex

np = pytest.importorskip("numpy")


class FakeBatchLoader:
    model_version = "fake-1"

    def __init__(self, *, fail_on_call: int | None = None) -> None:
        self.calls: list[list[str]] = []
        self.fail_on_call = fail_on_call

    def encode(self, texts):
        values = list(texts)
        self.calls.append(values)
        if self.fail_on_call == len(self.calls):
            raise RuntimeError("injected batch failure")
        return np.asarray(
            [[float(len(text)), float(index + 1)] for index, text in enumerate(values)],
            dtype=np.float32,
        )


class CallbackBatchLoader(FakeBatchLoader):
    def __init__(self, callback) -> None:
        super().__init__()
        self.callback = callback

    def encode(self, texts):
        result = super().encode(texts)
        self.callback()
        return result


def _seed_old_row(index: SQLiteIndex, entry_id: str = "old") -> None:
    with index.locked_connection() as conn:
        conn.execute(
            """
            INSERT INTO vec_embeddings
            (entry_id, model_id, model_version, embedding, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (entry_id, "demo-model", "old", np.asarray([9.0, 9.0], dtype=np.float32).tobytes(), 1),
        )
        conn.commit()


def test_batch_rebuild_reuses_loader_and_switches_staging_atomically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    loader = FakeBatchLoader()
    monkeypatch.setattr("harness_mem.embedding.get_model_loader", lambda _model_id: loader)
    index = SQLiteIndex(tmp_path / "index.sqlite")
    index.init_db()
    _seed_old_row(index, "id-0")
    _seed_old_row(index, "other-project")
    progress: list[tuple[int, int]] = []

    result = index.replace_embeddings_batch(
        [(f"id-{value}", f"text-{value}") for value in range(5)],
        model_id="demo-model",
        batch_size=2,
        progress=lambda done, total: progress.append((done, total)),
    )

    assert [len(call) for call in loader.calls] == [2, 2, 1]
    assert progress == [(2, 5), (4, 5), (5, 5)]
    assert result["old_count"] == 1
    assert result["new_count"] == 6
    with index.locked_connection() as conn:
        ids = {
            str(row[0])
            for row in conn.execute("SELECT entry_id FROM vec_embeddings").fetchall()
        }
        staging = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='vec_embeddings_staging'"
        ).fetchone()
    assert ids == {"other-project", *(f"id-{value}" for value in range(5))}
    assert staging is None
    index.close()


def test_batch_rebuild_failure_preserves_old_embeddings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    loader = FakeBatchLoader(fail_on_call=2)
    monkeypatch.setattr("harness_mem.embedding.get_model_loader", lambda _model_id: loader)
    index = SQLiteIndex(tmp_path / "index.sqlite")
    index.init_db()
    _seed_old_row(index)

    with pytest.raises(RuntimeError, match="injected batch failure"):
        index.replace_embeddings_batch(
            [(f"id-{value}", f"text-{value}") for value in range(4)],
            model_id="demo-model",
            batch_size=2,
        )

    with index.locked_connection() as conn:
        rows = conn.execute(
            "SELECT entry_id, model_version FROM vec_embeddings"
        ).fetchall()
        staging = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='vec_embeddings_staging'"
        ).fetchone()
    assert [(str(row[0]), str(row[1])) for row in rows] == [("old", "old")]
    assert staging is None
    index.close()


def test_batch_rebuild_rejects_concurrent_target_update(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    db_path = tmp_path / "index.sqlite"
    index = SQLiteIndex(db_path)
    index.init_db()
    _seed_old_row(index, "target")
    concurrent = SQLiteIndex(db_path)
    concurrent.init_db()

    def overwrite_target() -> None:
        with concurrent.locked_connection() as conn:
            conn.execute(
                """
                UPDATE vec_embeddings
                SET model_version = 'concurrent', embedding = ?, created_at = 2
                WHERE entry_id = 'target'
                """,
                (np.asarray([7.0, 7.0], dtype=np.float32).tobytes(),),
            )
            conn.commit()

    loader = CallbackBatchLoader(overwrite_target)
    monkeypatch.setattr("harness_mem.embedding.get_model_loader", lambda _id: loader)

    with pytest.raises(sqlite3.IntegrityError, match="targets changed"):
        index.replace_embeddings_batch(
            [("target", "old batch input")],
            model_id="demo-model",
        )

    with index.locked_connection() as conn:
        row = conn.execute(
            "SELECT model_version, embedding FROM vec_embeddings WHERE entry_id='target'"
        ).fetchone()
        staging = conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'vec_embeddings_staging_%'"
        ).fetchall()
    assert str(row[0]) == "concurrent"
    assert bytes(row[1]) == np.asarray([7.0, 7.0], dtype=np.float32).tobytes()
    assert staging == []
    concurrent.close()
    index.close()


def test_parallel_batch_rebuilds_use_isolated_staging_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HARNESS_MEM_DISABLE_EMBEDDINGS", raising=False)
    db_path = tmp_path / "parallel.sqlite"
    bootstrap = SQLiteIndex(db_path)
    bootstrap.init_db()
    bootstrap.close()
    barrier = threading.Barrier(2)
    monkeypatch.setattr(
        "harness_mem.embedding.get_model_loader",
        lambda _id: FakeBatchLoader(),
    )
    results: list[dict] = []
    errors: list[BaseException] = []

    def worker(entry_id: str) -> None:
        local = SQLiteIndex(db_path)
        local.init_db()
        try:
            results.append(
                local.replace_embeddings_batch(
                    [(entry_id, entry_id)],
                    model_id="demo-model",
                    progress=lambda _done, _total: barrier.wait(timeout=5),
                )
            )
        except BaseException as exc:
            errors.append(exc)
        finally:
            local.close()

    threads = [
        threading.Thread(target=worker, args=("parallel-a",)),
        threading.Thread(target=worker, args=("parallel-b",)),
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not errors
    assert len(results) == 2
    check = SQLiteIndex(db_path)
    check.init_db()
    with check.locked_connection() as conn:
        ids = {
            str(row[0])
            for row in conn.execute("SELECT entry_id FROM vec_embeddings").fetchall()
        }
        staging = conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'vec_embeddings_staging_%'"
        ).fetchall()
    assert ids == {"parallel-a", "parallel-b"}
    assert staging == []
    check.close()
