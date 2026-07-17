"""Ingest command implementation."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast

from harness_mem import __version__
from harness_mem.adapters import AdapterRegistry
from harness_mem.adapters.codex.archive_adapter import CodexArchiveAdapter
from harness_mem.adapters.claude_code.adapter import ClaudeCodeAdapter
from harness_mem.adapters.parser import extract_claude_session_cwd
from harness_mem.adapters.protocol import SessionRecord
from harness_mem.adapters.scan_scheduler import normalize_source_root, sync_sessions_fairly
from harness_mem.adapters.snapshot import TranscriptSyncResult
from harness_mem.adapters.claude_code.project_profile_detector import (
    build_project_profile,
    normalize_project_root,
)
from harness_mem.commands.support import (
    DEFAULT_DATA_DIR,
    claude_project_name_candidates_from_path,
    ensure_project_profile,
    log_cli_event,
    log_command_invoked,
    project_adapter_cursor_path,
    resolve_host_source,
    resolve_ingest_client,
    resolve_project_context,
    set_active_project,
)
from harness_mem.core.schemas.project_profile import ProjectProfile
from harness_mem.event_log import EventType
from harness_mem.storage.local_memory_backend import LocalMemoryBackend
from harness_mem.storage.local_project_profile_store import LocalProjectProfileStore


async def cmd_ingest(
    client: str,
    project_name: str | None = None,
    limit: int = 10,
    full_rescan: bool = False,
    scope: str = "project",
    project_root: str | None = None,
) -> int:
    """Ingest sessions for a supported client."""
    requested_client = client
    client = resolve_ingest_client(client)
    if client != requested_client:
        print(f"Auto-detected ingest client: {client}")
    host_source = resolve_host_source(requested_client)

    resolved_project_root = _resolve_project_root(project_root)
    project_context = resolve_project_context(
        project_name,
        project_root=resolved_project_root,
        required=True,
        action_label=f"{client} ingest",
    )
    if project_context is None:
        return 1
    project_name = project_context.project_name

    backend = LocalMemoryBackend(DEFAULT_DATA_DIR)
    await backend.init()
    try:
        profile_store = LocalProjectProfileStore(DEFAULT_DATA_DIR)
        await ensure_project_profile(project_name, resolved_project_root)

        if client not in AdapterRegistry.list():
            print(
                f"No native ingest adapter for {host_source.host_client} yet. "
                "Hook-based wake/maintenance can still run, but transcript ingest "
                f"for this host is not implemented in harness-mem {__version__} yet."
            )
            return 1

        if client == "claude-code":
            return await _ingest_claude_code(
                backend,
                profile_store,
                project_name=project_name,
                limit=limit,
                full_rescan=full_rescan,
                project_root=resolved_project_root,
            )
        if client == "codex-archive":
            return await _ingest_codex_archive(
                backend,
                project_name=project_name,
                limit=limit,
                full_rescan=full_rescan,
                scope=scope,
                project_root=resolved_project_root,
            )

        print(f"Ingesting {client} sessions for project: {project_name}")
        adapter_kwargs: dict[str, object] = {}
        if client in {"cursor", "codex", "grok", "hermes", "opencode", "antigravity"}:
            adapter_kwargs["project_root"] = resolved_project_root
        if client in {"codex", "hermes"}:
            adapter_kwargs["scope"] = scope
        adapter = AdapterRegistry.build(client, backend, **adapter_kwargs)
        if full_rescan:
            source_root = _adapter_source_root(adapter)
            if source_root is not None:
                backend.transcript_store.reset_scan_frontier(
                    project_name=project_name,
                    client=client,
                    source_root=normalize_source_root(source_root),
                )
        result = await adapter.ingest(project_name=project_name, limit=limit, min_size_kb=0)
        return _report_non_claude_ingest_result(
            client=client,
            project_name=project_name,
            result=result,
            full_rescan=full_rescan,
        )
    finally:
        await backend.close()


async def _ingest_claude_code(
    backend: LocalMemoryBackend,
    profile_store: LocalProjectProfileStore,
    *,
    project_name: str,
    limit: int,
    full_rescan: bool,
    project_root: Path,
) -> int:
    adapter = cast(ClaudeCodeAdapter, AdapterRegistry.build("claude-code", backend))
    profile = await profile_store.get(project_name)
    session_project_name, all_sessions = _list_claude_sessions_for_current_project(
        adapter,
        project_name=project_name,
        project_root=project_root,
    )
    last_session_id = profile.last_ingest_session_id if profile and not full_rescan else None

    print(f"Ingesting claude-code sessions for project: {project_name}")
    if session_project_name != project_name:
        print(f"Claude session project: {session_project_name}")
    print(f"Project root: {project_root}")
    candidate_sessions = all_sessions

    async def sync_one(session: SessionRecord) -> TranscriptSyncResult:
        return await adapter.sync_session(
            session["path"],
            session["session_id"],
            project_name,
            project_root=project_root,
        )

    source_root = (
        candidate_sessions[0]["path"].parent
        if candidate_sessions
        else adapter.sessions_dir / session_project_name
    )
    if full_rescan:
        backend.transcript_store.reset_scan_frontier(
            project_name=project_name,
            client="claude-code",
            source_root=normalize_source_root(source_root),
        )
    scan = await sync_sessions_fairly(
        backend.transcript_store,
        project_name=project_name,
        client="claude-code",
        source_root=source_root,
        sessions=candidate_sessions,
        change_limit=limit,
        sync_session=sync_one,
    )
    ingested = scan.ingested
    updated = scan.updated
    unchanged = scan.unchanged
    errors = len(scan.failures)

    newest_seen_session_id = last_session_id
    if all_sessions:
        newest_seen_session_id = all_sessions[0]["session_id"]

    print(f"Sessions found: {len(all_sessions)}")
    print(f"Ingested: {ingested} sessions")
    if updated > 0:
        print(f"Updated: {updated} sessions")
    if unchanged > 0:
        print(f"Unchanged: {unchanged} sessions")
    if errors > 0:
        print(f"Errors: {errors}")

    if profile is None:
        profile = ProjectProfile(project_name=project_name)
    if newest_seen_session_id is not None:
        profile.last_ingest_session_id = newest_seen_session_id
    if candidate_sessions or full_rescan:
        profile.last_ingest_at = datetime.now(timezone.utc)
    await profile_store.save(profile)

    if not profile.stacks:
        sessions_dir_value = getattr(adapter, "sessions_dir", Path.home() / ".claude" / "projects")
        sessions_dir = sessions_dir_value if isinstance(sessions_dir_value, Path) else Path(str(sessions_dir_value))
        project_path = _infer_claude_project_root(
            all_sessions,
            fallback_project_path=project_root if project_root.exists() else sessions_dir / session_project_name,
        )
        if project_path.exists():
            detected = build_project_profile(project_path, project_name)
            profile.stacks = detected.stacks
            profile.key_files = detected.key_files
            await profile_store.save(profile)
            detected_parts = [*profile.stacks, *profile.key_files[:3]]
            if detected_parts:
                print(f"Auto-detected profile: {', '.join(detected_parts)}")
            else:
                print("Auto-detected profile: no stack or key files found")

    set_active_project(project_name)
    extra = {
        "client": "claude-code",
        "ingested": ingested,
        "updated": updated,
        "unchanged": unchanged,
        "sessions_found": len(all_sessions),
        "full_rescan": full_rescan,
    }
    log_command_invoked("ingest", project_name=project_name, extra=extra)
    log_cli_event(
        EventType.SESSION_INGESTED,
        project_name=project_name,
        command="ingest",
        extra=extra,
    )
    return 0


async def _ingest_codex_archive(
    backend: LocalMemoryBackend,
    *,
    project_name: str,
    limit: int,
    full_rescan: bool,
    scope: str,
    project_root: Path,
) -> int:
    print(f"Ingesting codex-archive sessions for project: {project_name}")
    print(f"Scope: {scope}")
    if scope == "project":
        print(f"Project root: {project_root}")
    adapter = AdapterRegistry.build("codex-archive", backend)
    if not isinstance(adapter, CodexArchiveAdapter):
        raise TypeError("codex-archive adapter registry returned an unexpected adapter type")
    result = await adapter.ingest(
        project_name=project_name,
        limit=limit,
        min_size_kb=0,
        full_rescan=full_rescan,
        cursor_path=project_adapter_cursor_path(project_name, "codex-archive"),
        project_root=project_root,
        scope=scope,
    )
    return _report_non_claude_ingest_result(
        client="codex-archive",
        project_name=project_name,
        result=result,
        full_rescan=full_rescan,
    )


def _resolve_project_root(project_root: str | None) -> Path:
    if project_root:
        return normalize_project_root(Path(project_root).expanduser())
    return normalize_project_root(Path.cwd())


def _adapter_source_root(adapter: Any) -> Path | None:
    for name in (
        "source_root",
        "database_path",
        "projects_dir",
        "sessions_dir",
        "brain_dir",
        "archive_dir",
    ):
        value = getattr(adapter, name, None)
        if value is not None:
            return Path(value)
    return None


def _list_claude_sessions_for_current_project(
    adapter: Any,
    *,
    project_name: str,
    project_root: Path,
) -> tuple[str, list[SessionRecord]]:
    candidates = [project_name]
    for path_project_name in reversed(claude_project_name_candidates_from_path(project_root)):
        if path_project_name and path_project_name not in candidates:
            candidates.insert(0, path_project_name)
    for matched_project_name in _claude_project_names_matching_project(adapter, project_name):
        if matched_project_name and matched_project_name not in candidates:
            candidates.append(matched_project_name)

    for candidate in candidates:
        sessions = adapter.list_sessions(candidate, min_size_kb=0)
        if sessions:
            return candidate, sessions
    return candidates[0], []


def _claude_project_names_matching_project(adapter: Any, project_name: str) -> list[str]:
    sessions_dir_value = getattr(adapter, "sessions_dir", None)
    if not sessions_dir_value:
        return []
    sessions_dir = sessions_dir_value if isinstance(sessions_dir_value, Path) else Path(str(sessions_dir_value))
    if not sessions_dir.exists() or not sessions_dir.is_dir():
        return []
    project_key = _normalized_claude_project_key(project_name)
    matches: list[tuple[float, str]] = []
    for project_dir in sessions_dir.iterdir():
        if not project_dir.is_dir():
            continue
        dir_key = _normalized_claude_project_key(project_dir.name)
        if not (dir_key == project_key or dir_key.endswith(f"-{project_key}")):
            continue
        latest_mtime = max(
            (session.stat().st_mtime for session in project_dir.glob("*.jsonl")),
            default=project_dir.stat().st_mtime,
        )
        matches.append((latest_mtime, project_dir.name))
    return [name for _, name in sorted(matches, reverse=True)]


def _normalized_claude_project_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")


def _select_claude_candidate_sessions(
    all_sessions: list[SessionRecord],
    *,
    limit: int,
    full_rescan: bool,
    last_session_id: str | None,
    last_ingest_at: datetime | None,
) -> list[SessionRecord]:
    if full_rescan:
        print("[Full Rescan] Processing all sessions without cursor shortcuts.")
        return all_sessions[:limit]

    if not last_session_id:
        return all_sessions[:limit]

    candidate_sessions: list[SessionRecord] = []
    cursor_found = False
    for session in all_sessions:
        if session["session_id"] == last_session_id:
            cursor_found = True
            break
        candidate_sessions.append(session)

    if cursor_found:
        print(f"[Incremental] Processing sessions newer than cursor: {last_session_id}")
        return candidate_sessions[:limit]

    print(
        f"Warning: ingest cursor {last_session_id} not found; "
        "falling back to sessions newer than last ingest timestamp."
    )
    if last_ingest_at is not None:
        candidate_sessions = [
            session for session in all_sessions if session.get("mtime") and session["mtime"] > last_ingest_at
        ]
        return candidate_sessions[:limit]

    return all_sessions[:limit]


def _infer_claude_project_root(
    sessions: list[SessionRecord],
    *,
    fallback_project_path: Path,
) -> Path:
    for session in sessions[:5]:
        session_path = session.get("path")
        if session_path is None:
            continue
        cwd = extract_claude_session_cwd(Path(session_path))
        if cwd is None:
            continue
        project_root = normalize_project_root(cwd)
        if project_root.exists():
            return project_root

    return fallback_project_path


def _report_non_claude_ingest_result(
    *,
    client: str,
    project_name: str,
    result: dict,
    full_rescan: bool,
) -> int:
    for warning in result.get("warnings", []):
        print(f"Warning: {warning['message']}")

    changed_count = int(result.get("ingested", 0)) + int(result.get("updated", 0))
    exit_code = 1 if result["errors"] > 0 and changed_count == 0 else 0
    scoped_sessions = result.get("scoped_sessions")
    if (
        result.get("scope") == "project"
        and isinstance(scoped_sessions, int)
        and result.get("sessions_found", 0) > 0
        and scoped_sessions == 0
    ):
        exit_code = 1
    extra = {"client": client, **result, "full_rescan": full_rescan, "exit_code": exit_code}

    if result["sessions_found"] == 0:
        log_command_invoked("ingest", project_name=project_name, extra=extra)
        log_cli_event(
            EventType.SESSION_INGESTED,
            project_name=project_name,
            command="ingest",
            extra=extra,
        )
        print(f"No {client} sessions found.")
        return 1

    print(f"Sessions found: {result['sessions_found']}")
    if isinstance(scoped_sessions, int):
        print(f"Project-scope sessions: {scoped_sessions}")
        if result.get("scope") == "project" and scoped_sessions == 0:
            root = result.get("project_root") or "<unknown>"
            print(
                f"No {client} sessions matched current project root: {root}. "
                "Run from the target project directory, pass --project-root, or use --scope all explicitly."
            )
    candidate_sessions = result.get("candidate_sessions")
    if isinstance(candidate_sessions, int):
        print(f"Candidates after cursor: {candidate_sessions}")
    print(f"Ingested: {result['ingested']} sessions")
    updated = result.get("updated", 0)
    if isinstance(updated, int) and updated > 0:
        print(f"Updated: {updated} sessions")
    unchanged = result.get("unchanged", result.get("skipped_existing", 0))
    if isinstance(unchanged, int) and unchanged > 0:
        print(f"Unchanged: {unchanged} sessions")
    for error in result.get("error_details", []):
        print(f"Error: {error['message']}")
    if result["errors"] > 0:
        print(f"Errors: {result['errors']}")
    if exit_code == 0:
        set_active_project(project_name)

    log_command_invoked("ingest", project_name=project_name, extra=extra)
    log_cli_event(
        EventType.SESSION_INGESTED,
        project_name=project_name,
        command="ingest",
        extra=extra,
    )
    return exit_code
