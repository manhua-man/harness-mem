from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import sqlite3

import pytest

from harness_mem.storage import canonical_store as canonical_store_module
from harness_mem.storage.canonical_store import (
    CanonicalTransactionIdempotencyError,
    CanonicalTransactionPreconditionError,
    canonical_store_path,
)
from harness_mem.storage.local_structured_store import LocalStructuredStore


def _entry(entity_id: str, statement: str) -> dict[str, object]:
    return {
        "id": entity_id,
        "project_name": "fixture-project",
        "module_path": ["Storage"],
        "title": f"Knowledge {entity_id}",
        "statement": statement,
        "verified_at": "2026-08-19",
    }


def test_transaction_commits_multiple_collections_on_same_database_inode(tmp_path):
    store = LocalStructuredStore(tmp_path)
    db_path = canonical_store_path(tmp_path)
    store.write_record_payload(
        "knowledge_sources",
        "obsolete-source",
        {
            "id": "obsolete-source",
            "project_name": "fixture-project",
            "knowledge_id": "obsolete",
        },
    )
    inode_before = db_path.stat().st_ino
    try:
        result = store.apply_canonical_payload_transaction(
            idempotency_key="job-1:add-k1",
            mutations=[
                {
                    "operation": "upsert",
                    "collection": "knowledge_entries",
                    "entity_id": "k1",
                    "payload": _entry("k1", "SQLite remains authoritative."),
                    "expected_sha256": None,
                },
                {
                    "operation": "upsert",
                    "collection": "knowledge_sources",
                    "entity_id": "source-k1-1",
                    "payload": {
                        "id": "source-k1-1",
                        "project_name": "fixture-project",
                        "knowledge_id": "k1",
                        "source_kind": "repository",
                        "locator": "src/store.py",
                        "content_sha256": "a" * 64,
                        "verified_at": "2026-08-19",
                    },
                    "expected_sha256": None,
                },
                {
                    "operation": "upsert",
                    "collection": "knowledge_versions",
                    "entity_id": "version-k1-1",
                    "payload": {
                        "id": "version-k1-1",
                        "project_name": "fixture-project",
                        "knowledge_id": "k1",
                        "revision": 1,
                        "statement": "SQLite remains authoritative.",
                    },
                    "expected_sha256": None,
                },
                {
                    "operation": "delete",
                    "collection": "knowledge_sources",
                    "entity_id": "obsolete-source",
                },
            ],
        )

        assert result["mutation_count"] == 4
        assert result["replayed"] is False
        assert store.read_record_payload("knowledge_entries", "k1")["statement"] == (
            "SQLite remains authoritative."
        )
        assert store.record_payload_exists("knowledge_sources", "source-k1-1")
        assert store.record_payload_exists("knowledge_versions", "version-k1-1")
        assert not store.record_payload_exists("knowledge_sources", "obsolete-source")
        assert db_path.stat().st_ino == inode_before
    finally:
        store.close()


def test_precondition_failure_rolls_back_every_mutation(tmp_path):
    store = LocalStructuredStore(tmp_path)
    try:
        initial = store.apply_canonical_payload_transaction(
            idempotency_key="job-2:seed",
            mutations=[
                {
                    "operation": "upsert",
                    "collection": "knowledge_entries",
                    "entity_id": "existing",
                    "payload": _entry("existing", "Original"),
                    "expected_sha256": None,
                }
            ],
        )
        assert initial["mutations"][0]["payload_sha256"]

        with pytest.raises(CanonicalTransactionPreconditionError):
            store.apply_canonical_payload_transaction(
                idempotency_key="job-2:conflict",
                mutations=[
                    {
                        "operation": "upsert",
                        "collection": "knowledge_entries",
                        "entity_id": "new",
                        "payload": _entry("new", "Must not persist"),
                        "expected_sha256": None,
                    },
                    {
                        "operation": "delete",
                        "collection": "knowledge_entries",
                        "entity_id": "existing",
                        "expected_sha256": "0" * 64,
                    },
                ],
            )

        assert not store.record_payload_exists("knowledge_entries", "new")
        assert store.read_record_payload("knowledge_entries", "existing")[
            "statement"
        ] == "Original"
    finally:
        store.close()


def test_idempotent_replay_is_a_noop_and_key_reuse_fails_closed(tmp_path):
    store = LocalStructuredStore(tmp_path)
    mutation = {
        "operation": "upsert",
        "collection": "knowledge_entries",
        "entity_id": "k1",
        "payload": _entry("k1", "One committed value"),
        "expected_sha256": None,
    }
    try:
        first = store.apply_canonical_payload_transaction(
            idempotency_key="job-3:add-k1", mutations=[mutation]
        )
        replay = store.apply_canonical_payload_transaction(
            idempotency_key="job-3:add-k1", mutations=[mutation]
        )

        assert first["replayed"] is False
        assert replay["replayed"] is True
        assert replay["request_sha256"] == first["request_sha256"]
        with sqlite3.connect(canonical_store_path(tmp_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM canonical_transaction_records"
            ).fetchone()[0]
        assert count == 1

        changed = dict(mutation)
        changed["payload"] = _entry("k1", "Different request")
        with pytest.raises(CanonicalTransactionIdempotencyError):
            store.apply_canonical_payload_transaction(
                idempotency_key="job-3:add-k1", mutations=[changed]
            )
        assert store.read_record_payload("knowledge_entries", "k1")[
            "statement"
        ] == "One committed value"
    finally:
        store.close()


def test_runtime_failure_during_apply_leaves_no_partial_mutation(tmp_path, monkeypatch):
    store = LocalStructuredStore(tmp_path)
    original_upsert = canonical_store_module._upsert_canonical_row
    calls = 0

    def fail_second_upsert(conn, row):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("injected write failure")
        return original_upsert(conn, row)

    monkeypatch.setattr(
        canonical_store_module, "_upsert_canonical_row", fail_second_upsert
    )
    try:
        with pytest.raises(RuntimeError, match="injected write failure"):
            store.apply_canonical_payload_transaction(
                idempotency_key="job-4:atomic",
                mutations=[
                    {
                        "operation": "upsert",
                        "collection": "knowledge_entries",
                        "entity_id": "k1",
                        "payload": _entry("k1", "First"),
                    },
                    {
                        "operation": "upsert",
                        "collection": "knowledge_sources",
                        "entity_id": "source-k1-1",
                        "payload": {
                            "id": "source-k1-1",
                            "project_name": "fixture-project",
                            "knowledge_id": "k1",
                        },
                    },
                ],
            )

        assert not store.record_payload_exists("knowledge_entries", "k1")
        assert not store.record_payload_exists("knowledge_sources", "source-k1-1")
        with sqlite3.connect(canonical_store_path(tmp_path)) as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM canonical_transaction_records"
            ).fetchone()[0]
        assert count == 0
    finally:
        store.close()


def test_existing_single_row_writes_are_thread_safe(tmp_path):
    store = LocalStructuredStore(tmp_path)

    def write(index: int) -> None:
        store.write_record_payload(
            "knowledge_sources",
            f"source-{index}",
            {
                "id": f"source-{index}",
                "project_name": "fixture-project",
                "knowledge_id": f"k-{index}",
            },
        )

    try:
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(write, range(40)))
        assert len(store.list_record_payloads("knowledge_sources")) == 40
    finally:
        store.close()
