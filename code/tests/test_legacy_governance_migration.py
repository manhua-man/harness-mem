from __future__ import annotations

import asyncio
from pathlib import Path

from harness_mem.commands.doctor import legacy_accepted_status_report
from harness_mem.core.schemas import MemoryEntry, RelationFact
from harness_mem.event_log import iter_state_events
from harness_mem.governance_status import LEGACY_ACCEPTED_STATUS
from harness_mem.legacy_governance import migrate_legacy_accepted
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def test_legacy_accepted_migration_is_dry_run_reviewable_and_idempotent(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HARNESS_MEM_DISABLE_EMBEDDINGS", "1")

    async def exercise() -> None:
        backend = LocalMemoryBackend(tmp_path / "data")
        await backend.init()
        try:
            await backend.structured_store.save_memory_entry(
                MemoryEntry(
                    id="legacy-memory",
                    project_name="demo",
                    category="decision",
                    content="Needs human review",
                    source="obs:legacy-memory",
                    status=LEGACY_ACCEPTED_STATUS,
                )
            )
            await backend.structured_store.save_relation_fact(
                RelationFact(
                    id="legacy-relation",
                    project_name="demo",
                    source_entity="api",
                    target_entity="db",
                    relation_type="depends_on",
                    evidence="API depends on DB",
                    source="obs:legacy-relation",
                    status=LEGACY_ACCEPTED_STATUS,
                )
            )
            await backend.structured_store.save_relation_fact(
                RelationFact(
                    id="current-relation",
                    project_name="demo",
                    source_entity="api",
                    target_entity="db",
                    relation_type="depends_on",
                    evidence="API depends on DB",
                    source="obs:current-relation",
                    status="user_confirmed",
                )
            )

            preview = await migrate_legacy_accepted(
                backend,
                project_name="demo",
                apply=False,
            )
            before = await legacy_accepted_status_report(
                backend.structured_store,
                "demo",
            )
            assert preview["dry_run"] is True
            assert preview["found"] == 2
            assert preview["by_target"] == {"pending": 1, "superseded": 1}
            assert preview["automatic_truth_promotion"] is False
            assert before["total"] == 2

            applied = await migrate_legacy_accepted(
                backend,
                project_name="demo",
                apply=True,
            )
            after = await legacy_accepted_status_report(
                backend.structured_store,
                "demo",
            )
            memory = backend.structured_store.read_record_payload(
                "memory_entries",
                "legacy-memory",
            )
            relation = backend.structured_store.read_record_payload(
                "relation_facts",
                "legacy-relation",
            )
            assert applied["applied"] == 2
            assert after["total"] == 0
            assert memory["status"] == "pending"
            assert relation["status"] == "superseded"
            assert relation["superseded_by"] == ["current-relation"]
            assert memory["legacy_accepted_migration"]["previous_status"] == "accepted"
            assert memory["legacy_accepted_migration"]["decision"] == "pending"
            assert all(
                item["target_status"] not in {"auto_confirmed", "user_confirmed"}
                for item in applied["items"]
            )
            events = list(iter_state_events(backend.data_dir, project_name="demo"))
            migrated_events = [
                event
                for event in events
                if event.get("source_surface")
                == "maintenance.migrate-legacy-accepted"
            ]
            assert len(migrated_events) == 2
            assert all(
                event["payload"]["automatic_truth_promotion"] is False
                for event in migrated_events
            )

            repeated = await migrate_legacy_accepted(
                backend,
                project_name="demo",
                apply=True,
            )
            assert repeated["found"] == 0
            assert repeated["applied"] == 0
        finally:
            await backend.close()

    asyncio.run(exercise())
