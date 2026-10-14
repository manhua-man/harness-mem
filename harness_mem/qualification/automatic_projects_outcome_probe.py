"""Seven native hosts through automatic discovery and the real manual MCP flow.

Native formats, dispatcher, gates, jobs, SQLite, Notes and ordinary retrieval
are real. Filesystem locations and Agent semantic decisions are fictional and
isolated; this is not a native-app Hook or model-quality qualification.
"""

from __future__ import annotations

import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
from unittest.mock import patch

from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.antigravity.adapter import AntigravityAdapter
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.codex.adapter import CodexAdapter
from harness_mem.adapters.cursor.adapter import CursorAdapter
from harness_mem.adapters.grok.adapter import GrokAdapter, grok_project_bucket
from harness_mem.adapters.hermes.adapter import HermesAdapter
from harness_mem.adapters.opencode.adapter import OpenCodeAdapter
from harness_mem.adapters.source_inspection import HOSTS
from harness_mem.adapters.source_inspection import normalized_root
from harness_mem.adapters.snapshot import persist_session_snapshot
from harness_mem.commands.session_inventory import _PAGE_CACHE, discover_session_projects
from harness_mem.config.merge import MergedConfig
from harness_mem.core.schemas.observation import Observation
from harness_mem.mcp import server, tool_handlers
from harness_mem.storage.local_memory_backend import LocalMemoryBackend


def _jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def create_native_fixture(root: Path, projects: list[Path], *, native_containers: bool = False) -> dict:
    """Native discovery is only redirected to these fictional containers."""
    native = root / "native"
    locations: dict[str, Path] = {client: native / client for client in HOSTS}
    opencode = locations["opencode"] / "opencode.db"
    opencode.parent.mkdir(parents=True)
    with sqlite3.connect(opencode) as db:
        db.executescript("""
            CREATE TABLE session(id TEXT PRIMARY KEY, directory TEXT, title TEXT, time_created INTEGER, time_updated INTEGER);
            CREATE TABLE message(id TEXT PRIMARY KEY, session_id TEXT, time_created INTEGER, data TEXT);
            CREATE TABLE part(id TEXT PRIMARY KEY, message_id TEXT, session_id TEXT, data TEXT);
        """)
        for index, project in enumerate(projects):
            for client in HOSTS:
                sid = f"fixture-{client}-{index}"
                message = f"Verify {client}policy{index} against policy.txt."
                if client == "opencode":
                    db.execute("INSERT INTO session VALUES(?, ?, ?, 1000, 2000)", (sid, str(project), "Fictional policy"))
                    for role in ("user", "assistant"):
                        mid = f"{sid}-{role}"
                        db.execute("INSERT INTO message VALUES(?, ?, 1000, ?)", (mid, sid, json.dumps({"role": role})))
                        db.execute("INSERT INTO part VALUES(?, ?, ?, ?)",
                                   (mid, mid, sid, json.dumps({"type": "text", "text": message if role == "user" else "Reviewed fictional policy."})))
                elif client == "codex":
                    _jsonl(locations[client] / "sessions" / f"rollout-{sid}.jsonl", [
                        {"type": "session_meta", "payload": {"id": sid, "cwd": str(project)}},
                        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": message}]}},
                        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Reviewed fictional policy."}]}},
                    ])
                elif client == "claude-code":
                    _jsonl(locations[client] / f"bucket-{index}" / f"{sid}.jsonl", [
                        {"type": "user", "cwd": str(project), "message": {"role": "user", "content": message}},
                        {"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": "Reviewed fictional policy."}]}},
                    ])
                elif client == "cursor":
                    _jsonl(locations[client] / f"bucket-{index}" / "agent-transcripts" / sid / f"{sid}.jsonl", [
                        {"role": "user", "cwd": str(project), "message": {"content": message}},
                        {"role": "assistant", "message": {"content": "Reviewed fictional policy."}},
                    ])
                elif client == "grok":
                    _jsonl(locations[client] / grok_project_bucket(project.resolve()) / sid / "chat_history.jsonl", [
                        {"type": "user", "cwd": str(project), "content": message},
                        {"type": "assistant", "content": "Reviewed fictional policy."},
                    ])
                elif client == "hermes":
                    path = locations[client] / f"session_{sid}.json"
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(json.dumps({"session_id": sid, "cwd": str(project), "messages": [
                        {"role": "user", "content": message},
                        {"role": "assistant", "content": "Reviewed fictional policy."},
                    ]}), encoding="utf-8")
                elif client == "antigravity":
                    _jsonl(locations[client] / "brain" / sid / ".system_generated" / "logs" / "transcript_full.jsonl", [
                        {"type": "USER_INPUT", "source": "USER_EXPLICIT", "cwd": str(project), "content": message},
                        {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Reviewed fictional policy."},
                    ])
    adapters = {
        "claude-code": lambda: ClaudeCodeAdapter(None, sessions_dir=locations["claude-code"]),
        "codex": lambda: CodexAdapter(None, sessions_dir=locations["codex"] / "sessions", archive_dir=locations["codex"] / "archived_sessions", scope="all"),
        "cursor": lambda: CursorAdapter(None, projects_dir=locations["cursor"], sqlite_databases=()),
        "grok": lambda: GrokAdapter(None, sessions_dir=locations["grok"]),
        "hermes": lambda: HermesAdapter(None, sessions_dir=locations["hermes"]),
        "opencode": lambda: OpenCodeAdapter(None, database_path=opencode),
        "antigravity": lambda: AntigravityAdapter(None, brain_dir=locations["antigravity"] / "brain", cli_root=locations["antigravity"] / "cli"),
    }
    if native_containers:
        user = locations["cursor"] / "User"
        cursor_db = user / "globalStorage" / "state.vscdb"
        cursor_db.parent.mkdir(parents=True)
        workspace_dbs = []
        with sqlite3.connect(cursor_db) as db:
            db.executescript("CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY COLLATE BINARY, value TEXT); CREATE TABLE composerHeaders(composerId TEXT, workspaceId TEXT);")
            for index, project in enumerate(projects):
                sid, workspace_id = f"fixture-cursor-{index}", f"workspace-{index}"
                workspace_db = user / "workspaceStorage" / workspace_id / "state.vscdb"
                workspace_db.parent.mkdir(parents=True)
                (workspace_db.parent / "workspace.json").write_text(json.dumps({"folder": project.resolve().as_uri()}), encoding="utf-8")
                with sqlite3.connect(workspace_db) as workspace:
                    workspace.executescript("CREATE TABLE cursorDiskKV(key TEXT PRIMARY KEY COLLATE BINARY, value TEXT); CREATE TABLE ItemTable(key TEXT PRIMARY KEY, value TEXT);")
                workspace_dbs.append(workspace_db)
                db.execute("INSERT INTO composerHeaders VALUES (?, ?)", (sid, workspace_id))
                db.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"composerData:{sid}", json.dumps({
                    "composerId": sid, "fullConversationHeadersOnly": [{"bubbleId": "user"}, {"bubbleId": "assistant"}],
                })))
                for bubble, bubble_role in (("user", 1), ("assistant", 2)):
                    db.execute("INSERT INTO cursorDiskKV VALUES (?, ?)", (f"bubbleId:{sid}:{bubble}", json.dumps({
                        "bubbleId": bubble, "type": bubble_role, "text": f"Verify cursorpolicy{index}." if bubble_role == 1 else "Reviewed fictional policy.",
                    })))
        adapters["cursor"] = lambda: CursorAdapter(None, projects_dir=locations["cursor"] / "unused-jsonl",
                                                  sqlite_databases=(cursor_db, *workspace_dbs))
        hermes_db = locations["hermes"] / "state.db"
        with sqlite3.connect(hermes_db) as db:
            db.executescript("""
                CREATE TABLE sessions(id TEXT PRIMARY KEY, title TEXT, source TEXT, started_at REAL, ended_at REAL,
                    message_count INTEGER, cwd TEXT, git_repo_root TEXT, model TEXT, archived INTEGER);
                CREATE TABLE messages(id INTEGER PRIMARY KEY, session_id TEXT, role TEXT, content TEXT, tool_name TEXT, active INTEGER);
            """)
            for index, project in enumerate(projects):
                sid = f"fixture-hermes-{index}"
                child = project / "src"
                child.mkdir(exist_ok=True)
                db.execute("INSERT INTO sessions VALUES (?, 'Fictional archived session', 'cli', 1000, 1100, 2, ?, ?, 'fixture', 1)",
                           (sid, str(child), str(project)))
                db.execute("INSERT INTO messages(session_id,role,content,active) VALUES (?, 'user', ?, 1)", (sid, f"Verify hermespolicy{index}."))
                db.execute("INSERT INTO messages(session_id,role,content,active) VALUES (?, 'assistant', 'Reviewed fictional policy.', 1)", (sid,))
        adapters["hermes"] = lambda: HermesAdapter(None, sessions_dir=locations["hermes"] / "unused-json", state_db=hermes_db)
        cli = locations["antigravity"] / "cli"
        _jsonl(cli / "history.jsonl", [
            {"conversationId": f"fixture-antigravity-{index}", "workspace": str(project), "timestamp": 1000,
             "role": "user", "content": f"Verify antigravitypolicy{index}."}
            for index, project in enumerate(projects)
        ])
        for index, project in enumerate(projects):
            sid = f"fixture-antigravity-{index}"
            _jsonl(cli / "brain" / sid / ".system_generated" / "logs" / "transcript_full.jsonl", [
                {"type": "USER_INPUT", "source": "USER_EXPLICIT", "cwd": str(project / "src"), "content": f"Verify antigravitypolicy{index}."},
                {"type": "PLANNER_RESPONSE", "source": "MODEL", "content": "Reviewed fictional policy."},
            ])
            source = locations["codex"] / "sessions" / f"rollout-fixture-codex-{index}.jsonl"
            archive = locations["codex"] / "archived_sessions" / source.name
            archive.parent.mkdir(parents=True, exist_ok=True)
            archive.write_bytes(source.read_bytes())
        adapters["antigravity"] = lambda: AntigravityAdapter(None, brain_dir=locations["antigravity"] / "unused-brain", cli_root=cli)
        adapters["codex"] = lambda: CodexAdapter(None, sessions_dir=locations["codex"] / "unused-current",
                                                archive_dir=locations["codex"] / "archived_sessions", scope="all")
    return {"factories": adapters, "locations": locations}


def _rpc(name: str, arguments: dict) -> dict:
    response = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                      "params": {"name": name, "arguments": arguments}})
    assert response is not None and "error" not in response, response
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload.get("success", True), payload
    return payload


def _run_native_variant(*, native_containers: bool) -> dict:
    with TemporaryDirectory(prefix="hm-auto-projects-") as temporary, ExitStack() as stack:
        root = Path(temporary)
        projects = [root / "alpha" / "project", root / "beta" / "project"]
        for index, project in enumerate(projects):
            project.mkdir(parents=True)
            (project / "policy.txt").write_text("\n".join(
                f"{client}policy{index}: Keep only verified current cache entries for workspace {index}."
                for client in HOSTS
            ), encoding="utf-8")
        fixture = create_native_fixture(root, projects, native_containers=native_containers)
        factories = fixture["factories"]
        original = {path: path.read_bytes() for path in (root / "native").rglob("*") if path.is_file()}
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        stack.callback(lambda: asyncio.run(backend.close()))
        # A complete old source remains intact even though its former directory
        # is absent. It is evidence, not a reservation for this context label.
        historical_root = root / "old-worktree" / "project"
        historical = asyncio.run(persist_session_snapshot(
            backend,
            Observation(session_id="historical-source", client="codex", raw_content="Earlier cache discussion.",
                        content_type="transcript", metadata={}),
            project_name="project", project_root=str(historical_root), client="codex",
            session_id="historical-source", source_kind="jsonl",
            source_uri=(root / "historical-session.jsonl").as_uri(),
            source_text="User: earlier cache discussion.\nAssistant: review later.\n",
        ))
        assert historical.source is not None
        historical_bytes = backend.transcript_store.reconstruct_raw(historical.source.id)
        stack.enter_context(patch.object(tool_handlers, "_backend_provider", lambda: backend))
        stack.enter_context(patch.object(tool_handlers, "_observer_data_dir_provider", lambda: backend.data_dir))
        stack.enter_context(patch.object(tool_handlers, "_cost_surface_budgets_provider", lambda _: None))
        stack.enter_context(patch("harness_mem.commands.session_inventory.load_merged_config", lambda *_: MergedConfig()))
        stack.enter_context(patch("harness_mem.commands.session_inventory.build_inspection_adapter", lambda client: factories[client]()))
        stack.enter_context(patch("harness_mem.mcp.distill_handlers._session_notes_dir", lambda _: backend.data_dir / "notes"))
        _PAGE_CACHE.clear()
        device = _rpc("inspect_sessions", {})
        assert device["scope"] == "all", device
        # Preserve qualification of the explicit optional legacy source filter;
        # the daily public default is now a flat selected-device flow.
        discovery = discover_session_projects(backend.data_dir)
        discovered = {item["project_root"]: item for item in discovery["projects"]}
        for binding in discovered.values():
            # These arguments come from native discovery, never human input.
            narrowed = _rpc("inspect_sessions", {"project_root": binding["project_root"], "project_name": binding["project_name"]})
            binding["sessions"] = [row for row in narrowed["sessions"] if row["ownership"] == "project"]
        names = [discovered[os.path.normcase(str(project.resolve()))]["project_name"] for project in projects]
        assert names == ["project", "project"], discovery
        checks: dict[str, bool] = {
            "no_directory_input": discovery["success"],
            "context_labels_not_renamed": names == ["project", "project"],
            "historical_roots_do_not_reserve_names": not historical_root.exists(),
            "seven_native_hosts_discovered": all(
                {item["client"] for item in project["sessions"]} == set(HOSTS) for project in discovery["projects"]
            ),
            "discovery_has_no_verified_revision": all(
                row["revision_verified"] is False and row["source_revision"].startswith("metadata:")
                for project in discovery["projects"] for row in project["sessions"]
            ),
        }
        per_host = {client: {"prepared": False, "persisted": False, "retrieved": False, "note_verified": False} for client in HOSTS}
        resumed_job_same = True
        pages_target_only = True
        source_scopes_preserved = True
        full_reader = __import__("harness_mem.commands.session_inventory", fromlist=["inspect_native_source"]).inspect_native_source
        for index, project in enumerate(projects):
            selected = discovered[os.path.normcase(str(project.resolve()))]["sessions"]
            verified_selection = []
            full_reads = []
            def count_full(adapter, client, record, **kwargs):
                full_reads.append((client, record["session_id"]))
                return full_reader(adapter, client, record, **kwargs)
            with patch("harness_mem.commands.session_inventory.inspect_native_source", count_full):
                for source in selected:
                    full_reads.clear()
                    offset = 0
                    page_count = 0
                    while True:
                        page = _rpc("inspect_sessions", {"action": "source", "session": source, "offset": offset, "page_chars": 31})
                        page_count += 1
                        assert page["revision_verified"]
                        if page["next_offset"] is None:
                            break
                        offset = page["next_offset"]
                    pages_target_only &= page_count > 1 and full_reads == [(source["client"], source["session_id"])]
                    verified_selection.append(page["verified_session"])
            packet = _rpc("prepare_session_distill", {"batch_sessions": verified_selection if index else selected})
            batch_id, first_job = packet["batch_id"], packet["distill_job_id"]
            resumed = _rpc("prepare_session_distill", {"batch_id": batch_id})
            resumed_job_same &= resumed["distill_job_id"] == first_job
            packet = resumed
            for _ in selected:
                job = backend.transcript_store.get_distill_job(packet["distill_job_id"])
                assert job is not None and normalized_root(job.project_root) == normalized_root(project), packet
                source_scopes_preserved &= normalized_root(job.project_root) == normalized_root(project)
                client = job.client
                token = f"{client}policy{index}"
                statement = f"{token}: Keep only verified current cache entries for workspace {index}."
                policy = project / "policy.txt"
                suggestion = _rpc("govern_memory", {"action": "suggest", "arguments": {
                    "kind": "memory", "project_name": job.project_name, "category": "decision", "content": statement,
                    "source": f"distill-job:{job.id}", "distill_job_id": job.id,
                    "evidence_basis": "repository", "verification_outcome": "verified",
                    "verification_refs": [{"kind": "repository", "locator": "policy.txt", "content_sha256": hashlib.sha256(policy.read_bytes()).hexdigest()}],
                    "assimilation_disposition": "add", "assimilation_reason": "Verified fictional workspace cache policy.",
                    "canonical_title": f"{client} cache policy", "topic_path": ["Cache"],
                }})
                assert suggestion["success"], suggestion
                final = _rpc("finalize_session_distill", {"project_name": job.project_name, "job_id": job.id,
                    "semantic_review": {"session_summary": "Verified fictional cache policy.", "final_user_request": f"Verify {token}.",
                                        "final_outcome": "Verified policy saved.", "last_turn_status": "answered",
                                        "contradictions": [], "unfinished_work": [], "evidence_status": "answered", "promotion_decision": "promote"}})
                found = _rpc("search_memory", {"project_name": job.project_name, "query": token, "scope": "project"})
                note = Path(final["note"]["path"])
                per_host[client] = {
                    "prepared": job.source_revision.startswith("sha256:"),
                    "persisted": bool(final["knowledge_changes"]),
                    "retrieved": any(row["statement"] == statement for row in found["memories"]),
                    "note_verified": note.is_file() and statement in note.read_text(encoding="utf-8")
                                     and hashlib.sha256(note.read_bytes()).hexdigest() == final["note"]["sha256"],
                }
                assert all(per_host[client].values()), {client: per_host[client]}
                packet = _rpc("prepare_session_distill", {"batch_id": batch_id})
            assert packet["status"] == "completed" and packet["progress"]["completed"] == 7, packet
        # Independently reopen the durable store, then use the ordinary MCP reader.
        asyncio.run(backend.close())
        backend = LocalMemoryBackend(root / "data")
        asyncio.run(backend.init())
        current = _rpc("search_memory", {"query": ""})
        checks.update({
            "seven_host_complete_flow": all(all(result.values()) for result in per_host.values()),
            "batch_resumes_same_job": resumed_job_same,
            "truth_retrievable_after_reopen": len(current["memories"]) == 14,
            "global_retrieval_default": current.get("project_name") is None and len(current["memories"]) == 14,
            "source_scopes_preserved": source_scopes_preserved,
            "historical_source_preserved": backend.transcript_store.reconstruct_raw(historical.source.id) == historical_bytes,
            "native_sources_preserved": all(path.read_bytes() == content for path, content in original.items()),
            "paged_reads_target_only": pages_target_only,
            "seven_host_registration_retained": set(AdapterRegistry.list_capabilities()) == set(HOSTS),
        })
        return {"verified": all(checks.values()), **checks, "hosts": per_host,
                "semantic_mode": "deterministic_fixture_agent", "native_apps_or_hooks": "not_run"}


def run_automatic_projects_outcome_probe() -> dict:
    files = _run_native_variant(native_containers=False)
    containers = _run_native_variant(native_containers=True)
    booleans = {key: bool(value and containers.get(key)) for key, value in files.items() if isinstance(value, bool)}
    return {**booleans, "verified": files["verified"] and containers["verified"],
            "native_variant_count": 2, "variants": {"files": files, "containers_and_archives": containers},
            "semantic_mode": "deterministic_fixture_agent", "native_apps_or_hooks": "not_run"}


def main() -> int:
    from harness_mem.embedding.model_loader import temporarily_disable_embeddings
    with temporarily_disable_embeddings():
        result = run_automatic_projects_outcome_probe()
    output = (json.dumps(result, sort_keys=True) + "\n").encode("utf-8")
    os.write(getattr(server, "_REAL_STDOUT_FD", 1), output)
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
