"""vec0 rebuild and doctor guidance for upgraded stores."""

from __future__ import annotations

from pathlib import Path

import pytest

from harness_mem.storage.sqlite_index import SQLiteIndex


def test_rebuild_vec0_index_clears_coverage_gap(tmp_path: Path) -> None:
    pytest.importorskip("sqlite_vec")

    index = SQLiteIndex(tmp_path / "structured.sqlite")
    index.init_db()
    index._vec_index.mark_extension_loaded()

    model_id = "rebuild-model"
    blob = b"\x00\x00\x80\x3f" + b"\x00" * 4
    conn = index._conn_write()
    conn.execute(
        """
        INSERT INTO vec_embeddings (entry_id, model_id, model_version, embedding, created_at)
        VALUES ('only', ?, 'v1', ?, 1)
        """,
        (model_id, blob),
    )
    conn.commit()

    before = index.vec0_coverage_report(model_id=model_id)
    assert before["vec0_missing"] == 1

    indexed = index.rebuild_vec0_index(model_id=model_id)
    assert indexed == 1

    after = index.vec0_coverage_report(model_id=model_id)
    assert after["vec0_missing"] == 0
    assert after["vec0_indexed"] == 1