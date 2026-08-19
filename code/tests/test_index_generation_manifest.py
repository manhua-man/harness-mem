from __future__ import annotations

from pathlib import Path

from harness_mem.storage.sqlite_index import SQLiteIndex


def test_index_generation_manifest_publishes_one_active_generation(
    tmp_path: Path,
) -> None:
    index = SQLiteIndex(tmp_path / "index.sqlite")
    index.init_db()
    ids = ["entry-a", "entry-b"]
    id_hash = index.stable_id_hash(ids)

    staged = index.record_index_generation(
        index_name="vec0",
        source_generation="canonical:one",
        row_count=2,
        id_hash=id_hash,
        model_id="model-a",
        dimensions=384,
        metadata={"build": "staged"},
    )
    assert staged["status"] == "staged"
    assert index.get_active_index_generation("vec0") is None

    active = index.record_index_generation(
        index_name="vec0",
        source_generation="canonical:one",
        row_count=2,
        id_hash=id_hash,
        model_id="model-a",
        dimensions=384,
        metadata={"build": "complete"},
        activate=True,
    )
    assert active["status"] == "active"
    current = index.get_active_index_generation("vec0")
    assert current is not None
    assert current["generation_id"] == active["generation_id"]
    assert current["metadata"] == {"build": "complete"}
    assert index.validate_index_generation(
        "vec0",
        row_count=2,
        id_hash=id_hash,
        model_id="model-a",
        dimensions=384,
    )["has_issue"] is False


def test_index_generation_manifest_fails_closed_on_membership_or_dimension_drift(
    tmp_path: Path,
) -> None:
    index = SQLiteIndex(tmp_path / "index.sqlite")
    index.init_db()
    index.record_index_generation(
        index_name="fts",
        source_generation="canonical:two",
        row_count=3,
        id_hash=index.stable_id_hash(["one", "two", "three"]),
        activate=True,
    )

    report = index.validate_index_generation(
        "fts",
        row_count=2,
        id_hash=index.stable_id_hash(["one", "two"]),
    )
    assert report["has_issue"] is True
    assert report["reason"] == "manifest_mismatch"
    assert set(report["mismatches"]) == {"row_count", "id_hash"}

    missing = index.validate_index_generation(
        "trigram",
        row_count=0,
        id_hash=index.stable_id_hash([]),
    )
    assert missing["has_issue"] is True
    assert missing["reason"] == "missing_active_generation"
