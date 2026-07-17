from __future__ import annotations

from pathlib import Path

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
