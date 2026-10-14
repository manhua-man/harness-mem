"""Isolated device memory outcomes over fictional seven-host native sources.

The dispatcher, source validation, jobs, SQLite, Notes and retrieval are real.
Semantic decisions are deterministic fixtures; native apps, Hooks and models
are not run. Former workspace directories are absent before discovery.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from contextlib import ExitStack, closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from harness_mem.adapters.source_inspection import HOSTS, normalized_root
from harness_mem.commands import session_inventory
from harness_mem.commands.evidence_admission import _frozen_user_exchange_indexes
from harness_mem.config.merge import MergedConfig
from harness_mem.embedding.model_loader import temporarily_disable_embeddings
from harness_mem.mcp import server, tool_handlers
from harness_mem.mcp.distill_projection import render_distill_exchange_windows
from harness_mem.qualification.automatic_projects_outcome_probe import (
    _rpc, create_native_fixture,
)
from harness_mem.storage.canonical_store import CanonicalStoreRuntime, canonical_store_path
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


PREFERENCES = {
    "claude-code": "For future collaboration, answer in concise Chinese.",
    "codex": "For future collaboration, keep independently verifiable facts for fourteen days.",
    "cursor": "For future collaboration, include absolute file links in code explanations.",
    "grok": "For future collaboration, report exact test commands.",
    "hermes": "For future collaboration, ask before deleting source conversations.",
    "opencode": "For future collaboration, keep project status separate from test results.",
    "antigravity": "For future collaboration, explain unresolved work explicitly.",
}


def _preference_fixture(root: Path, *, native_containers: bool) -> dict:
    former = root / "former-workspace"
    former.mkdir()
    connections = []
    connect = sqlite3.connect

    def fixture_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    # The older fixture helper commits with connection contexts but does not
    # close them. Close only connections constructed for our temporary fixture.
    try:
        with patch("sqlite3.connect", fixture_connection):
            fixture = create_native_fixture(root, [former], native_containers=native_containers)
    finally:
        for connection in connections:
            connection.close()
    locations = fixture["locations"]
    # Rewrite only this temporary fixture, before taking retention receipts.
    for client, location in locations.items():
        for path in location.rglob("*"):
            if path.suffix not in {".json", ".jsonl"}:
                continue
            text = path.read_text(encoding="utf-8")
            for old in (f"Verify {client}policy0 against policy.txt.", f"Verify {client}policy0."):
                text = text.replace(old, PREFERENCES[client])
            text = text.replace("Reviewed fictional policy.", "Understood your future preference.")
            if client == "cursor" and path.suffix == ".jsonl":
                rows = [json.loads(line) for line in text.splitlines()]
                for row in rows:
                    # Native Cursor message.content is a list of text items.
                    row["message"]["content"] = [{"type": "text", "text": row["message"]["content"]}]
                text = "".join(json.dumps(row) + "\n" for row in rows)
            if client == "antigravity" and path.name == "history.jsonl":
                rows = [json.loads(line) for line in text.splitlines()]
                for row in rows:
                    # The native history entry owns the explicit user display.
                    row["display"] = row.pop("content")
                    row["response"] = "Understood your future preference."
                text = "".join(json.dumps(row) + "\n" for row in rows)
            path.write_text(text, encoding="utf-8")
    with closing(sqlite3.connect(locations["opencode"] / "opencode.db")) as db, db:
        db.execute("UPDATE message SET time_created=2000 WHERE id LIKE '%-assistant'")
        for part_id, content in db.execute("SELECT id, data FROM part").fetchall():
            part = json.loads(content)
            part["text"] = PREFERENCES["opencode"] if part_id.endswith("-user") else "Understood your future preference."
            db.execute("UPDATE part SET data=? WHERE id=?", (json.dumps(part), part_id))
    if native_containers:
        cursor_db = locations["cursor"] / "User" / "globalStorage" / "state.vscdb"
        with closing(sqlite3.connect(cursor_db)) as db, db:
            key = "bubbleId:fixture-cursor-0:user"
            bubble = json.loads(db.execute("SELECT value FROM cursorDiskKV WHERE key=?", (key,)).fetchone()[0])
            bubble["text"] = PREFERENCES["cursor"]
            db.execute("UPDATE cursorDiskKV SET value=? WHERE key=?", (json.dumps(bubble), key))
        with closing(sqlite3.connect(locations["hermes"] / "state.db")) as db, db:
            db.execute("UPDATE messages SET content=? WHERE role='user'", (PREFERENCES["hermes"],))
        (former / "src").rmdir()
    former.rmdir()
    assert not former.exists()
    return fixture


def _sqlite_entries(data_dir: Path) -> list[dict]:
    with closing(CanonicalStoreRuntime(data_dir, read_only=True)) as store:
        return store.list_payloads("knowledge_entries")


def run_device_memory_variant(*, native_containers: bool) -> dict:
    """Use only temporary native containers and the existing public MCP path."""
    with TemporaryDirectory(prefix="hm-device-memory-") as temporary, ExitStack() as stack:
        root = Path(temporary)
        fixture = _preference_fixture(root, native_containers=native_containers)
        originals = {path: path.read_bytes() for path in (root / "native").rglob("*") if path.is_file()}
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        stack.callback(lambda: asyncio.run(backend.close()))
        stack.enter_context(temporarily_disable_embeddings())
        stack.enter_context(patch.object(tool_handlers, "_backend_provider", lambda: backend))
        stack.enter_context(patch.object(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir))
        stack.enter_context(patch.object(tool_handlers, "_cost_surface_budgets_provider", lambda _: None))
        stack.enter_context(patch.object(session_inventory, "load_merged_config", lambda *_: MergedConfig()))
        stack.enter_context(patch.object(session_inventory, "build_inspection_adapter", lambda client: fixture["factories"][client]()))
        stack.enter_context(patch("harness_mem.mcp.distill_handlers._session_notes_dir", lambda _: backend.data_dir / "notes"))
        # A regression must fail before it can launch any background CLI.
        processes = stack.enter_context(patch("subprocess.Popen", side_effect=AssertionError("device probe must not launch a CLI")))
        stack.enter_context(patch.object(session_inventory, "_PAGE_CACHE", OrderedDict()))
        full_reads: list[tuple[str, str]] = []
        reader = session_inventory.inspect_native_source

        def record_read(adapter, client, record, **kwargs):
            full_reads.append((client, record["session_id"]))
            return reader(adapter, client, record, **kwargs)

        stack.enter_context(patch.object(session_inventory, "inspect_native_source", record_read))
        listed = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})
        assert listed is not None and "error" not in listed, listed
        public_names = {tool["name"] for tool in listed["result"]["tools"]}
        assert len(public_names) == 20 and "inspect_sessions" in public_names and "dream_auto_tick" not in public_names
        discovery = _rpc("inspect_sessions", {})
        selected = discovery["sessions"]
        assert len(selected) == len(HOSTS) and {row["client"] for row in selected} == set(HOSTS), discovery
        assert discovery["project_name"] == "global" and discovery["project_root"] == "", discovery
        assert discovery["scope"] == "all", discovery
        assert not full_reads and not list(backend.transcript_store.list_distill_jobs())
        assert not _sqlite_entries(backend.data_dir)
        assert not (backend.data_dir / "profiles").exists()
        assert all(row["scope"] == "all" and not row["revision_verified"] for row in selected), selected

        batch_id = None
        notes = []
        host_results: dict[str, dict[str, bool]] = {}
        order = []
        for index, source in enumerate(selected):
            client, session_id = source["client"], source["session_id"]
            full_reads.clear()
            offset, fragments = 0, []
            while True:
                page = _rpc("inspect_sessions", {"action": "source", "session": source,
                                                 "offset": offset, "page_chars": 37})
                assert page["revision_verified"] and page["verified_session"]["scope"] == "all", page
                fragments.append(page["content"])
                if page["next_offset"] is None:
                    break
                offset = page["next_offset"]
            assert len(fragments) > 1 and PREFERENCES[client] in "".join(fragments)
            assert full_reads == [(client, session_id)], full_reads
            assert len(list(backend.transcript_store.list_distill_jobs())) == index
            packet = _rpc("prepare_session_distill", {"scope": "all", "batch_sessions": selected}
                          if batch_id is None else {"batch_id": batch_id})
            batch_id = packet["batch_id"]
            assert packet["session_id"] == session_id, packet
            job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
            assert job is not None and job.client == client and job.manual_only and job.retain_source
            assert job.project_name == "global" and normalized_root(job.project_root) == normalized_root(source["project_root"]), job
            assert not Path(job.project_root).exists(), job
            assert len(list(backend.transcript_store.list_distill_jobs())) == index + 1
            assert set(full_reads) == {(client, session_id)}, full_reads
            resumed = _rpc("prepare_session_distill", {"batch_id": batch_id})
            assert resumed["distill_job_id"] == job.id
            observation = asyncio.run(backend.verbatim_store.get(str(uuid5(NAMESPACE_URL, f"{job.source_id}:observation"))))
            assert observation is not None
            windows = render_distill_exchange_windows(observation.raw_content, [1])
            assert len(windows) == 1 and PREFERENCES[client] in observation.raw_content, {
                "client": client, "stage": "semantic_exchange_projection",
                "reason": "user_statement_exchange_missing", "hosts_completed": sorted(host_results),
                "windows": windows, "rendering": observation.raw_content,
            }
            if client == "codex":
                # Automatic author validation must still work without a caller role.
                assert _frozen_user_exchange_indexes(backend, source_id=job.source_id,
                    source_revision=job.source_revision, rendering=observation.raw_content) == {1}
            statement = PREFERENCES[client]
            suggestion = _rpc("govern_memory", {"action": "suggest", "arguments": {
                "kind": "memory", "project_name": job.project_name, "category": "preference",
                "content": statement, "source": f"distill-job:{job.id}", "distill_job_id": job.id,
                "canonical_title": f"{client} collaboration preference", "topic_path": ["Preferences"],
                "evidence_basis": "user_statement", "verification_outcome": "verified",
                "verification_refs": [{"kind": "user_statement", "exchange_index": 1,
                                       "content_sha256": windows[0]["content_sha256"], "role": "user"}],
                "assimilation_disposition": "add", "assimilation_reason": "Explicit future collaboration preference.",
            }})
            evidence = asyncio.run(backend.structured_store.knowledge_store.list_evidence(suggestion["entry_id"]))
            assert len(evidence) == 1 and evidence[0].verification_outcome == "verified", {
                "client": client, "evidence": [item.model_dump(mode="json") for item in evidence],
                "rendering": observation.raw_content,
            }
            final = _rpc("finalize_session_distill", {"project_name": job.project_name, "job_id": job.id,
                "semantic_review": {"session_summary": "Verified an explicit future preference.",
                    "final_user_request": statement, "final_outcome": "Saved the verified preference.",
                    "last_turn_status": "answered", "contradictions": [], "unfinished_work": [],
                    "evidence_status": "answered", "promotion_decision": "promote"}})
            assert len(final["knowledge_changes"]) == 1 and final["knowledge_changes"][0]["change"] == "added", final
            note = Path(final["note"]["path"])
            assert note.resolve().is_relative_to(backend.data_dir.resolve()), note
            assert statement in note.read_text(encoding="utf-8")
            assert hashlib.sha256(note.read_bytes()).hexdigest() == final["note"]["sha256"]
            notes.append((note, final["note"]["sha256"]))
            entries = _sqlite_entries(backend.data_dir)
            assert len(entries) == index + 1 and any(entry["statement"] == statement for entry in entries), entries
            host_results[client] = {"complete_source_read": True, "same_job_finalized": True,
                                    "sqlite_persisted": True, "note_verified": True}
            order.append((client, session_id))

        complete = _rpc("prepare_session_distill", {"batch_id": batch_id})
        assert complete["status"] == "completed" and complete["progress"]["completed"] == len(HOSTS), complete
        assert complete["unfinished_work"] == [], complete
        raw_sources = {job.source_id: backend.transcript_store.reconstruct_raw(job.source_id, source_revision=job.source_revision)
                       for job in backend.transcript_store.list_distill_jobs()}
        assert len(raw_sources) == len(HOSTS)
        asyncio.run(backend.close())
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        entries = _sqlite_entries(backend.data_dir)
        current = _rpc("search_memory", {"query": ""})
        assert len(current["memories"]) == len(HOSTS) and current.get("project_name") is None, current
        assert {row["statement"] for row in current["memories"]} == set(PREFERENCES.values()), current
        assert all(set(row) == {"module", "title", "statement", "project_name"} and row["project_name"] == "global"
                   for row in current["memories"]), current
        for client, result in host_results.items():
            found = _rpc("search_memory", {"query": f"{client} collaboration preference"})
            result["retrieved_after_reopen"] = any(row["statement"] == PREFERENCES[client] for row in found["memories"])
        checks = {
            "default_device_inventory": all(row["scope"] == "all" for row in selected),
            "historical_directories_absent": not (root / "former-workspace").exists(),
            "inventory_read_only": all(not row["imported"] and not row["revision_verified"] for row in selected),
            "one_session_at_a_time": order == [(row["client"], row["session_id"]) for row in selected],
            "fixed_batch_completed": complete["status"] == "completed",
            "seven_host_complete_flow": all(all(result.values()) for result in host_results.values()),
            "sqlite_durable_after_reopen": canonical_store_path(backend.data_dir).is_file()
                and len(entries) == len(HOSTS) and {row["statement"] for row in entries} == set(PREFERENCES.values()),
            "default_global_retrieval": current.get("project_name") is None and len(current["memories"]) == len(HOSTS),
            "notes_durable_after_reopen": all(hashlib.sha256(path.read_bytes()).hexdigest() == digest for path, digest in notes),
            "native_sources_retained": all(path.read_bytes() == content for path, content in originals.items()),
            "frozen_sources_retained": all(backend.transcript_store.reconstruct_raw(source_id) == content for source_id, content in raw_sources.items()),
            "manual_retain_source": all(job.manual_only and job.retain_source for job in backend.transcript_store.list_distill_jobs()),
            "no_profiles": not (backend.data_dir / "profiles").exists(),
            "no_background_cli": processes.call_count == 0,
            "public_twenty_tools": len(public_names) == 20,
        }
        return {"verified": all(checks.values()), **checks, "hosts": host_results,
                "semantic_mode": "deterministic_fixture_agent", "native_apps_or_hooks": "not_run"}


def run_device_memory_outcome_probe() -> dict:
    variants = {}
    for name, containers in (("files", False), ("containers_and_archives", True)):
        try:
            variants[name] = run_device_memory_variant(native_containers=containers)
        except AssertionError as exc:
            variants[name] = {"verified": False, "failure": str(exc),
                              "semantic_mode": "deterministic_fixture_agent", "native_apps_or_hooks": "not_run"}
    checked_names = {key for result in variants.values() for key, value in result.items() if isinstance(value, bool)}
    combined = {key: all(result.get(key) is True for result in variants.values()) for key in checked_names}
    return {**combined, "verified": all(result["verified"] for result in variants.values()),
            "native_variant_count": len(variants), "variants": variants,
            "semantic_mode": "deterministic_fixture_agent", "native_apps_or_hooks": "not_run"}


def main() -> int:
    result = run_device_memory_outcome_probe()
    fd = getattr(server, "_REAL_STDOUT_FD", None)
    os.write(fd if fd is not None else 1, (json.dumps(result, sort_keys=True) + "\n").encode("utf-8"))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
