from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harness_mem.storage.sqlite_index import SQLiteIndex


@pytest.mark.parametrize("row_count", [1_000, 10_000])
def test_fts_retrieval_at_declared_scale(tmp_path: Path, row_count: int) -> None:
    """1k/10k deterministic corpus gate for the local derived read model."""

    index = SQLiteIndex(tmp_path / f"scale-{row_count}.sqlite")
    index.init_db()
    now = datetime.now(timezone.utc).isoformat()
    needle_id = f"scale-memory-{row_count - 1}"
    rows = [
        {
            "id": f"scale-memory-{value}",
            "project_name": "scale-project",
            "category": "decision",
            "content": (
                f"scale corpus row {value} ordinary filler"
                if value != row_count - 1
                else f"scale corpus row {value} unique-needle-{row_count}"
            ),
            "confidence": 0.9,
            "status": "user_confirmed",
            "source": "benchmark:scale",
            "created_at": now,
            "updated_at": now,
            "tags": [],
            "compacted": 0,
            "usage_count": 0,
            "last_accessed_at": None,
            "memory_type": "semantic",
            "valid_from": now,
            "valid_to": None,
            "recorded_at": now,
            "supersedes": [],
            "superseded_by": [],
        }
        for value in range(row_count)
    ]
    try:
        assert index.bulk_upsert("memory_entries", rows) == row_count
        hits = index.search(
            "memory_entries",
            f"unique needle {row_count}",
            limit=5,
            extra_where="project_name = ?",
            extra_params=("scale-project",),
        )
        assert [row["id"] for row in hits] == [needle_id]
    finally:
        index.close()
